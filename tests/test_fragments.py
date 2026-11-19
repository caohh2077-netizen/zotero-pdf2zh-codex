from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack
import json
import os
from pathlib import Path
import shlex
import socket
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"src"))
import engine_bridge
from adapter import appserver
from adapter import codex_translate as cli
from fragments import Fragments
from managed_jobs import Job, ManagedJobs, command
from options import Selection
from winjob import execution_slot, resident_slot


class FragmentsContract(unittest.TestCase):
    def test_selection_and_parts(self):
        catalog={"models":[{"id":"gpt-6.2-sol","efforts":["low","xhigh"]}]}
        data={"codex":{"protocol":2,"model":"gpt-6.2-sol","effort":"xhigh"},"qps":"33","poolSize":"0"}
        self.assertEqual(Selection.parse(data,catalog).workers,20)
        for value in (21,-1,True,1.3):
            with self.assertRaises(ValueError):
                Selection.parse(dict(data,poolSize=value),catalog)
        with self.assertRaises(ValueError):
            Selection.parse(dict(data,codex=dict(data["codex"],effort="other")),catalog)
        f=Fragments()
        def report(i,current,n,kind):
            f.update(dict(stage="Translate Paragraphs",type=kind,part_index=i,total_parts=2,stage_current=current,stage_total=n))
        self.assertIsNone(f.snapshot()["total"])
        report(1,0,3,"progress_start")
        report(1,2,3,"progress_update")
        report(1,1,3,"progress_update")
        self.assertEqual(f.snapshot()["current"],2)
        report(1,3,3,"progress_end")
        report(1,0,3,"progress_start")
        self.assertIsNone(f.snapshot()["total"])
        report(2,0,0,"progress_start")
        report(2,0,0,"progress_end")
        self.assertEqual((f.snapshot()["current"],f.snapshot()["total"],f.stage),(3,3,"typeset"))
        for event in ("end", "start", "end", "start"):
            f.update({"event":event, "id":"segment-1", "result":"network"})
        self.assertEqual((f.calls, f.failed), (1, 1))

    def test_global_slots_across_documents(self):
        # Forty independent tasks across two documents share the same Win32 slot set.
        for limit in (10,20):
            entered=0
            peak=0
            lock=threading.Lock()
            full=threading.Event()
            def work(n):
                nonlocal entered,peak
                with execution_slot("test-"+str(os.getpid()),20):
                    with lock:
                        entered+=1
                        peak=max(peak,entered)
                        if entered==limit:
                            full.set()
                    if not full.wait(8):
                        raise AssertionError("Concurrent workers did not reach barrier")
                    time.sleep(.02)
                    with lock:
                        entered-=1
            with ThreadPoolExecutor(max_workers=limit if limit==10 else 32) as pool:
                list(pool.map(work,range(40)))
            self.assertEqual(peak,limit)

    def test_disconnect_attempt_limit_partial_and_cache(self):
        from pdf2zh_next.config import ConfigManager
        from pdf2zh_next.translator.translator_impl.clitranslator import CLITranslatorTranslator
        from pdf2zh_next.translator.rate_limiter.qps_rate_limiter import QPSRateLimiter
        with tempfile.TemporaryDirectory() as work:
            slot=Path(work)
            (slot/"managed/state").mkdir(parents=True)
            (slot/"runtime/Scripts").mkdir(parents=True)
            (slot/"runtime/Scripts/python.exe").touch()
            (slot/"settings.json").write_text(json.dumps({"root":work,"codex":sys.executable}))
            calls=[]
            # The synthetic CLI connects to a closed loopback port for exactly one
            # marked paragraph. Its own process reports the final network failure.
            def invoke(binary,env,source,target,text,deadline,model,effort,prompt):
                calls.append((text,model,effort))
                if text=="recover" and sum(t==text for t,_,_ in calls)==1:
                    raise cli.Failure("network")
                if text=="broken":
                    code="import socket,sys;s=socket.socket();sys.exit(s.connect_ex(('127.0.0.1',int(sys.argv[1]))) != 0)"
                    with socket.socket() as listener:
                        listener.bind(("127.0.0.1",0))
                        res=subprocess.run([sys.executable,"-I","-c",code,str(listener.getsockname()[1])])
                    self.assertNotEqual(res.returncode,0)
                    raise cli.Failure("network")
                return "译 "+text
            def create(model,effort):
                opts=slot/"test.toml"
                cli_cmd=command(slot,"en","zh-CN",model,effort)
                opts.write_text("[clitranslator_detail]\nclitranslator_command="+json.dumps(cli_cmd)+"\n")
                with patch.object(sys,"argv",["pdf2zh_next","--clitranslator","--config-file",str(opts)]):
                    config=ConfigManager().initialize_config()
                engine=CLITranslatorTranslator(config,QPSRateLimiter(1000))
                self.assertTrue(engine_bridge.bind(engine))
                return engine
            with patch.object(engine_bridge,"SLOT",slot), patch.dict(os.environ,{"ZPC_JOB_DIR":work}), \
                 patch.object(cli,"ensure_cli"),patch.object(cli,"invoke",invoke):
                e=create("gpt-6.2-sol","xhigh")
                self.assertEqual(calls,[])
                self.assertEqual(e.translate("Hello"),"译 Hello")
                self.assertEqual(e.translate("broken"),"broken")
                self.assertEqual(e.translate("done"),"译 done")
                self.assertEqual(e.translate("broken"),"broken")
                rows=[json.loads(x) for x in (slot/"dispatch.jsonl").read_text().splitlines()]
                failed=[r for r in rows if r.get("result")=="network"]
                self.assertEqual([r["final"] for r in failed],[False,False,True])
                self.assertEqual(len({r["fragmentId"] for r in failed}),1)
                self.assertEqual([x[0] for x in calls],["Hello","broken","broken","broken","done"])
                before=len(calls)
                hot=create("gpt-6.2-sol","xhigh")
                self.assertEqual(hot.translate("done"),"译 done")
                self.assertEqual(hot.translate("Hello"),"译 Hello")
                self.assertEqual(len(calls),before)
                self.assertEqual(create("gpt-6.2-sol","low").translate("done"),"译 done")
                self.assertEqual(create("gpt-6.2-astra","low").translate("done"),"译 done")
                self.assertEqual(len(calls),before+2)
                with ThreadPoolExecutor(10) as pool:
                    self.assertEqual(list(pool.map(e.translate,["recover"]*10)),["译 recover"]*10)
                self.assertEqual(sum(t=="recover" for t,_,_ in calls),2)
                self.assertEqual(hot.translate("recover"),"译 recover")
                self.assertEqual(sum(t=="recover" for t,_,_ in calls),2)

    def test_recovered_cli_stream(self):
        rows=[{"type":"error","message":"reconnecting 1/2"},{"type":"item.completed","item":{"type":"agent_message","text":"好"}},
              {"type":"turn.completed"}]
        self.assertEqual(cli.final_text("\n".join(map(json.dumps,rows))),"好")

    def test_retry_policy_and_fragment_progress(self):
        for code in ("rate","quota","login","model","network","timeout","format","server","cli","config","tools","failed"):
            with self.subTest(code=code), tempfile.TemporaryDirectory() as directory:
                root=Path(directory)
                state=root/"managed/state"
                state.mkdir(parents=True)
                settings={"root":directory, "codex":sys.executable}
                env=dict(cli.environment(),TEMP=directory)
                clock=[1000.]
                def sleep(seconds):
                    clock[0]+=seconds
                with patch.object(cli,"environment",return_value=env), patch.object(cli,"ensure_cli"), \
                     patch.object(time,"monotonic",side_effect=lambda:clock[0]), patch.object(time,"time",side_effect=lambda:clock[0]), \
                     patch.object(time,"sleep",side_effect=sleep), \
                     patch.dict(os.environ,{"ZPC_JOB_DIR":directory}), \
                     patch.object(cli,"invoke",side_effect=cli.Failure(code)) as call:
                    with self.assertRaisesRegex(cli.Failure,code):
                        cli.translate(settings,"en","zh-CN","data","gpt-6.2-sol","xhigh")
                rows=[json.loads(line) for line in (root/"dispatch.jsonl").read_text().splitlines()]
                expected=3 if code in ("rate","network","timeout","format","server") else 1
                self.assertEqual(call.call_count,expected)
                self.assertEqual(len({r["fragmentId"] for r in rows}),1)
                self.assertEqual([r["attempt"] for r in rows if r["event"]=="start"],list(range(1,expected+1)))
                progress=Fragments()
                for row in rows:
                    progress.update(row)
                    progress.update(row)
                    if row["event"]=="end":
                        self.assertEqual(progress.snapshot()["retrying"],int(not row["final"]))
                        self.assertEqual(progress.failed,int(row["final"]))
                self.assertEqual(progress.calls,expected)
                self.assertEqual(clock[0]-1000,4 if expected==3 else 0)

    def test_deadline_and_recovery(self):
        for delays,expected in (([600], "timeout"), ([598,1], "timeout"), ([12,2], "ok")):
            with self.subTest(delays=delays), tempfile.TemporaryDirectory() as folder:
                root=Path(folder)
                (root/"managed/state").mkdir(parents=True)
                clock=[150.]
                prompts=[]
                def advance(seconds):
                    clock[0]+=seconds
                def invoke(binary,env,source,target,text,deadline,model,effort,prompt):
                    self.assertEqual(deadline,750.)
                    prompts.append(prompt)
                    advance(delays[len(prompts)-1])
                    if len(prompts)==1:
                        raise cli.Failure("timeout" if delays[0]==600 else "network")
                    return "中文"
                with patch.object(cli,"environment",return_value=dict(cli.environment(),TEMP=folder)), patch.object(cli,"ensure_cli"), \
                     patch.dict(os.environ,{"ZPC_JOB_DIR":folder}), patch.object(cli,"invoke",invoke), \
                     patch.object(time,"monotonic",side_effect=lambda:clock[0]), patch.object(time,"sleep",side_effect=advance):
                    def run():
                        return cli.translate({"root":folder,"codex":sys.executable},"en","zh-CN","source",prefix="Custom opening.")
                    if expected=="ok":
                        self.assertEqual(run(),"中文")
                    else:
                        with self.assertRaisesRegex(cli.Failure,"timeout"): run()
                self.assertEqual(len(prompts),len(delays))
                self.assertEqual(len(set(prompts)),1)
                rows=[json.loads(s) for s in (root/"dispatch.jsonl").read_text().splitlines()]
                progress=Fragments()
                for row in rows: progress.update(row)
                self.assertEqual((progress.failed,len(progress.retrying)),(int(expected!="ok"),0))

    def test_terminal_diagnostic_and_retry_after(self):
        stream="\n".join(map(json.dumps,[
            {"type":"error","message":"reconnecting"},
            {"type":"turn.failed","error":"HTTP 503. Retry-After: 7"},
        ]))
        err=cli.exit_failure(stream,"CLI exited")
        self.assertEqual((str(err),err.retry_after),("server",7))
        self.assertEqual(cli.classify('HTTP 503 Service Temporarily Unavailable'),"server")
        self.assertEqual(str(cli.exit_failure("HTTP 502 Bad Gateway","")),"server")
        answer=json.dumps({"type":"item.completed","item":{"type":"agent_message","text":"a network connection"}})
        self.assertEqual(str(cli.exit_failure(answer,"unknown error")),"failed")

    def test_service_retry_after_respects_fragment_budget(self):
        for retry_after,expected_starts in ((7,[0,7,14]),(700,[0])):
            with self.subTest(retry_after=retry_after), tempfile.TemporaryDirectory() as folder:
                (Path(folder)/"managed/state").mkdir(parents=True)
                clock=[0.]
                starts=[]
                def advance(seconds):
                    clock[0]+=seconds
                def unavailable(*args):
                    starts.append(clock[0])
                    raise cli.Failure.from_response(f"HTTP 503. Retry-After: {retry_after}")
                with patch.object(cli,"environment",return_value=dict(cli.environment(),TEMP=folder)), patch.object(cli,"ensure_cli"), \
                     patch.object(cli,"invoke",unavailable), patch.object(time,"monotonic",side_effect=lambda:clock[0]), \
                     patch.object(time,"sleep",side_effect=advance), patch.dict(os.environ,{"ZPC_JOB_DIR":folder}):
                    with self.assertRaisesRegex(cli.Failure,"server"):
                        cli.translate({"root":folder,"codex":sys.executable},"en","zh-CN","source")
                self.assertEqual(starts,expected_starts)

    def test_idle_pool_counts_toward_resident_limit(self):
        scope="idle-test-"+str(os.getpid())
        class FakeWorker:
            def __init__(self,*args): self.residency=ExitStack()
            def run(self,*args): return "译"
            def close(self): self.residency.close()
        pool=appserver.Pool()
        entered=threading.Event()
        def standalone():
            with resident_slot(scope,1):
                entered.set()
        with patch.object(appserver,"Worker",FakeWorker), patch.object(appserver,"resident_slot",lambda name,**kw:resident_slot(name,1,**kw)):
            try:
                with pool.reserve(scope) as dispatch:
                    self.assertEqual(dispatch(None,None,"en","zh","test",0,"model","low"),"译")
                with ThreadPoolExecutor(1) as executor:
                    future=executor.submit(standalone)
                    try:
                        self.assertFalse(entered.wait(.25))
                    finally:
                        pool.close()
                    future.result(3)
                self.assertTrue(entered.is_set())
            finally:
                pool.close()

    def test_resident_slot_released_by_process_exit(self):
        scope="abandon-test-"+str(os.getpid())
        script=("import os,sys; sys.path.insert(0,sys.argv[1]); from winjob import resident_slot; "
                "slot=resident_slot(sys.argv[2],1); slot.__enter__(); print('ready',flush=True); "
                "sys.stdin.buffer.read(); os._exit(0)")
        with subprocess.Popen([sys.executable,"-I","-c",script,str(ROOT/"src"),scope],stdin=subprocess.PIPE,stdout=subprocess.PIPE) as child:
            self.assertEqual(child.stdout.readline().strip(),b"ready")
            acquired=threading.Event()
            def second():
                with resident_slot(scope,1): acquired.set()
            with ThreadPoolExecutor(1) as executor:
                future=executor.submit(second)
                try:
                    self.assertFalse(acquired.wait(.25))
                finally:
                    child.stdin.close()
                future.result(4)
            self.assertTrue(acquired.is_set())

    def test_products_and_existing_name(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            server=ManagedJobs.__new__(ManagedJobs)
            server.output=root/"out"
            server.output.mkdir()
            for version in (1,2):
                work=root/str(version)
                work.mkdir()
                options=Selection("gpt-6.2-sol","xhigh",10,10)
                job=Job(work,options,"中文研究","paper",str(version))
                files=[work/"paper.no_watermark.zh-CN.mono.pdf",work/"paper.no_watermark.zh-CN.LR_dual.pdf"]
                for file in files:
                    file.write_bytes(bytes([version]))
                result=server.publish(files,job,lambda raw:"mono" if ".mono" in str(raw) else "dual")
                self.assertEqual([p["kind"] for p in result["products"]],["mono","dual"])
                self.assertTrue(all(n.endswith("__gpt-6.2-sol__xhigh.pdf") for n in result["fileList"]))
            self.assertEqual(sorted(p.read_bytes() for p in server.output.iterdir()),[b"\x01",b"\x01",b"\x02",b"\x02"])
