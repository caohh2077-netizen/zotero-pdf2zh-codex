"""Exercise the real layout engine and a deterministic, account-free CLI translator."""
import argparse
import hashlib
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import json
import pymupdf

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"fixtures"))
from sample import make


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--asset-profile",type=Path,help="Reuse a verified engine-data directory")
    p=parser.parse_args()
    with tempfile.TemporaryDirectory(prefix="zpc-pdf-") as tmp:
        folder=Path(tmp)
        data=folder/"engine-data"
        env=dict(os.environ,USERPROFILE=str(data),HOME=str(data),TIKTOKEN_CACHE_DIR=str(data/".cache/babeldoc/tiktoken"),
                 GRADIO_ANALYTICS_ENABLED="False",PYTHONUTF8="1")
        subprocess.run([sys.executable,"-I",str(ROOT/"src/assets.py"),str(folder),
                        *([str(p.asset_profile)] if p.asset_profile else [])],env=env,check=True)
        source=folder/"temperature.pdf"
        make(source)
        before=hashlib.sha256(source.read_bytes()).digest()
        fake=folder/"fake translate.py"
        fake.write_text("import sys\ns=sys.stdin.read()\nprint('样本 '+s.replace('We tested','测试了'))\n",encoding="utf-8")
        command=f'"{Path(sys.executable).as_posix()}" -I -X utf8 "{fake.as_posix()}"'
        conf=folder/"test.toml"
        conf.write_text("[clitranslator_detail]\nclitranslator_command="+json.dumps(command)+"\n",encoding="utf-8")
        binary=Path(sys.executable).parent/"pdf2zh_next.exe"
        subprocess.run([str(binary),str(source),"--clitranslator","--config-file",str(conf),"--output",str(folder),
                        "--lang-in","en","--lang-out","zh-CN","--qps","1","--no-mono","--no-auto-extract-glossary"],
                       env=env,check=True,timeout=360,stdout=subprocess.DEVNULL)
        output=next(folder.glob("*.dual.pdf"))
        with pymupdf.open(output) as doc:
            text="".join(page.get_text() for page in doc)
            assert len(doc)==1 and "样本" in text and "23.5" in text
        assert hashlib.sha256(source.read_bytes()).digest()==before
        print("PASS: real engine, bilingual single-page PDF, Chinese text, original unchanged")


if __name__=="__main__":
    main()
