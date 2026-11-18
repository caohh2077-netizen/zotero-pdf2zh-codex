"""CI acceptance of the installer under a clean account, without a paid model call."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT=Path(__file__).resolve().parents[1]
with tempfile.TemporaryDirectory(prefix="Zotero 安装 ") as folder:
    work=Path(folder)
    # Prepare only resolves frontend paths; these named inert fixtures must never be executed.
    for name in ("zotero.exe","codex.exe"):
        (work/name).write_bytes(b"test fixture, not executable")
    root=work/"clean installation"
    cmd=[sys.executable,"-I",str(ROOT/"src/manage.py"),"prepare","--root",str(root),
         "--wheelhouse",str(ROOT/".work/verified-wheels"),"--zotero",str(work/"zotero.exe"),"--codex",str(work/"codex.exe")]
    subprocess.run(cmd,check=True)
    state=root/"managed/state"
    slot=root/"managed/releases"/json.loads((state/"candidate.json").read_text())["id"]
    marker=(slot/"ready.json").stat().st_mtime_ns
    subprocess.run(cmd,check=True)
    assert (slot/"ready.json").stat().st_mtime_ns==marker
    assert json.loads((state/"active.json").read_text())["active"] is None
    subprocess.run([str(slot/"runtime/Scripts/python.exe"),"-X","utf8",str(ROOT/"scripts/offline_pdf.py"),
                    "--asset-profile",str(slot/"engine-data")],check=True)
    print("Clean-account prepare, repeated install and one-page offline PDF passed")
