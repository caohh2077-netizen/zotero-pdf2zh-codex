"""Public model metadata and immutable options for one translation."""
from dataclasses import dataclass
import json
import os
from pathlib import Path
import re
import subprocess
import threading

from common import LOCK

MODEL_ID = re.compile(r"[a-zA-Z0-9][a-zA-Z0-9._-]{0,79}\Z")
EFFORTS = {"none", "minimal", "low", "medium", "high", "xhigh", "max", "ultra"}
LIMIT = 20
_catalog_lock = threading.Lock()
_cached = {}


def project(data):
    models = []
    for entry in data["models"]:
        ident = entry.get("slug", "")
        if not MODEL_ID.fullmatch(ident) or entry.get("visibility", "list") != "list":
            continue
        efforts = [v["effort"] for v in entry.get("supported_reasoning_levels", []) if v.get("effort") in EFFORTS]
        if efforts:
            models.append({"id": ident, "name": entry.get("display_name") or ident,
                           "efforts": efforts, "default": entry.get("default_reasoning_level") or efforts[0]})
    if not models:
        raise ValueError("Codex 模型目录为空，请在 Codex 登录后刷新模型。")
    return models


def capabilities(binary, env, refresh=False):
    path = Path(env["CODEX_HOME"]) / "models_cache.json"
    identity = (str(binary), os.stat(binary).st_mtime_ns, str(path))
    with _catalog_lock:
        stamp = path.stat().st_mtime_ns if path.is_file() else None
        if not refresh and identity in _cached and _cached[identity][0] == stamp:
            return _cached[identity][1]
        source = "account-cache"
        if refresh or not path.is_file():
            proc = subprocess.run([str(binary), "debug", "models"], capture_output=True, env=env, timeout=30,
                                  creationflags=subprocess.CREATE_NO_WINDOW)
            if proc.returncode:
                raise ValueError("Codex 无法刷新当前账户的模型目录，请检查登录及网络。")
            data = json.loads(proc.stdout)
            source = "codex-debug"
        else:
            data = json.loads(path.read_bytes())
        result = {"protocol": 2, "models": project(data), "source": source, "maxWorkers": LIMIT,
                  "defaults": {"model": LOCK["model"], "effort": LOCK["effort"], "workers": 10}}
        _cached[identity] = (path.stat().st_mtime_ns if path.is_file() else None, result)
        return result


@dataclass(frozen=True)
class Selection:
    model: str
    effort: str
    qps: int
    workers: int

    @classmethod
    def parse(cls, body, catalog):
        selected = body.get("codex")
        if not isinstance(selected, dict) or selected.get("protocol") != 2:
            raise ValueError("Codex 协议不匹配，请安装配套的 PDF2zh 前端和后端。")
        model, effort = selected.get("model"), selected.get("effort")
        if not any(m["id"] == model and effort in m["efforts"] for m in catalog["models"]):
            raise ValueError(f"当前账户目录不支持 {model} / {effort}，请刷新模型或重新选择。")
        def integer(name, default, minimum, maximum):
            value = str(body.get(name, default))
            if not value.isascii() or not value.isdecimal() or not minimum <= int(value) <= maximum:
                raise ValueError(f"{name} 须在 {minimum} 到 {maximum} 之间。")
            return int(value)
        qps = integer("qps", 10, 1, 1000)
        workers = integer("poolSize", 10, 0, LIMIT) or min(qps, LIMIT)
        return cls(model, effort, qps, workers)
