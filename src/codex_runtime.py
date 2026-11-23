"""Provision the pinned translation CLI independently of the desktop app."""
from pathlib import Path
import tarfile
import tomllib

from common import LOCK, digest, download, read, save, verified_copy


REPAIR_MESSAGE = "无法使用翻译专用 Codex CLI，请运行 Doctor.ps1 检查并修复。"


def executable(root):
    return Path(root) / "managed/tools/codex" / LOCK["codex_cli"]["version"] / "codex.exe"


def ensure(root, *, source=None, asset_dir=None):
    spec = LOCK["codex_cli"]
    binary = executable(root)
    if binary.is_file() and digest(binary) == spec["sha256"]:
        return binary

    if source is not None:
        with Path(source).open("rb") as stream:
            verified_copy(stream, binary, spec["sha256"])
        return binary

    name = spec["asset"] + ".tar.gz"
    archive = Path(root) / "managed/downloads/codex" / spec["version"] / name
    url = f"https://github.com/openai/codex/releases/download/rust-v{spec['version']}/{name}"
    if asset_dir:
        local = (Path(asset_dir) / name).resolve()
        if local.is_file() and local != archive.resolve():
            url = local.as_uri()
    download(url, archive, spec["tar_gz_sha256"])
    with tarfile.open(archive, "r|gz") as package:
        member = package.next()
        if member is None or member.name != spec["asset"] or not member.isfile():
            raise ValueError("Unexpected file in the pinned Codex CLI archive")
        with package.extractfile(member) as stream:
            verified_copy(stream, binary, spec["sha256"])
    return binary


def record_executable(settings_file, binary):
    settings = read(settings_file)
    if settings.get("codex") != str(binary):
        settings["codex"] = str(binary)
        save(settings_file, settings)


def migrate_previous(slot, binary):
    """Keep an older compatible release usable if the user rolls back."""
    manifest = slot / "pkg/compat/upstream.lock.toml"
    if not manifest.is_file():
        return
    previous = tomllib.loads(manifest.read_text("utf-8"))
    if LOCK["codex_cli"]["version"] not in previous.get("codex_versions", ()):
        return
    settings_file = slot / "settings.json"
    old = Path(read(settings_file)["codex"])
    if "windowsapps" in (part.casefold() for part in old.parts) or not old.is_file():
        record_executable(settings_file, binary)
