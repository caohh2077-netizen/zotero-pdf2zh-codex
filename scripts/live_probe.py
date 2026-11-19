"""Submit only the bundled synthetic sample to a local managed backend."""
import argparse
import base64
import json
from pathlib import Path
import sys
import time
from urllib.request import ProxyHandler,Request,build_opener
import psutil
import pymupdf

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"fixtures"))
from sample import make
from tempfile import TemporaryDirectory

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--root",type=Path,required=True)
    p.add_argument("--port",type=int,required=True)
    p.add_argument("--observe",type=Path)
    p.add_argument("--check-released",type=Path)
    a=p.parse_args()
    if a.check_released:
        snap=json.loads(a.check_released.read_text("utf-8"))
        remaining=[]
        for pid,created in snap["processes"]:
            try:
                if abs(psutil.Process(pid).create_time()-created)<.01:
                    remaining.append(pid)
            except psutil.NoSuchProcess:
                pass
        import socket
        with socket.socket() as sock:
            listening=sock.connect_ex(("127.0.0.1",a.port))==0
        print(json.dumps({"remaining":remaining,"listening":listening}))
        return int(bool(remaining) or listening)
    state=json.loads((a.root/"managed/state"/f"session-{a.port}.json").read_text("utf-8"))
    opener=build_opener(ProxyHandler({}))
    base=f"http://127.0.0.1:{a.port}"
    with opener.open(base+"/health",timeout=3) as r:
        health=json.load(r)
    expected=a.root/"managed/releases"/state["slot"]/"server/translated"
    if Path(health["outputDir"]).resolve()!=expected.resolve():
        raise ValueError("Unexpected server")
    with TemporaryDirectory() as work:
        source=Path(work)/"sample.pdf"
        make(source)
        with pymupdf.open(source) as doc:
            doc[0].insert_text((72,245),f"Trial identifier {int(time.time())}.")
            content=base64.b64encode(doc.tobytes()).decode("ascii")
    payload={"engine":"pdf2zh_next","next_service":"clitranslator","fileName":f"Codex-probe-{int(time.time())}.pdf",
             "fileContent":content,"sourceLang":"en","targetLang":"zh-CN","qps":1,"poolSize":1,"noMono":True,
             "noDual":False,"dual":True,"mono":False,"disableGlossary":True,"asyncJob":True}
    if health.get("codexProtocol")==2:
        payload.update(qps=10,poolSize=10,codex={"protocol":2,"model":"gpt-6.2-sol","effort":"xhigh"})
    req=Request(base+"/translate",data=json.dumps(payload).encode(),headers={"Content-Type":"application/json"})
    with opener.open(req,timeout=15) as r:
        result=json.load(r)
    print("Accepted",result.get("taskId"),flush=True)
    if a.observe:
        backend=psutil.Process(state["backend_pid"])
        until=time.monotonic()+90
        while time.monotonic()<until:
            tree=[backend]+backend.children(recursive=True)
            try:
                cli=[x for x in tree if x.name().lower()=="codex.exe" and "exec" in x.cmdline()]
                if cli:
                    snap={"backend":backend.pid,"owner":state["owner_pid"],"codex":cli[0].pid,
                          "processes":[[x.pid,x.create_time()] for x in tree]}
                    a.observe.write_text(json.dumps(snap),encoding="utf-8")
                    print("Observed Codex process and owned tree:",len(tree))
                    return 0
            except psutil.NoSuchProcess:
                pass
            time.sleep(.2)
        raise ValueError("No live Codex exec observed")
    return 0

if __name__=="__main__":
    sys.exit(main())
