"""Check a real bilingual PDF after a synthetic CLI subprocess loses a connection."""
import argparse
import asyncio
import json
import os
import re
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import unicodedata
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]


async def check(slot, work, scenario):
    sys.path[:0]=[str(slot/"pkg/src"),str(ROOT/"fixtures")]
    import pymupdf
    from sample import make
    from adapter import codex_translate as cli
    import engine_bridge
    from fragments import Fragments
    from managed_jobs import command
    from pdf2zh_next.config import ConfigManager
    from pdf2zh_next.high_level import create_babeldoc_config, babeldoc_translate
    source=work/"partial.pdf"
    make(source)
    before=source.read_bytes()
    state=work/"managed/state"
    state.mkdir(parents=True)
    cfg=work/"input.toml"
    cfg.write_text("[clitranslator_detail]\nclitranslator_command="+
                   json.dumps(command(slot,"en","zh-CN","gpt-6.2-sol","xhigh"))+"\n",encoding="utf-8")
    args=["pdf2zh_next",str(source),"--clitranslator","--config-file",str(cfg),"--output",str(work),
          "--lang-in","en","--lang-out","zh-CN","--qps","10","--no-mono","--no-auto-extract-glossary",
          "--ignore-cache","--watermark-output-mode","no_watermark"]
    attempts=[]
    def fake(binary, env, source, target, text, deadline, model, effort, prompt):
        if "We tested" in text:
            attempts.append((text,prompt,deadline))
            if scenario=="exhausted" or len(attempts)==1:
                with socket.socket() as sock:
                    sock.bind(("127.0.0.1",0))
                    port=sock.getsockname()[1]
                    rc=subprocess.run([sys.executable,"-I","-c","import socket,sys; socket.create_connection(('127.0.0.1',int(sys.argv[1])),2)",str(port)],
                                      stderr=subprocess.DEVNULL).returncode
                assert rc!=0
                raise cli.Failure("network")
        return ("译例 "+text.replace("A small temperature study","一项温度研究")
                .replace("We tested 12 samples at 23.5 degrees Celsius","在23.5摄氏度下测试了12个样品")
                .replace("The measured value was","测量值为").replace("The results were reproducible","结果可复现"))
    with patch.object(sys,"argv",args),patch.object(cli,"ensure_cli"),patch.object(cli,"invoke",fake), \
         patch.object(engine_bridge,"read",return_value={"root":str(work),"codex":sys.executable}):
        settings=ConfigManager().initialize_config()
        config=create_babeldoc_config(settings,source)
        async for event in babeldoc_translate(config):
            if event["type"]=="error":
                raise RuntimeError(str(event["error"]))
            if event["type"]=="finish":
                output=event["translate_result"].dual_pdf_path
                break
    with pymupdf.open(output) as doc:
        assert len(doc)==1
        page=doc[0]
        box=page.rect
        def column(x0,x1):
            text=page.get_text(clip=pymupdf.Rect(x0,0,x1,box.height))
            return re.sub(r"\s+", "", unicodedata.normalize("NFKC",text))
        left=column(0,box.width/2)
        right=column(box.width/2,box.width)
    recovered=scenario=="recovered"
    assert "Wetested" in left and "译例" not in left
    assert right.count("译例")==2+int(recovered) and ("Wetested" in right)==(not recovered),right
    assert "23.5" in left and "23.5" in right and source.read_bytes()==before
    rows=[json.loads(s) for s in (work/"dispatch.jsonl").read_text().splitlines()]
    ends=[r for r in rows if r.get("event")=="end"]
    progress=Fragments()
    for row in rows: progress.update(row)
    assert len(ends)==progress.calls==(4 if recovered else 5)
    assert sum(r["final"] for r in ends)==3 and len(progress.retrying)==0 and progress.failed==int(not recovered)
    assert len(attempts)==(2 if recovered else 3) and len(set(attempts))==1
    print(f"PASS {scenario}: {progress.calls} calls, {progress.failed} final failures; verified both PDF columns.")


if __name__=="__main__":
    p=argparse.ArgumentParser()
    p.add_argument("--slot",required=True,type=Path)
    p.add_argument("--child-work",type=Path,help=argparse.SUPPRESS)
    p.add_argument("--scenario",choices=["recovered","exhausted"])
    args=p.parse_args()
    slot=args.slot.resolve()
    if args.child_work is None:
        # The native layout library may keep mapped PDF handles until process
        # exit. Give the parent ownership of the directory, as in production.
        for scenario in ([args.scenario] if args.scenario else ["recovered","exhausted"]):
            with tempfile.TemporaryDirectory(prefix="zpc-partial-") as temp:
                subprocess.run([sys.executable,"-I","-X","utf8",str(Path(__file__).resolve()),"--slot",str(slot),
                                "--child-work",temp,"--scenario",scenario],check=True,timeout=220)
    else:
        work=args.child_work
        data=slot/"engine-data"
        os.environ.update(ZPC_REAL_PROFILE=os.environ["USERPROFILE"],USERPROFILE=str(data),HOME=str(data),
                          ZPC_JOB_DIR=str(work),TIKTOKEN_CACHE_DIR=str(data/".cache/babeldoc/tiktoken"))
        asyncio.run(check(slot,work,args.scenario or "exhausted"))
