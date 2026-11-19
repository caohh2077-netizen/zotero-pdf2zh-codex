"""Monitor the Zotero main window and own precisely one backend process tree."""
import argparse
import configparser
import ctypes
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import time
from urllib.request import ProxyHandler, build_opener

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from common import LOCK, PKG, read, save, system_id
from winjob import child_tree, mutex
import psutil
import win32api
import win32con
import win32event as event
import win32gui
import win32process
import win32ts

OPENER = build_opener(ProxyHandler({}))
SLOT = PKG.parent
EXTENSION = "pdf2zh@guaguastandup.com"


def default_profile():
    base = Path(os.environ["APPDATA"])/"Zotero/Zotero"
    ini = configparser.ConfigParser(interpolation=None)
    ini.read(base/"profiles.ini", encoding="utf-8-sig")
    profiles = [ini[k] for k in ini if k.startswith("Profile")]
    install = next((ini[k].get("Default") for k in ini if k.startswith("Install") and ini[k].get("Default")), None)
    if install:
        return (base/install).resolve()
    selected = next((p for p in profiles if p.get("Default") == "1"), profiles[0] if len(profiles)==1 else None)
    if selected is None:
        raise RuntimeError("Select a Zotero profile with -Profile.")
    return (base/selected["Path"]).resolve() if selected.get("IsRelative") == "1" else Path(selected["Path"])


def compatible(profile, zotero, preparing=False):
    ini = configparser.ConfigParser(interpolation=None, strict=False)
    ini.read(zotero.parent/"app/application.ini", encoding="utf-8-sig")
    if not ini.has_option("App", "Version"):
        ini.read(zotero.parent/"application.ini", encoding="utf-8-sig")
    version = ini.get("App", "Version", fallback="")
    if version not in LOCK["zotero_versions"]:
        raise RuntimeError(f"Unsupported Zotero version {version}.")
    try:
        ext = next(a for a in read(profile/"extensions.json")["addons"] if a["id"]==EXTENSION)
    except (OSError, KeyError, StopIteration):
        raise RuntimeError("Install and enable the supplied PDF2zh XPI in this Zotero profile.") from None
    if not ext.get("active") or ext["version"] not in ({LOCK["xpi_version"],LOCK["server_version"]} if preparing else {LOCK["xpi_version"]}):
        raise RuntimeError("The enabled PDF2zh XPI must match "+LOCK["xpi_version"])


def engine_env(slot):
    env = os.environ.copy()
    for key in ("PYTHONHOME","PYTHONPATH"):
        env.pop(key, None)
    real = env["USERPROFILE"]
    profile = slot/"engine-data"
    env.update(ZPC_REAL_PROFILE=real, ZPC_REAL_CODEX_HOME=env.get("CODEX_HOME", str(Path(real)/".codex")),
               USERPROFILE=str(profile), HOME=str(profile), HF_HOME=str(profile/"huggingface"),
               TIKTOKEN_CACHE_DIR=str(profile/".cache/babeldoc/tiktoken"),
               VIRTUAL_ENV=str(slot/"runtime"), PATH=str(slot/"runtime/Scripts")+os.pathsep+env["PATH"],
               PYTHONUTF8="1", PYTHONIOENCODING="utf-8", PYTHONNOUSERSITE="1",
               GRADIO_ANALYTICS_ENABLED="False")
    return env


def window_owner(exe, profile=None):
    pairs = []
    def visit(window, _):
        if win32gui.IsWindowVisible(window) and win32gui.GetClassName(window) == "MozillaWindowClass" and win32gui.GetWindowText(window):
            pairs.append((win32process.GetWindowThreadProcessId(window)[1], window))
        return True
    win32gui.EnumWindows(visit,None)
    for pid, window in pairs:
        try:
            p = psutil.Process(pid)
            if win32ts.ProcessIdToSessionId(pid) != win32ts.ProcessIdToSessionId(os.getpid()) or Path(p.exe()) != exe:
                continue
            args = p.cmdline()
            explicit = next((Path(args[i+1]).resolve() for i, v in enumerate(args[:-1]) if v.lower() in ("-profile","--profile")),None)
            if (profile and explicit != profile) or (not profile and explicit):
                continue
            return pid, window
        except (psutil.Error, OSError):
            continue
    return None


def open_window(exe, profile):
    owner = window_owner(exe,profile)
    if not owner:
        args = [str(exe)] + (["-no-remote","-profile",str(profile)] if profile else [])
        subprocess.Popen(args, cwd=exe.parent)
        deadline=time.monotonic()+80
        while time.monotonic()<deadline and not (owner:=window_owner(exe,profile)):
            time.sleep(.25)
    if not owner:
        raise RuntimeError("Zotero main window did not appear.")
    if win32gui.IsIconic(owner[1]):
        win32gui.ShowWindow(owner[1],win32con.SW_RESTORE)
    try:
        win32gui.SetForegroundWindow(owner[1])
    except win32gui.error:
        pass
    return owner[0]


def run(slot, settings, port, profile, owner_pid=None):
    state=Path(settings["root"])/"managed/state"
    key="backend."+system_id(str(state)+str(port))
    with mutex(key) as owned:
        if not owned:
            existing=window_owner(Path(settings["zotero"]),profile)
            if existing:
                if win32gui.IsIconic(existing[1]):
                    win32gui.ShowWindow(existing[1],win32con.SW_RESTORE)
                try:
                    win32gui.SetForegroundWindow(existing[1])
                except win32gui.error:
                    pass
            return
        with socket.socket() as probe:
            if probe.connect_ex(("127.0.0.1",port))==0:
                raise RuntimeError(f"Port {port} is occupied by another program.")
        exe=Path(settings["zotero"])
        if not owner_pid and not window_owner(exe,profile):
            from pair_frontend import pair
            pair(Path(settings["root"]),slot.name,profile or default_profile())
        pid=owner_pid or open_window(exe,profile)
        if not owner_pid:
            selected=profile or default_profile()
            for attempt in range(30):
                try:
                    compatible(selected,exe)
                    break
                except RuntimeError:
                    if attempt==29:
                        raise
                    time.sleep(.2)
        owner=win32api.OpenProcess(win32con.SYNCHRONIZE,False,pid)
        keyfile=state/f"session-{port}.json"
        try:
            with open(os.devnull,"rb") as inp, open(os.devnull,"wb") as out:
                server=slot/"server"
                cmd=[slot/"runtime/Scripts/python.exe","-u",server/"server.py","--host","127.0.0.1","--port",str(port),
                     "--enable_venv=False","--check_update=False","--update_source=github"]
                with child_tree(cmd,engine_env(slot),server,inp,out,out) as (child,cpid):
                    deadline=time.monotonic()+80
                    while time.monotonic()<deadline:
                        result=event.WaitForMultipleObjects([owner,child],False,150)
                        if result==0:
                            return
                        if result==1:
                            raise RuntimeError("Backend stopped before becoming ready.")
                        try:
                            with OPENER.open(f"http://127.0.0.1:{port}/health",timeout=.8) as r:
                                data=json.load(r)
                        except (OSError,ValueError):
                            continue
                        if (data.get("status")!="ok" or data.get("version")!=LOCK["server_version"]
                                or data.get("codexProtocol") != LOCK["protocol"]
                                or Path(data.get("outputDir","")).resolve()!=(server/"translated").resolve()):
                            raise RuntimeError("Unexpected server health response.")
                        break
                    else:
                        raise RuntimeError("Backend health check timed out.")
                    save(keyfile,{"backend_pid":cpid,"owner_pid":pid,"slot":slot.name,"port":port})
                    if event.WaitForMultipleObjects([owner,child],False,event.INFINITE)==1:
                        raise RuntimeError("Backend stopped unexpectedly.")
        finally:
            owner.Close()
            keyfile.unlink(missing_ok=True)


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--port",type=int,default=8890)
    parser.add_argument("--profile",type=Path)
    parser.add_argument("--console",action="store_true")
    args=parser.parse_args()
    try:
        settings=read(SLOT/"settings.json")
        run(SLOT,settings,args.port,args.profile.resolve() if args.profile else None)
    except Exception as exc:
        message=str(exc)
        if args.console:
            print(message,file=sys.stderr)
        else:
            ctypes.windll.user32.MessageBoxW(None,message,"Zotero 全文翻译",0x30)
        return 1
    return 0


if __name__=="__main__":
    sys.exit(main())
