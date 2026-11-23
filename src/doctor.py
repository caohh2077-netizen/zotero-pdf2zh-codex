import argparse
from pathlib import Path
import sys

sys.path.insert(0,str(Path(__file__).resolve().parent))
sys.path.insert(0,str(Path(__file__).resolve().parent/"adapter"))
sys.path.insert(0,str(Path(__file__).resolve().parent/"launcher"))
from common import PKG, read
import codex_runtime
from codex_translate import probe, environment, ERRORS, Failure
from launch import compatible, default_profile

if __name__=="__main__":
    p=argparse.ArgumentParser()
    p.add_argument("--profile",type=Path)
    p.add_argument("--before-pair",action="store_true")
    args=p.parse_args()
    s=read(PKG.parent/"settings.json")
    try:
        compatible(args.profile or default_profile(),Path(s["zotero"]),preparing=True,
                   pairing_root=Path(s["root"]) if args.before_pair else None)
        binary=codex_runtime.ensure(Path(s["root"]))
        codex_runtime.record_executable(PKG.parent/"settings.json",binary)
        probe(binary,environment())
        (Path(s["root"])/"managed/state/pause.json").unlink(missing_ok=True)
        print("OK | Zotero + PDF2zh + ChatGPT login |",s["source"],"->",s["target"],"|",s["id"])
    except Failure as exc:
        if str(exc)=="login":
            sys.exit(f'请在 PowerShell 中运行 & "{binary}" login，以 ChatGPT 账户登录。')
        sys.exit(ERRORS[str(exc)])
    except (RuntimeError,OSError,ValueError) as exc:
        sys.exit(str(exc))
