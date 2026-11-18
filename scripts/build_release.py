"""Build a portable public bundle from a clean, tagged checkout."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
import zipfile

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"src"))
from manage import source_files
from common import LOCK,digest


def build(out):
    out.mkdir(parents=True,exist_ok=True)
    version=LOCK["release"]
    name=f"zotero-pdf2zh-codex-{version}-windows-x64.zip"
    files=sorted(source_files(ROOT))
    def git(*args):
        return subprocess.check_output(["git","-C",str(ROOT),*args],text=True).strip()
    if git("status","--porcelain","--untracked-files=normal"):
        raise ValueError("Commit intended release files before building.")
    commit=git("rev-parse","HEAD")
    with zipfile.ZipFile(out/name,"w",zipfile.ZIP_DEFLATED) as z:
        for p in files:
            rel=p.relative_to(ROOT).as_posix()
            if rel.endswith((".sqlite",".log",".pdf",".js.map")) or p.name.lower() in ("auth.json","config.toml","prefs.js"):
                raise ValueError("Unexpected public file: "+rel)
            contents=p.read_bytes()
            if re.search(rb"(?:sk-[A-Za-z0-9_-]{24,}|gh[pousr]_[A-Za-z0-9]{25,}|-----BEGIN [A-Z ]*PRIVATE KEY-----)",contents):
                raise ValueError("Possible credential: "+rel)
            # Windows checkouts may have CRLF; canonicalize text from Git.
            contents=subprocess.check_output(["git","-C",str(ROOT),"show",f"{commit}:{rel}"])
            info=zipfile.ZipInfo(rel,(2026,1,1,0,0,0))
            z.writestr(info,contents,compress_type=zipfile.ZIP_DEFLATED)
    (out/"SHA256SUMS").write_text(digest(out/name)+"  "+name+"\n",encoding="ascii")
    (out/"build-source.json").write_text(json.dumps({"repository":LOCK["repository"],"commit":commit,"upstream":LOCK["commit"],
                                                     "version":version},indent=2)+"\n",encoding="utf-8")
    print(out/name)


if __name__=="__main__":
    parser=argparse.ArgumentParser()
    parser.add_argument("--out",type=Path,default=ROOT/"dist")
    build(parser.parse_args().out)
