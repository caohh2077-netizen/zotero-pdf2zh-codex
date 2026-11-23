"""CI acceptance of the installer under a clean account, without a paid model call."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/"src"))
from codex_runtime import executable
from common import LOCK, digest, read, save

with tempfile.TemporaryDirectory(prefix="Zotero 安装 ") as folder:
    work=Path(folder)
    # Prepare only resolves the Zotero path. The translation CLI is the real distribution.
    (work/"zotero.exe").write_bytes(b"inert frontend fixture")
    root=work/"clean installation"
    cmd=[sys.executable,"-I",str(ROOT/"src/manage.py"),"prepare","--root",str(root),
         "--wheelhouse",str(ROOT/".work/verified-wheels"),"--zotero",str(work/"zotero.exe")]
    subprocess.run(cmd,check=True)
    state=root/"managed/state"
    slot=root/"managed/releases"/json.loads((state/"candidate.json").read_text())["id"]
    marker=(slot/"ready.json").stat().st_mtime_ns
    binary = executable(root)
    settings = read(slot/"settings.json")
    assert settings["codex"] == str(binary) and digest(binary) == LOCK["codex_cli"]["sha256"]
    version = subprocess.check_output([binary, "--version"], text=True, creationflags=subprocess.CREATE_NO_WINDOW)
    assert version.strip() == "codex-cli " + LOCK["codex_cli"]["version"]
    binary_time = binary.stat().st_mtime_ns
    save(slot/"settings.json", dict(settings, codex=str(work/"WindowsApps/removed/codex.exe")))
    subprocess.run(cmd,check=True)
    assert read(slot/"settings.json") == settings
    assert binary.stat().st_mtime_ns == binary_time
    assert (slot/"ready.json").stat().st_mtime_ns==marker
    assert json.loads((state/"active.json").read_text())["active"] is None
    subprocess.run([str(slot/"runtime/Scripts/python.exe"),"-X","utf8",str(ROOT/"scripts/offline_pdf.py"),
                    "--asset-profile",str(slot/"engine-data")],check=True)
    subprocess.run([str(slot/"runtime/Scripts/python.exe"),"-I","-X","utf8",str(ROOT/"scripts/offline_partial.py"),"--slot",str(slot)],check=True,timeout=300)
    print("Clean-account prepare, repeated install and one-page offline PDF passed")
