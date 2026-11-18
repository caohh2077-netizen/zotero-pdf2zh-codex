"""Fetch the exact Windows wheels named by the release lock, with offline reuse."""
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from pathlib import Path
import re
import tempfile
import time
from urllib.request import urlopen


def fetch(target, lock):
    target.mkdir(parents=True, exist_ok=True)
    lines = [l for l in lock.read_text("utf-8").splitlines() if l and not l.startswith("#")]
    def one(line):
        match=re.fullmatch(r"([a-z0-9.-]+)==(\S+) --hash=sha256:([a-f0-9]{64})",line)
        if not match:
            raise ValueError("Malformed wheel lock")
        name,version,sha=match.groups()
        prefix=name.replace("-","_")+"-"+version+"-"
        for path in target.glob(prefix+"*.whl"):
            with path.open("rb") as source:
                if hashlib.file_digest(source,"sha256").hexdigest()==sha:
                    return
        for attempt in range(3):
            tmp=None
            try:
                with urlopen(f"https://pypi.org/pypi/{name}/{version}/json",timeout=35) as r:
                    wheel=next(w for w in json.load(r)["urls"] if w["digests"]["sha256"]==sha)
                filename=wheel["filename"]
                if Path(filename).name!=filename or not filename.endswith(".whl") or not wheel["url"].startswith("https://files.pythonhosted.org/"):
                    raise ValueError("Unexpected wheel location")
                with urlopen(wheel["url"],timeout=90) as response, tempfile.NamedTemporaryFile(dir=target,delete=False) as f:
                    tmp=Path(f.name)
                    h=hashlib.sha256()
                    while block:=response.read(1024*1024):
                        h.update(block)
                        f.write(block)
                if h.hexdigest()!=sha:
                    raise ValueError("Wheel digest mismatch: "+name)
                tmp.replace(target/filename)
                return
            except OSError:
                if attempt==2:
                    raise
                time.sleep(attempt+1)
            finally:
                if tmp:
                    tmp.unlink(missing_ok=True)
    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(one,lines))
    return target


if __name__=="__main__":
    import sys
    print(fetch(Path(sys.argv[1]), Path(__file__).resolve().parents[1]/"locks/windows-x64-py312.txt"))
