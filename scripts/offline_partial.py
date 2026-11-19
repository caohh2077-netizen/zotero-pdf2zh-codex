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


async def check(slot, work):
    sys.path[:0]=[str(slot/"pkg/src"),str(ROOT/"fixtures")]
    import pymupdf
    from sample import make
    from adapter import codex_translate as cli
    import engine_bridge
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
    def fake(binary, env, source, target, text, deadline, model, effort, prompt):
        if "We tested" in text:
            with socket.socket() as sock:
                sock.bind(("127.0.0.1",0))
                port=sock.getsockname()[1]
                rc=subprocess.run([sys.executable,"-I","-c","import socket,sys; socket.create_connection(('127.0.0.1',int(sys.argv[1])),2)",str(port)],
                                  stderr=subprocess.DEVNULL).returncode
            if rc:
                raise cli.Failure("network")
        return "译例 "+text
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
        txt="".join(p.get_text() for p in doc)
    plain=re.sub(r"\s+", "", unicodedata.normalize("NFKC",txt))
    assert plain.count("译例")==2 and plain.count("23.5")==2 and source.read_bytes()==before, ("bilingual check",repr(txt))
    rows=[json.loads(s) for s in (work/"dispatch.jsonl").read_text().splitlines()]
    ends=[r for r in rows if r.get("event")=="end"]
    failed=[r for r in ends if r["result"]=="network"]
    assert len(failed)==1 and len(ends)==3,ends
    assert sum(r["event"]=="start" and r["id"]==failed[0]["id"] for r in rows)==1
    print("PASS: real bilingual PDF, 3 dispatches, 2 translated, one final disconnect, one start for the failed paragraph")


if __name__=="__main__":
    p=argparse.ArgumentParser()
    p.add_argument("--slot",required=True,type=Path)
    p.add_argument("--child-work",type=Path,help=argparse.SUPPRESS)
    args=p.parse_args()
    slot=args.slot.resolve()
    if args.child_work is None:
        # The native layout library may keep mapped PDF handles until process
        # exit. Give the parent ownership of the directory, as in production.
        with tempfile.TemporaryDirectory(prefix="zpc-partial-") as temp:
            subprocess.run([sys.executable,"-I","-X","utf8",str(Path(__file__).resolve()),"--slot",str(slot),
                            "--child-work",temp],check=True,timeout=220)
    else:
        work=args.child_work
        data=slot/"engine-data"
        os.environ.update(ZPC_REAL_PROFILE=os.environ["USERPROFILE"],USERPROFILE=str(data),HOME=str(data),
                          ZPC_JOB_DIR=str(work),TIKTOKEN_CACHE_DIR=str(data/".cache/babeldoc/tiktoken"))
        asyncio.run(check(slot,work))
