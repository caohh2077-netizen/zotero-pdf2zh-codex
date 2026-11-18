"""Rebuild the Windows wheel lock from a known-good Windows x64 engine venv."""
import argparse
import concurrent.futures
import hashlib
import importlib.metadata as metadata
import json
from pathlib import Path
import urllib.request

from packaging.tags import sys_tags
from packaging.utils import canonicalize_name, parse_wheel_filename

ROOT = Path(__file__).resolve().parents[1]
RANK = {tag: n for n, tag in enumerate(sys_tags())}


def release_wheel(package):
    name, version = package
    url = f"https://pypi.org/pypi/{name}/{version}/json"
    with urllib.request.urlopen(url, timeout=40) as response:
        files = json.load(response)["urls"]
    options = []
    for file in files:
        if file["filename"].endswith(".whl"):
            tags = parse_wheel_filename(file["filename"])[3]
            ranks = [RANK[tag] for tag in tags if tag in RANK]
            if ranks:
                options.append((min(ranks), file["filename"], file))
    if not options:
        raise ValueError(f"No compatible wheel for {name}=={version}")
    wheel = min(options)[2]
    return (f"{name}=={version} --hash=sha256:{wheel['digests']['sha256']}", wheel["size"])


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT/"locks/windows-x64-py312.txt")
    args = parser.parse_args()
    packages = sorted({(canonicalize_name(d.metadata["Name"]), d.version) for d in metadata.distributions()
                       if d.metadata["Name"] and d.metadata["Name"].lower() != "pip"})
    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as pool:
        results = list(pool.map(release_wheel, packages))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text("# CPython 3.12.10 Windows x64 / PyPI wheels\n" +
                           "\n".join(line for line, size in results) + "\n", encoding="utf-8")
    print(f"{len(results)} wheels, {sum(size for _, size in results)/1e6:.1f} MB")
