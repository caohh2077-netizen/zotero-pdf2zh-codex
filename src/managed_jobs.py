"""Small integration surface for the pinned Flask server and its original output processors."""
import json
import os
from pathlib import Path
import re
import shutil
import threading

from flask import g, jsonify, request
import win32event
import win32process

from adapter.codex_translate import ERRORS, environment, language
from common import LOCK, PKG, read
from fragments import Fragments
from options import Selection, capabilities
from winjob import child_tree

SLOT = PKG.parent
TAIL = re.compile(r"__(?P<model>[A-Za-z0-9._-]+?)__(?P<effort>none|minimal|low|medium|high|xhigh|max|ultra)(?=\.pdf$)", re.I)
KIND = re.compile(r"([.-](?:(?:LR_|TB_)?dual|mono|mono-cut|dual-cut|crop-compare|compare|cut))$", re.I)


def command(slot, source, target, model, effort):
    return (f'"{(slot/"runtime/Scripts/python.exe").as_posix()}" -I -X utf8 '
            f'"{(slot/"pkg/src/adapter/codex_translate.py").as_posix()}" --source {language(source)} '
            f'--target {language(target)} --prompt-version 1 --model {model} --effort {effort}')


class Job:
    def __init__(self, directory, selection, title, original, task):
        self.directory = directory.resolve()
        self.selection = selection
        self.title = title
        self.original = original
        self.task = task
        self.cancel = threading.Event()
        self.fragments = Fragments()


def records(stream):
    while True:
        position = stream.tell()
        line = stream.readline()
        if not line.endswith(b"\n"):
            stream.seek(position)
            return
        yield json.loads(line)


class ManagedJobs:
    def __init__(self, app, manager, output):
        self.manager = manager
        self.output = Path(output).resolve()
        self.settings = read(SLOT / "settings.json")
        self.active = {}
        self.lock = threading.Lock()
        @app.teardown_request
        def release_unaccepted(error):
            if hasattr(g, "codex_task") and not getattr(g, "codex_handed_off", False):
                self.release(g.codex_task)
        app.add_url_rule("/api/codex/capabilities", "codex_options", self.catalog_route)
        app.add_url_rule("/api/codex/tasks/<task>/cancel", "codex_cancel", self.cancel, methods=["POST"])

    def catalog(self, refresh=False):
        return capabilities(self.settings["codex"], environment(), refresh)

    def catalog_route(self):
        try:
            return jsonify(self.catalog(request.args.get("refresh") == "1"))
        except Exception as error:
            return jsonify(protocol=2, error=str(error)), 503

    def cancel(self, task):
        with self.lock:
            job = self.active.get(task)
            if job:
                job.cancel.set()
        return (jsonify(cancelled=True), 202) if job else (jsonify(cancelled=False), 404)

    def input(self, data, config, file_name, task):
        suffix = TAIL.search(file_name)
        if not data.get("codex") and (not suffix or request.path == "/translate"):
            return str(self.output), file_name
        if data.get("codex") and (config.engine != "pdf2zh_next" or config.service != "clitranslator"):
            raise ValueError("Codex 需要 pdf2zh_next 和 clitranslator。")
        if not task:
            import uuid
            task = str(uuid.uuid4())
        if suffix and request.path != "/translate":
            # Post-processing an existing attachment retains its original provenance.
            selection = Selection(suffix["model"], suffix["effort"], 1, 1)
        else:
            selection = Selection.parse(data, self.catalog())
        if Path(file_name).is_reserved() or any(c in file_name for c in '<>:"|?*'):
            raise ValueError("无效的 PDF 文件名。")
        clean = TAIL.sub("", file_name)
        match = KIND.search(Path(clean).stem)
        internal = "paper" + (match[0] if match else "") + ".pdf"
        directory = SLOT / "jobs" / task
        directory.mkdir(parents=True)
        job = Job(directory, selection, Path(clean).stem, Path(internal).stem, task)
        config.codex_job = job
        config.qps, config.pool_size = selection.qps, selection.workers
        with self.lock:
            self.active[task] = job
        g.codex_task = task
        return str(directory), internal

    def release(self, task):
        with self.lock:
            job = self.active.pop(task, None)
        if job:
            shutil.rmtree(job.directory, ignore_errors=True)

    def info(self, info, config):
        job = getattr(config, "codex_job", None)
        if job:
            s = job.selection
            info.update(modelName=s.model, fileName=job.title+".pdf", fragments=job.fragments.snapshot(),
                        message=job.fragments.message())
            info["config"].update(model=s.model, effort=s.effort, protocol=3 if s.subject else 2,
                                  poolSize=s.workers, subjectField=s.subject)
        return info

    def engine(self, job, config, cmd):
        s = job.selection
        conf = job.directory / "settings.toml"
        cli = command(SLOT, config.sourceLang, config.targetLang, s.model, s.effort)
        conf.write_text("[clitranslator_detail]\nclitranslator_command = "+json.dumps(cli)+
                        "\nclitranslator_timeout = 300\n", encoding="utf-8")
        args = cmd[1:]
        for option, value in (("--config-file", conf), ("--output", job.directory)):
            args[args.index(option)+1] = str(value)
        if "--pool-max-worker" not in args:
            args.extend(["--pool-max-worker", str(s.workers)])
        spawn = [SLOT/"runtime/Scripts/python.exe", "-I", "-X", "utf8", PKG/"src/engine_runner.py", *args]
        env = dict(os.environ, ZPC_JOB_DIR=str(job.directory), ZPC_TESSDATA=str(SLOT/"tessdata"),
                   ZPC_SUBJECT_FIELD=s.subject)
        paths, message = [], ""
        progress = job.fragments
        with open(os.devnull,"rb") as inp, open(os.devnull,"wb") as out:
            with (job.directory/"progress.jsonl").open("a+b") as events, (job.directory/"dispatch.jsonl").open("a+b") as dispatch:
                with child_tree(spawn, env, job.directory, inp, out, out) as (proc, _):
                    while True:
                        done = win32event.WaitForSingleObject(proc, 90) == 0
                        changed = False
                        percent = None
                        for stream in (dispatch, events):
                            for row in records(stream):
                                changed = True
                                if row.get("type") == "output":
                                    paths = [Path(p).resolve() for p in row["paths"]]
                                elif row.get("type") == "failure":
                                    message = row["message"]
                                else:
                                    progress.update(row)
                                    percent = row.get("overall_progress", percent)
                        if changed:
                            update = {"fragments":progress.snapshot(),"message":progress.message()}
                            if percent is not None:
                                update["progress"] = round(percent)
                            self.manager.update_task(job.task, update)
                        if job.cancel.is_set():
                            progress.terminal = True
                            raise ValueError(progress.message()+" · 已取消")
                        if done:
                            rc = win32process.GetExitCodeProcess(proc)
                            break
        if rc and progress.failed:
            raise ValueError(progress.message()+" · "+ERRORS.get(progress.error, "片段翻译失败"))
        if rc or not paths or any(p.parent != job.directory or not p.is_file() for p in paths):
            raise ValueError(message or "引擎没有返回完整的翻译文件。")
        return list(map(str, paths))

    def publish(self, paths, job, classifier):
        published, products = [], []
        try:
            for raw in paths:
                if job.cancel.is_set():
                    raise ValueError(job.fragments.message()+" · 已取消")
                path = Path(raw).resolve()
                if path.parent != job.directory or path.suffix.lower() != ".pdf":
                    raise ValueError("无效的任务产物。")
                base = path.stem.removeprefix("paper")
                title = job.title
                if job.original != "paper":
                    title = KIND.sub("", title)
                tail = f"__{job.selection.model}__{job.selection.effort}.pdf"
                budget = 220-len((base+tail).encode("utf-8"))
                title = title.encode("utf-8")[:max(4,budget)].decode("utf-8","ignore")
                for i in range(10000):
                    nonce = "" if i == 0 else f" ({i+1})"
                    dest = self.output / (title+nonce+base+tail)
                    try:
                        # Windows rename publishes the complete file and rejects
                        # existing names. Both directories belong to this slot.
                        os.rename(path, dest)
                        break
                    except FileExistsError:
                        continue
                else:
                    raise ValueError("无法分配唯一文件名。")
                published.append(dest)
                products.append({"kind":classifier(raw), "name":dest.name, "download":dest.name,
                                 "model":job.selection.model, "effort":job.selection.effort})
            return {"status":"success", "taskId":job.task, "fileList":[p.name for p in published],
                    "filePaths":list(map(str,published)), "outputDir":str(self.output), "products":products,
                    "fragments":job.fragments.snapshot(), "partial":bool(job.fragments.failed),
                    "message":(f"部分完成，{job.fragments.failed} 个片段保留原文 · " +
                               ERRORS.get(job.fragments.error,"片段翻译失败")) if job.fragments.failed else ""}
        except BaseException:
            for dest in published:
                dest.unlink(missing_ok=True)
            raise
