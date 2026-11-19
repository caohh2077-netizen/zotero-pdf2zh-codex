"""Stable shortcut entry; only select slots that finished installation."""
import ctypes
import json
import msvcrt
import os
from pathlib import Path
import subprocess
import sys
import tempfile

managed=Path(__file__).resolve().parent
state=managed/"state"
def pair(chosen, previous):
    selected = previous if chosen == "legacy" else chosen
    if not selected or selected == "legacy":
        return
    runtime = (managed/"releases"/selected/"runtime/Scripts/pythonw.exe").resolve()
    if not runtime.is_relative_to((managed/"releases").resolve()):
        raise ValueError("Invalid runtime")
    subprocess.run([str(runtime),"-I",str(managed/"pair_frontend.py"),str(managed.parent),chosen],check=True)

def load(name):
    return json.loads((state/name).read_text("utf-8"))

try:
    with (state/"install.lock").open("r+b") as lock:
        msvcrt.locking(lock.fileno(),msvcrt.LK_LOCK,1)
        active=load("active.json")
        if (state/"pending.json").exists():
            tasks=subprocess.run(["tasklist","/FI","IMAGENAME eq zotero.exe","/FO","CSV","/NH"],
                                 capture_output=True,creationflags=subprocess.CREATE_NO_WINDOW).stdout.lower()
            if b"zotero.exe" not in tasks:
                chosen=load("pending.json")["active"]
                pair(chosen,active["active"])
                with tempfile.NamedTemporaryFile(dir=state,delete=False) as f:
                    f.write(json.dumps({"active":chosen,"previous":active["active"]}).encode())
                    f.flush()
                    os.fsync(f.fileno())
                os.replace(f.name,state/"active.json")
                (state/"pending.json").unlink()
                active=load("active.json")
        name=active["active"]
        running = subprocess.run(["tasklist","/FI","IMAGENAME eq zotero.exe","/FO","CSV","/NH"],
                                 capture_output=True,creationflags=subprocess.CREATE_NO_WINDOW).stdout.lower()
        if b"zotero.exe" not in running:
            pair(name,active.get("previous"))
        if name=="legacy":
            base=managed.parent
            cmd=[base/"runtime/Scripts/pythonw.exe",base/"pdf2zh-launcher.pyw"]
            previous=active.get("previous")
            if previous and Path(previous).name==previous:
                old=(managed/"releases"/previous).resolve()
                if old.parent==(managed/"releases").resolve() and (old/"pkg/src/preferences.py").is_file():
                    python=old/"runtime/Scripts/pythonw.exe"
                    subprocess.run([str(python),"-I",str(old/"pkg/src/preferences.py"),"--restore"],check=True)
                    subprocess.run([str(python),"-I",str(old/"pkg/src/shortcut.py"),str(base),str(old),
                                    sys.executable,"--restore"],check=True)
        else:
            slot=(managed/"releases"/name).resolve()
            if slot.parent!=(managed/"releases").resolve() or not (slot/"ready.json").is_file():
                raise ValueError("Invalid active release")
            cmd=[slot/"runtime/Scripts/pythonw.exe",slot/"pkg/src/launcher/launch.py"]
        subprocess.Popen(list(map(str,cmd)),cwd=managed)
except Exception as exc:
    ctypes.windll.user32.MessageBoxW(None,str(exc),"Zotero PDF2zh",0x30)
