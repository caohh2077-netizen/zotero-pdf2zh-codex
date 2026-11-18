"""Isolate engine cache and configs from the developer's real user profile."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile

root=Path(__file__).resolve().parents[1]
with tempfile.TemporaryDirectory(prefix="zpc-tests-") as folder:
    env=dict(os.environ,HOME=folder,USERPROFILE=folder,PYTHONUTF8="1",PYTHONDONTWRITEBYTECODE="1")
    code=subprocess.run([sys.executable,"-X","utf8","-m","unittest","discover","-v","-s",str(root/"tests"),
                         "-p",sys.argv[1]],cwd=root,env=env).returncode
sys.exit(code)
