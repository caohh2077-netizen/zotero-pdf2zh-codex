"""Shared release metadata and crash-safe local state."""
import hashlib
import json
import os
from pathlib import Path
import tempfile
import tomllib
from urllib.request import Request, urlopen

PKG = Path(__file__).resolve().parents[1]
LOCK = tomllib.loads((PKG / "compat/upstream.lock.toml").read_text("utf-8"))


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def atomic(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as file:
        tmp = Path(file.name)
        try:
            file.write(data)
            file.flush()
            os.fsync(file.fileno())
        except BaseException:
            file.close()
            tmp.unlink(missing_ok=True)
            raise
    try:
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)


def save(path, obj):
    atomic(path, (json.dumps(obj, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))


def digest(path):
    with Path(path).open("rb") as source:
        return hashlib.file_digest(source, "sha256").hexdigest()


def verified_copy(source, target, sha):
    target.parent.mkdir(parents=True, exist_ok=True)
    temp = tempfile.NamedTemporaryFile(dir=target.parent, delete=False)
    staged = Path(temp.name)
    try:
        checksum = hashlib.sha256()
        with temp:
            while block := source.read(1024 * 1024):
                temp.write(block)
                checksum.update(block)
            if checksum.hexdigest() != sha:
                raise ValueError("SHA-256 mismatch: " + target.name)
            temp.flush()
            os.fsync(temp.fileno())
        try:
            os.replace(staged, target)
        except PermissionError:
            # A concurrent installer may already have published the verified
            # executable and Windows may now have it open.
            if not target.is_file() or digest(target) != sha:
                raise
    finally:
        staged.unlink(missing_ok=True)


def download(url, target, sha):
    if target.is_file() and digest(target) == sha:
        return
    request = Request(url, headers={"User-Agent": "Zotero-PDF2zh-Codex"})
    with urlopen(request, timeout=90) as response:
        verified_copy(response, target, sha)


def slot_path(root, name):
    if not name or Path(name).name != name or name in {".", "..", "legacy"} or ":" in name:
        raise ValueError("Invalid release directory")
    base = (Path(root)/"managed/releases").resolve()
    slot = (base/name).resolve()
    if slot.parent != base:
        raise ValueError("Release outside installation")
    return slot


def system_id(text):
    return hashlib.sha256(str(text).casefold().encode()).hexdigest()[:24]
