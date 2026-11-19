"""Pair a closed Zotero profile with the chosen backend, including v0.1 rollback."""
import argparse
import configparser
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import tempfile
import tomllib

import win32con
import win32file

EXTENSION = "pdf2zh@guaguastandup.com"


def atomic(path, data):
    with tempfile.NamedTemporaryFile(dir=path.parent,delete=False) as temp:
        staged = Path(temp.name)
        temp.write(data)
    try:
        os.replace(staged,path)
    finally:
        staged.unlink(missing_ok=True)


def default_profile():
    base = Path(os.environ["APPDATA"])/"Zotero/Zotero"
    ini = configparser.ConfigParser(interpolation=None)
    ini.read(base/"profiles.ini", encoding="utf-8-sig")
    for key in ini:
        if key.startswith("Install") and ini[key].get("Default"):
            return (base/ini[key]["Default"]).resolve()
    profiles = [ini[k] for k in ini if k.startswith("Profile")]
    profile = next((p for p in profiles if p.get("Default") == "1"), profiles[0] if len(profiles)==1 else None)
    if profile is None:
        raise RuntimeError("请选择 Zotero 配置目录。")
    return (base/profile["Path"]).resolve()


def pair(root, chosen, profile=None):
    managed = root/"managed"
    manifest = None
    if chosen != "legacy":
        slot = (managed/"releases"/chosen).resolve()
        if slot.parent != (managed/"releases").resolve():
            raise ValueError("Invalid slot")
        manifest = tomllib.loads((slot/"pkg/compat/upstream.lock.toml").read_text("utf-8"))
    v2 = bool(manifest and manifest.get("protocol") == 2)
    source = slot/"pkg/compat/pdf2zh-codex.xpi" if v2 else managed/"downloads/zotero-pdf-2-zh.xpi"
    new = source.read_bytes()
    sourcehash = hashlib.sha256(new).hexdigest()
    expected = manifest["xpi_sha256"] if v2 else "c5f72846547ed4898a29d0ee5b2cebffef40ee6548a8e1a4bfec9130fab82f16"
    if expected != sourcehash:
        raise RuntimeError("配套 XPI 校验失败。")
    profile = profile or default_profile()
    path = profile/"extensions"/(EXTENSION+".xpi")
    marker = managed/"state"/("pair-"+hashlib.sha256(str(profile).casefold().encode()).hexdigest()[:20]+".json")
    previous = json.loads(marker.read_bytes()) if marker.is_file() else {}
    current = hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None
    database = profile/"extensions.json"
    active = next((extension for extension in json.loads(database.read_bytes()).get("addons", [])
                   if extension["id"] == EXTENSION), {}) if database.is_file() else {}
    version = manifest["xpi_version"] if v2 else "4.1.8"
    if current == sourcehash and previous.get("sha") == sourcehash and active.get("version") == version:
        return
    if current not in (None, sourcehash, previous.get("sha"), "c5f72846547ed4898a29d0ee5b2cebffef40ee6548a8e1a4bfec9130fab82f16"):
        raise RuntimeError("当前配置的 XPI 来自另一版本，须先核对版本。")
    guard = win32file.CreateFile(str(profile/"parent.lock"),win32con.GENERIC_READ|win32con.GENERIC_WRITE,
                                 0,None,win32con.OPEN_ALWAYS,win32con.FILE_ATTRIBUTE_NORMAL,None)
    try:
        path.parent.mkdir(exist_ok=True)
        prefs = profile/"prefs.js"
        raw = prefs.read_bytes().decode("utf-8")
        # Zotero skips scans on equal app build IDs. Its add-on manager consumes
        # and restores this single cache marker on the following startup.
        raw = re.sub(r'(?m)^user_pref\("extensions\.lastAppBuildId", "[^"]*"\);\r?\n?', "", raw)
        changes = previous.get("prefs", {})
        # Upgrade the old wrapper's two defaults only for users of that service.
        if v2 and re.search(r'user_pref\("extensions\.zotero\.pdf2zh\.next_service", "clitranslator"\)',raw):
            for key in ("qps","poolSize"):
                pattern = rf'(?m)^user_pref\("extensions\.zotero\.pdf2zh\.{key}", 1\);'
                if re.search(pattern,raw):
                    changes[key] = 1
                    raw = re.sub(pattern,lambda m:m[0][:-3]+"10);",raw)
        if not v2:
            for key,old in changes.items():
                pattern = rf'(?m)^user_pref\("extensions\.zotero\.pdf2zh\.{key}", 10\);'
                raw = re.sub(pattern,lambda m:m[0][:-4]+str(old)+");",raw)
            changes = {}
        if raw.encode("utf-8") != prefs.read_bytes():
            atomic(prefs,raw.encode("utf-8"))
        if current != sourcehash:
            atomic(path,new)
        atomic(marker,json.dumps({"sha":sourcehash,"prefs":changes}).encode())
    finally:
        guard.Close()


if __name__ == "__main__":
    parser=argparse.ArgumentParser()
    parser.add_argument("root",type=Path)
    parser.add_argument("slot")
    parser.add_argument("--profile",type=Path)
    args=parser.parse_args()
    pair(args.root,args.slot,args.profile)
