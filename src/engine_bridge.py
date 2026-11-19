"""Loaded by the pinned pdf2zh-next initialization hook, also in Windows spawn children."""
import atexit
from concurrent.futures import Future
import os
from pathlib import Path
import threading

from adapter.codex_translate import SLOT, language, translate
from common import read
from options import EFFORTS, MODEL_ID, prefix_digest, subject_prefix


def bind(translator):
    command = getattr(translator, "command", None)
    args = getattr(translator, "args", [])
    if (translator.__class__.__module__ != "pdf2zh_next.translator.translator_impl.clitranslator"
            or not command or Path(command).resolve() != (SLOT / "runtime/Scripts/python.exe").resolve()
            or len(args) != 14 or args[:3] != ["-I", "-X", "utf8"]
            or Path(args[3]).resolve() != (SLOT / "pkg/src/adapter/codex_translate.py").resolve()
            or args[4::2] != ["--source", "--target", "--prompt-version", "--model", "--effort"]):
        return False
    source, target, version, model, effort = args[5::2]
    if version != "1" or not MODEL_ID.fullmatch(model) or effort not in EFFORTS:
        raise ValueError("Invalid managed translator options")
    language(source)
    language(target)
    if not os.environ.get("ZPC_JOB_DIR"):
        raise ValueError("请从配套的 Codex 翻译前端提交文档。")
    settings = read(SLOT / "settings.json")
    prefix = subject_prefix(os.environ.get("ZPC_SUBJECT_FIELD", ""))
    if prefix:
        translator.add_cache_impact_parameters("codex_subject_v1", prefix_digest(prefix))
    runner = None
    if os.environ.get("ZPC_EXPERIMENT") == "app-server":
        from adapter.appserver import Pool
        runner = Pool()
        atexit.register(runner.close)
    # Single-flight also retains failed futures until this document exits. A layout
    # fallback requesting the same failed source cannot send it to the model again.
    pending = {}
    lock = threading.Lock()
    def one_attempt(text, rate_limit_params=None):
        with lock:
            future = pending.get(text)
            owner = future is None
            if owner:
                future = pending[text] = Future()
        if owner:
            try:
                result = translate(settings, source, target, text, model, effort, runner, prefix=prefix)
                future.set_result(result)
            except Exception as error:
                future.set_exception(error)
        return future.result()
    translator.do_translate = one_attempt
    cached_translate = translator.translate
    def keep_partial(text, ignore_cache=False, rate_limit_params=None):
        try:
            return cached_translate(text, ignore_cache, rate_limit_params)
        except Exception:
            # A failed dispatch raised before BaseTranslator could cache anything.
            # Preserve the original paragraph on the translated page, continue the
            # document, and retain the recorded failure for the terminal response.
            with lock:
                future = pending.get(text)
            if future is not None and future.done() and future.exception() is not None:
                return text
            raise
    translator.translate = keep_partial
    return True
