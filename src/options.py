"""Public model metadata and immutable options for one translation."""
from dataclasses import dataclass
from hashlib import sha256
import json
import os
from pathlib import Path
import re
import subprocess
import threading
import unicodedata

from common import LOCK

MODEL_ID = re.compile(r"[a-zA-Z0-9][a-zA-Z0-9._-]{0,79}\Z")
EFFORTS = {"none", "minimal", "low", "medium", "high", "xhigh", "max", "ultra"}
LIMIT = 20
SUBJECT_TEMPLATE = "As a translator specializing in {field}, choose established terms in the target language that fit the context."
SUBJECT_PRESETS = {
    "ai-ml": ("人工智能、机器学习与具身智能", "artificial intelligence, machine learning, and embodied AI"),
    "ai-machine-learning": ("人工智能、机器学习", "artificial intelligence and machine learning"),
    "computer-systems": ("计算机系统与软件工程", "computer systems and software engineering"),
    "electrical-power": ("电气与电力工程", "electrical and power engineering"),
    "bioinformatics": ("生物信息学与基因组学", "bioinformatics and genomics"),
    "clinical-medicine": ("临床医学", "clinical medicine"),
    "materials": ("材料科学与工程", "materials science and engineering"),
    "physics": ("物理学", "physics"),
    "chemistry": ("化学", "chemistry"),
    "math-stats": ("数学与统计学", "mathematics and statistics"),
    "econ-finance": ("经济学与金融学", "economics and finance"),
}
_catalog_lock = threading.Lock()
_cached = {}


def normalize_subject(value):
    if not isinstance(value, str):
        raise ValueError("请填写自定义学科领域。")
    if any(unicodedata.category(c).startswith("C") or unicodedata.category(c) in ("Zl", "Zp") for c in value):
        raise ValueError("学科领域请使用单行文字，移除换行或不可见字符。")
    field = " ".join(unicodedata.normalize("NFKC", value).split())
    if not 1 <= len(field) <= 64:
        raise ValueError("学科领域须为 1–64 个字符。")
    if not any(c.isalpha() for c in field):
        raise ValueError("学科领域须包含文字。")
    if any(unicodedata.category(c)[0] not in "LMN" and unicodedata.category(c) != "Pd"
           and c not in " /+&,()'’·" for c in field):
        raise ValueError("请输入领域名称，移除句末标点或其他特殊字符。")
    return field


def subject_prefix(field):
    return SUBJECT_TEMPLATE.format(field=field) if field else ""


def prefix_digest(prefix):
    return sha256(prefix.encode("utf-8")).hexdigest()


def request_subject(options):
    protocol = options.get("protocol")
    if type(protocol) is not int or protocol not in (2, 3):
        raise ValueError("Codex 协议不匹配，请安装配套的 PDF2zh 前端和后端。")
    if protocol == 2:
        if "subject" in options:
            raise ValueError("学科领域需要协议 3。")
        return ""
    subject = options.get("subject")
    if isinstance(subject, dict):
        if subject.get("kind") == "custom" and set(subject) == {"kind", "name"}:
            return normalize_subject(subject["name"])
        if subject.get("kind") == "preset" and set(subject) == {"kind", "id"}:
            key = subject["id"]
            if isinstance(key, str) and key in SUBJECT_PRESETS:
                return SUBJECT_PRESETS[key][1]
            raise ValueError("未知学科预设，请重新选择。")
    raise ValueError("协议 3 需要有效的预设或自定义学科领域。")


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
                  "subjectContext": {"version": 1, "requestProtocol": 3, "template": SUBJECT_TEMPLATE,
                                     "presets": [{"id": key, "label": label, "field": field}
                                                 for key, (label, field) in SUBJECT_PRESETS.items()]},
                  "defaults": {"model": LOCK["model"], "effort": LOCK["effort"], "workers": 10}}
        _cached[identity] = (path.stat().st_mtime_ns if path.is_file() else None, result)
        return result


@dataclass(frozen=True)
class Selection:
    model: str
    effort: str
    qps: int
    workers: int
    subject: str = ""

    @classmethod
    def parse(cls, body, catalog):
        selected = body.get("codex")
        if not isinstance(selected, dict):
            raise ValueError("Codex 协议不匹配，请安装配套的 PDF2zh 前端和后端。")
        subject = request_subject(selected)
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
        return cls(model, effort, qps, workers, subject)
