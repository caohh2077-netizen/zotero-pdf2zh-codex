import argparse
from pathlib import Path
import shutil
import subprocess
import sys

import win32com.client
from win32com.shell import shell, shellcon

sys.path.insert(0,str(Path(__file__).resolve().parent))
from common import read

if __name__=="__main__":
    p=argparse.ArgumentParser()
    p.add_argument("root",type=Path)
    p.add_argument("slot",type=Path)
    p.add_argument("pythonw")
    p.add_argument("--candidate",action="store_true")
    p.add_argument("--restore",action="store_true")
    p.add_argument("--profile")
    args=p.parse_args()
    desktop=Path(shell.SHGetFolderPath(0,shellcon.CSIDL_DESKTOPDIRECTORY,None,0))
    name="Zotero 全文翻译"+(" (test)" if args.candidate else "")+".lnk"
    path=desktop/name
    backup=args.root/"managed/state/legacy-shortcut.lnk"
    if args.restore:
        if backup.exists():
            shutil.copyfile(backup,path)
        sys.exit(0)
    if not args.candidate and path.exists() and not backup.exists():
        shutil.copyfile(path,backup)
    link=win32com.client.Dispatch("WScript.Shell").CreateShortcut(str(path))
    if args.candidate:
        link.TargetPath=str(args.slot/"runtime/Scripts/pythonw.exe")
        command=["-I",str(args.slot/"pkg/src/launcher/launch.py"),"--port","18890"]
        if args.profile:
            command+=["--profile",args.profile]
    else:
        link.TargetPath=args.pythonw
        command=["-I",str(args.root/"managed/start.pyw")]
    link.Arguments=subprocess.list2cmdline(command)
    link.WorkingDirectory=str(args.root)
    link.IconLocation=read(args.slot/"settings.json")["zotero"]+",0"
    link.Save()
    print(path)
