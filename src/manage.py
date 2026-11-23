"""Install and switch verified release slots. Runs with standard CPython before the venv exists."""
import argparse
import configparser
from contextlib import contextmanager
import hashlib
import json
import msvcrt
import os
from pathlib import Path
import re
import shutil
import struct
import subprocess
import sys
import tempfile
import time
from urllib.request import urlopen
import zipfile

sys.path.insert(0,str(Path(__file__).resolve().parent))
from common import LOCK, PKG, atomic, digest, download, read, save, slot_path
import codex_runtime
from wheels import fetch
import patch_runtime

ASSET_URL = f"https://github.com/{LOCK['upstream']}/releases/download/{LOCK['tag']}"
DEFAULT = Path(os.environ["LOCALAPPDATA"])/"Zotero-PDF2zh-Codex"
LOCATION = DEFAULT/"last-install.json"
PUBLIC = ("src","scripts","compat","locks","fixtures","tests","docs",".github","LICENSE","README.md",
          "Install.ps1","Doctor.ps1","Update.ps1","Rollback.ps1","Set-Language.ps1","Activate.ps1","Candidate.ps1","Use-Codex.ps1",".gitattributes",".gitignore")


def source_files(base):
    for name in PUBLIC:
        path=base/name
        if path.is_file():
            yield path
        elif path.is_dir():
            for f in sorted(path.rglob("*")):
                if f.is_file() and "__pycache__" not in f.parts and f.suffix not in (".pyc",".log"):
                    yield f


@contextmanager
def install_lock(state):
    state.mkdir(parents=True,exist_ok=True)
    with (state/"install.lock").open("a+b") as f:
        if f.tell()==0:
            f.write(b"0")
            f.flush()
        f.seek(0)
        try:
            msvcrt.locking(f.fileno(),msvcrt.LK_NBLCK,1)
        except OSError:
            raise RuntimeError("Another install or version switch is in progress.") from None
        try:
            yield
        finally:
            f.seek(0)
            msvcrt.locking(f.fileno(),msvcrt.LK_UNLCK,1)


def unpack(archive,destination):
    base=destination.resolve()
    with zipfile.ZipFile(archive) as z:
        for item in z.infolist():
            path=(base/item.filename).resolve()
            if not path.is_relative_to(base) or ":" in item.filename or (item.external_attr>>16)&0o170000 == 0o120000:
                raise ValueError("Invalid archive member")
        z.extractall(base)


def exe_path(value,name,extra=()):
    candidates=[value,shutil.which(name),*extra]
    for p in candidates:
        if p and Path(p).is_file() and Path(p).name.lower()==name.lower():
            return str(Path(p).resolve())
    raise ValueError(f"Specify an installed {name} path.")


def runtime(slot, script, *args, env=None):
    subprocess.run([str(slot/"runtime/Scripts/python.exe"),"-I","-X","utf8",str(script),*map(str,args)],env=env,check=True)


def configure(slot,source,target):
    if not all(re.fullmatch(r"[A-Za-z]{2,8}(?:-[A-Za-z0-9]{1,8}){0,3}",x) for x in (source,target)):
        raise ValueError("Invalid language code")
    path=slot/"server/config/config.toml"
    template=path.with_suffix(".toml.example")
    data=(path if path.exists() else template).read_text("utf-8-sig")
    command=(f'"{(slot/"runtime/Scripts/python.exe").as_posix()}" -I -X utf8 '
             f'"{(slot/"pkg/src/adapter/codex_translate.py").as_posix()}" --source {source} --target {target} '
             f'--prompt-version 1 --model {LOCK["model"]} --effort {LOCK["effort"]}')
    section=("[clitranslator_detail]\ntranslate_engine_type = \"CLITranslator\"\nclitranslator_command = "+
             json.dumps(command,ensure_ascii=False)+"\nclitranslator_timeout = 300\n\n")
    changed,count=re.subn(r"(?ms)^\[clitranslator_detail\][^\n]*\n.*?(?=^\[|\Z)",lambda _:section,data)
    if count!=1:
        raise ValueError("Unsupported upstream CLITranslator template")
    import tomllib
    if tomllib.loads(changed)["clitranslator_detail"]["clitranslator_command"]!=command:
        raise ValueError("Invalid configuration")
    if data!=changed:
        backup=path.with_name("clitranslator-before.toml")
        if not backup.exists():
            old=re.search(r"(?ms)^\[clitranslator_detail\][^\n]*\n.*?(?=^\[|\Z)",data)
            atomic(backup,old.group().encode())
        atomic(path,changed.encode("utf-8"))


def install(root,args):
    if sys.version_info[:3]!=tuple(map(int,LOCK["python"].split("."))) or struct.calcsize("P")!=8:
        raise RuntimeError("Use x64 CPython "+LOCK["python"]+" via -PythonPath.")
    managed=root/"managed"
    state=managed/"state"
    with install_lock(state):
        files=list(source_files(PKG))
        fingerprint=hashlib.sha256()
        for f in files:
            fingerprint.update(f.relative_to(PKG).as_posix().encode()+bytes.fromhex(digest(f)))
        name=LOCK["release"]+"-"+fingerprint.hexdigest()[:10]
        slot=slot_path(root,name)
        active=read(state/"active.json").get("active") if (state/"active.json").exists() else None
        prior=read(slot_path(root,active)/"settings.json") if active and active!="legacy" else {}
        zotero=exe_path(args.zotero or prior.get("zotero"),"zotero.exe",(root.parent/"Zotero/zotero.exe",Path(os.environ["PROGRAMFILES"])/"Zotero/zotero.exe"))
        binary=codex_runtime.ensure(root, source=args.codex, asset_dir=args.asset_dir)
        if not (slot/"ready.json").exists():
            slot.mkdir(parents=True,exist_ok=True)
            for f in files:
                dest=slot/"pkg"/f.relative_to(PKG)
                dest.parent.mkdir(parents=True,exist_ok=True)
                shutil.copyfile(f,dest)
            cache=managed/"downloads"
            for fname,sha in LOCK["assets"].items():
                target=cache/fname
                local=next((p for p in (root/fname,root/f"server-{LOCK['tag']}.zip",Path(args.asset_dir or cache)/fname)
                            if p.is_file() and digest(p)==sha),None)
                cache.mkdir(parents=True,exist_ok=True)
                if local and local.resolve()!=target.resolve():
                    shutil.copyfile(local,target)
                download(ASSET_URL+"/"+fname,target,sha)
            unpack(cache/"server.zip",slot)
            python=slot/"runtime/Scripts/python.exe"
            if not python.exists():
                subprocess.run([sys.executable,"-m","venv",str(slot/"runtime")],check=True)
            wheelhouse=fetch(Path(args.wheelhouse or cache/"wheels"),PKG/"locks/windows-x64-py312.txt")
            subprocess.run([str(python),"-m","pip","--disable-pip-version-check","install","--quiet","--no-index","--no-compile",
                            "--only-binary=:all:","--no-deps","--require-hashes","--find-links",str(wheelhouse),
                            "-r",str(PKG/"locks/windows-x64-py312.txt")],check=True)
            patch_runtime.install(slot)
            if digest(PKG/"compat/pdf2zh-codex.xpi") != LOCK["xpi_sha256"]:
                raise ValueError("Paired XPI digest mismatch")
            ocr = LOCK["ocr"]
            trained = cache/"eng.traineddata"
            download("https://raw.githubusercontent.com/tesseract-ocr/tessdata_fast/"+ocr["commit"]+"/eng.traineddata",
                     trained,ocr["eng_sha256"])
            (slot/"tessdata").mkdir(exist_ok=True)
            shutil.copyfile(trained,slot/"tessdata/eng.traineddata")
            # The official wheel metadata contains a verified asset inventory.
            current=read(state/"active.json") if (state/"active.json").exists() else {}
            previous=current.get("active")
            profiles=[root/"engine-data"]
            if previous and previous!="legacy":
                profiles.insert(0,slot_path(root,previous)/"engine-data")
            previous_slot=slot_path(root,previous) if previous and previous!="legacy" else root
            runtime(slot,slot/"pkg/src/migrate.py",previous_slot/"server/config/config.toml",slot/"server/config/config.toml")
            data=slot/"engine-data"
            env=dict(os.environ,USERPROFILE=str(data),HOME=str(data),TIKTOKEN_CACHE_DIR=str(data/".cache/babeldoc/tiktoken"))
            runtime(slot,slot/"pkg/src/assets.py",slot,*profiles,env=env)
            settings={"root":str(root),"zotero":zotero,"codex":str(binary),"source":"en","target":"zh-CN","id":name}
            if previous and previous!="legacy":
                prior=read(slot_path(root,previous)/"settings.json")
                settings.update(source=prior["source"],target=prior["target"])
            save(slot/"settings.json",settings)
            configure(slot,settings["source"],settings["target"])
            save(slot/"ready.json",{"id":name,"release":LOCK["release"],"source":fingerprint.hexdigest()})
        else:
            codex_runtime.record_executable(slot/"settings.json", binary)
        save(state/"candidate.json",{"id":name})
        if not (state/"active.json").exists():
            save(state/"active.json",{"active":"legacy" if (root/"pdf2zh-launcher.pyw").exists() else None,"previous":None})
        atomic(managed/"pair_frontend.py",(PKG/"src/pair_frontend.py").read_bytes())
        atomic(managed/"start.pyw",(PKG/"src/start.pyw").read_bytes())
        print("Translation CLI", binary)
        print("Candidate ready:",slot)
    return slot


def shortcut(root,slot,test=False,profile=None,restore=False):
    args=[root,slot,Path(sys.executable).with_name("pythonw.exe")]
    if test:
        args.append("--candidate")
    if restore:
        args.append("--restore")
    if profile:
        args+=["--profile",str(profile)]
    runtime(slot,PKG/"src/shortcut.py",*args)


def active_switch(root,dest,slot=None):
    state=root/"managed/state"
    statefile=state/"active.json"
    current=read(statefile)
    if dest!="legacy":
        target=slot_path(root,dest)
        if read(target/"ready.json")["id"]!=dest:
            raise ValueError("Release is not ready")
    if current.get("active")==dest:
        (state/"pending.json").unlink(missing_ok=True)
        return
    if slot is not None and current.get("active") not in (None, "legacy"):
        codex_runtime.migrate_previous(slot_path(root, current["active"]), codex_runtime.executable(root))
    running=subprocess.run(["tasklist","/FI","IMAGENAME eq zotero.exe","/FO","CSV","/NH"],capture_output=True,
                           creationflags=subprocess.CREATE_NO_WINDOW).stdout.lower()
    if b"zotero.exe" not in running:
        chosen = current.get("active") if dest == "legacy" else dest
        if chosen and chosen != "legacy":
            runtime(slot_path(root,chosen),PKG/"src/pair_frontend.py",root,dest)
    if dest!="legacy":
        shortcut(root,slot or target)
    elif b"zotero.exe" not in running and current.get("active") and current["active"]!="legacy":
        previous_slot=slot_path(root,current["active"])
        runtime(previous_slot,previous_slot/"pkg/src/preferences.py","--restore")
        shortcut(root,previous_slot,restore=True)
    if b"zotero.exe" in running:
        save(state/"pending.json",{"active":dest})
        print("Version switch queued for next startup after Zotero exits.")
    else:
        save(statefile,{"active":dest,"previous":current.get("active")})
        (state/"pending.json").unlink(missing_ok=True)
    save(LOCATION,{"root":str(root)})


def main():
    p=argparse.ArgumentParser()
    p.add_argument("action",choices=["install","prepare","activate","doctor","rollback","language","candidate","update","use-codex","restore-prefs"])
    for arg in ("root","zotero","codex","source","target","version","wheelhouse","asset-dir","profile"):
        p.add_argument("--"+arg)
    args=p.parse_args()
    root=Path(args.root or (read(LOCATION)["root"] if LOCATION.exists() else DEFAULT)).resolve()
    state=root/"managed/state"
    if args.action=="update":
        version=args.version or ""
        if not re.fullmatch(r"\d+\.\d+\.\d+(?:-[a-z0-9.-]+)?",version):
            raise ValueError("Specify a release version")
        # Fetch GitHub's release metadata and the exact immutable asset digest.
        with urlopen(f"https://api.github.com/repos/{LOCK['repository']}/releases/tags/v{version}",timeout=30) as r:
            rel=json.load(r)
        name=f"zotero-pdf2zh-codex-{version}-windows-x64.zip"
        asset=next(a for a in rel["assets"] if a["name"]==name)
        sha=asset["digest"].removeprefix("sha256:")
        if not re.fullmatch(r"[a-f0-9]{64}",sha):
            raise ValueError("Missing release checksum")
        zipfile_path=root/"managed/downloads"/name
        download(asset["browser_download_url"],zipfile_path,sha)
        with tempfile.TemporaryDirectory(prefix="zpc-update-") as work:
            unpack(zipfile_path,Path(work))
            subprocess.run([sys.executable,"-I",str(Path(work)/"src/manage.py"),"install","--root",str(root)],check=True)
        return
    if args.action in ("install","prepare"):
        slot=install(root,args)
        if args.action=="prepare":
            return
        runtime(slot,slot/"pkg/src/doctor.py","--before-pair",*(["--profile",args.profile] if args.profile else []))
        with install_lock(state):
            active_switch(root,slot.name,slot)
        return
    with install_lock(state):
        active=read(state/"active.json")
        candidate=read(state/"candidate.json")["id"]
        chosen=candidate if args.action in ("activate","candidate") or active.get("active") in (None,"legacy") else active["active"]
        slot=slot_path(root,chosen)
        if args.action=="doctor":
            runtime(slot,slot/"pkg/src/doctor.py",*(["--profile",args.profile] if args.profile else []))
        elif args.action=="candidate":
            shortcut(root,slot,True,args.profile)
        elif args.action=="activate":
            runtime(slot,slot/"pkg/src/doctor.py","--before-pair")
            active_switch(root,candidate,slot)
        elif args.action in ("use-codex","restore-prefs"):
            options=(["--restore"] if args.action=="restore-prefs" else [])+(["--profile",args.profile] if args.profile else [])
            runtime(slot,slot/"pkg/src/preferences.py",*options)
        elif args.action=="rollback":
            if (state/"pending.json").exists():
                (state/"pending.json").unlink()
                print("Cancelled pending version switch.")
                return
            if not active.get("previous"):
                raise ValueError("No previous release")
            active_switch(root,active["previous"])
        elif args.action=="language":
            settings=read(slot/"settings.json")
            configure(slot,args.source or "",args.target or "")
            settings.update(source=args.source,target=args.target)
            save(slot/"settings.json",settings)
            print("Set Zotero languages to",args.source,args.target)


if __name__=="__main__":
    # Windows pipes use the system code page, even when a valid path contains other characters.
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    try:
        main()
    except Exception as exc:
        sys.exit(str(exc))
