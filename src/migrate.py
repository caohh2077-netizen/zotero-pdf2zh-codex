"""Merge known TOML settings locally and preserve new upstream defaults."""
from pathlib import Path
import sys
import tomlkit

sys.path.insert(0,str(Path(__file__).resolve().parent))
from common import atomic


def merge(template, old):
    for key in template:
        if key not in old:
            continue
        if isinstance(template[key],dict) and isinstance(old[key],dict):
            merge(template[key],old[key])
        else:
            a,b=template[key],old[key]
            current=a.unwrap() if hasattr(a,"unwrap") else a
            previous=b.unwrap() if hasattr(b,"unwrap") else b
            if type(current) is type(previous):
                template[key]=b


if __name__=="__main__":
    source, dest=map(Path,sys.argv[1:3])
    if source.is_file() and not dest.exists():
        new=tomlkit.parse(dest.with_suffix(".toml.example").read_text("utf-8-sig"))
        old=tomlkit.parse(source.read_text("utf-8-sig"))
        merge(new,old)
        atomic(dest,tomlkit.dumps(new).encode("utf-8"))
