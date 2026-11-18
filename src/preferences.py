"""Opt-in edit of PDF2zh preferences when Zotero has released the selected profile."""
import argparse
from contextlib import contextmanager
import json
from pathlib import Path
import re
import sys
import win32con
import win32file

sys.path.insert(0,str(Path(__file__).resolve().parent))
sys.path.insert(0,str(Path(__file__).resolve().parent/"launcher"))
from common import PKG, atomic, read, save, system_id
from launch import default_profile

PREFIX="extensions.zotero.pdf2zh."


def apply(profile, state, source, target, restore=False):
    prefs=profile/"prefs.js"
    if not prefs.is_file():
        raise ValueError("Open Zotero once before setting preferences")
    try:
        guard=win32file.CreateFile(str(profile/"parent.lock"),win32con.GENERIC_READ|win32con.GENERIC_WRITE,
                                   0,None,win32con.OPEN_ALWAYS,win32con.FILE_ATTRIBUTE_NORMAL,None)
    except OSError:
        raise RuntimeError("Close this Zotero profile before changing its preferences.") from None
    try:
        snapshot=state/("prefs-"+system_id(profile)+".json")
        values={"engine":"pdf2zh_next","engineSelect":"pdf2zh_next","next_service":"clitranslator",
                "next_serviceSelect":"clitranslator","new_serverip":"http://127.0.0.1:8890","sourceLang":source,
                "targetLang":target,"sourceLangSelect":source,"targetLangSelect":target,"qps":1,"poolSize":1,
                "noMono":True,"noDual":False,"mono":False,"dual":True,"disableGlossary":True}
        lines=prefs.read_bytes().decode("utf-8").splitlines(keepends=True)
        known={PREFIX+k for k in values}
        entries={}
        for i,line in enumerate(lines):
            m=re.fullmatch(r'user_pref\("([^"]+)",\s*(.*?)\);\s*',line)
            if m and m[1] in known:
                entries[m[1]]=(i,line)
        if restore and not snapshot.exists():
            return
        previous=read(snapshot) if snapshot.exists() else {"before":{k:entries.get(k,(None,None))[1] for k in known},"set":{}}
        for key,value in values.items():
            name=PREFIX+key
            idx,old=entries.get(name,(None,None))
            new=f'user_pref("{name}", {json.dumps(value)});\n'
            if restore:
                if old is None or old.strip()!=previous["set"].get(name,"").strip():
                    continue
                new=previous["before"].get(name) or ""
            else:
                previous["set"][name]=new
            if idx is None:
                lines.append(new)
            else:
                lines[idx]=new
        if not restore:
            save(snapshot,previous)
        atomic(prefs,"".join(lines).encode("utf-8"))
        if restore:
            snapshot.unlink()
    finally:
        guard.Close()


if __name__=="__main__":
    p=argparse.ArgumentParser()
    p.add_argument("--profile",type=Path)
    p.add_argument("--restore",action="store_true")
    a=p.parse_args()
    s=read(PKG.parent/"settings.json")
    apply(a.profile or default_profile(),Path(s["root"])/"managed/state",s["source"],s["target"],a.restore)
    print("PDF2zh preferences restored." if a.restore else "PDF2zh now uses clitranslator.")
