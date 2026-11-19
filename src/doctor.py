import argparse
from pathlib import Path
import sys
import shutil

sys.path.insert(0,str(Path(__file__).resolve().parent))
sys.path.insert(0,str(Path(__file__).resolve().parent/"adapter"))
sys.path.insert(0,str(Path(__file__).resolve().parent/"launcher"))
from common import PKG, read, save
from codex_translate import probe, environment, ERRORS, Failure
from launch import compatible, default_profile

if __name__=="__main__":
    p=argparse.ArgumentParser()
    p.add_argument("--profile",type=Path)
    args=p.parse_args()
    s=read(PKG.parent/"settings.json")
    try:
        compatible(args.profile or default_profile(),Path(s["zotero"]),preparing=True)
        binary=Path(s["codex"])
        if not binary.is_file() and shutil.which("codex.exe"):
            binary=Path(shutil.which("codex.exe"))
        probe(binary,environment())
        if str(binary)!=s["codex"]:
            s["codex"]=str(binary)
            save(PKG.parent/"settings.json",s)
        (Path(s["root"])/"managed/state/pause.json").unlink(missing_ok=True)
        print("OK | Zotero + PDF2zh + ChatGPT login |",s["source"],"->",s["target"],"|",s["id"])
    except Failure as exc:
        sys.exit(ERRORS[str(exc)])
    except (RuntimeError,OSError) as exc:
        sys.exit(str(exc))
