"""Reuse verified assets only; keep mutable BabelDOC databases per slot."""
import hashlib
import os
from pathlib import Path
import shutil
import sys

from babeldoc.assets.assets import generate_all_assets_file_list, warmup


def matches(path, value):
    if not path.is_file():
        return False
    with path.open("rb") as f:
        return hashlib.file_digest(f, "sha3_256").hexdigest() == value


def prepare(slot, old_profiles):
    target = slot/"engine-data/.cache/babeldoc"
    files = generate_all_assets_file_list()
    missing = []
    for group, entries in files.items():
        for entry in entries:
            rel = Path(group)/entry["name"]
            dest = target/rel
            if matches(dest, entry["sha3_256"]):
                continue
            dest.parent.mkdir(parents=True, exist_ok=True)
            for profile in old_profiles:
                src = profile/".cache/babeldoc"/rel
                if matches(src, entry["sha3_256"]):
                    shutil.copyfile(src, dest)
                    break
            else:
                missing.append(rel)
    if missing:
        warmup()
    for group, entries in files.items():
        for item in entries:
            if not matches(target/group/item["name"], item["sha3_256"]):
                raise RuntimeError("Asset verification failed: "+item["name"])
    print("Verified engine assets:", sum(map(len, files.values())))


if __name__ == "__main__":
    prepare(Path(sys.argv[1]), [Path(p) for p in sys.argv[2:]])
