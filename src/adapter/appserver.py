"""Experiment B. Each turn owns a new ephemeral thread in a document-local process pool."""
from collections import deque
from contextlib import ExitStack, contextmanager
import json
import os
from pathlib import Path
import queue
import tempfile
import threading
import time

from adapter.codex_translate import Failure, instruction, restrictions, validate
from common import LOCK
from winjob import child_tree, resident_slot


class Worker:
    def __init__(self, binary, env, effort, deadline):
        self.stack = ExitStack()
        self.residency = ExitStack()
        self.events = queue.Queue()
        self.sequence = 0
        self.backlog = deque()
        self.closed = False
        try:
            self.cwd = self.stack.enter_context(tempfile.TemporaryDirectory(prefix="zpc-session-"))
            ir, iw = os.pipe()
            or_, ow = os.pipe()
            self.writer = self.stack.enter_context(os.fdopen(iw, "wb", buffering=0))
            reader = self.stack.enter_context(os.fdopen(or_, "rb"))
            with os.fdopen(ir, "rb") as stdin, os.fdopen(ow, "wb") as stdout, open(os.devnull, "wb") as err:
                args = [binary, "app-server", "--listen", "stdio://", *restrictions(effort)]
                self.stack.enter_context(child_tree(args, env, self.cwd, stdin, stdout, err))
            def receive():
                try:
                    for line in reader:
                        self.events.put(json.loads(line))
                except (OSError, ValueError):
                    pass
                finally:
                    self.events.put(None)
            threading.Thread(target=receive, daemon=True).start()
            self.call("initialize", {"clientInfo":{"name":"pdf2zh_codex","title":"PDF2zh","version":LOCK["release"]},
                                     "capabilities":{"experimentalApi":True}}, min(deadline, time.monotonic()+25))
            self.send({"method":"initialized"})
        except BaseException:
            self.close()
            raise

    def send(self, data):
        try:
            self.writer.write((json.dumps(data, ensure_ascii=False)+"\n").encode("utf-8"))
        except BrokenPipeError:
            raise Failure("network") from None

    def next(self, deadline):
        if time.monotonic() >= deadline:
            raise Failure("timeout")
        try:
            row = self.backlog.popleft() if self.backlog else self.events.get(timeout=max(0, deadline-time.monotonic()))
        except queue.Empty:
            raise Failure("timeout") from None
        if row is None:
            raise Failure("network")
        if "method" in row and "id" in row:
            self.send({"id":row["id"], "error":{"code":-32601, "message":"Unavailable in translation"}})
            raise Failure("tools")
        return row

    def call(self, method, params, deadline):
        self.sequence += 1
        ident = self.sequence
        self.send({"id":ident, "method":method, "params":params})
        pending = []
        while True:
            row = self.next(deadline)
            if row.get("id") == ident:
                self.backlog.extendleft(reversed(pending))
                if "error" in row:
                    raise Failure.from_response(str(row["error"]))
                return row.get("result", {})
            if row.get("method") in ("turn/completed", "item/completed", "item/started", "error"):
                pending.append(row)

    def run(self, model, effort, text, deadline, prompt):
        thread = self.call("thread/start", {
            "model":model, "modelProvider":"openai", "ephemeral":True, "cwd":self.cwd,
            "sandbox":"read-only", "approvalPolicy":"never", "baseInstructions":prompt,
            "config":{"web_search":"disabled","mcp_servers":{},"project_doc_max_bytes":0},
        }, deadline)["thread"]["id"]
        turn = None
        try:
            turn = self.call("turn/start", {"threadId":thread, "model":model, "effort":effort,
                             "input":[{"type":"text", "text":text, "text_elements":[]}]}, deadline)["turn"]["id"]
            answer = ""
            while True:
                row = self.next(deadline)
                params = row.get("params") or {}
                if params.get("threadId") != thread or params.get("turnId", turn) != turn:
                    continue
                method = row.get("method")
                if method in ("item/started", "item/completed"):
                    item = params["item"]
                    if item["type"] not in ("userMessage", "agentMessage", "reasoning", "contextCompaction"):
                        raise Failure("tools")
                    if method == "item/completed" and item["type"] == "agentMessage":
                        answer = item.get("text", "").strip()
                if method == "error" and not params.get("willRetry"):
                    raise Failure.from_response(str(params.get("error")))
                if method == "turn/completed" and params["turn"]["id"] == turn:
                    if params["turn"]["status"] != "completed":
                        raise Failure.from_response(str(params["turn"].get("error")))
                    validate(text, answer)
                    self.call("thread/unsubscribe", {"threadId":thread}, min(deadline,time.monotonic()+4))
                    return answer
        except BaseException:
            if turn:
                try:
                    self.send({"id":-1,"method":"turn/interrupt","params":{"threadId":thread,"turnId":turn}})
                except (OSError, Failure):
                    pass
            raise

    def close(self):
        if not self.closed:
            self.closed = True
            try:
                self.stack.close()
            finally:
                self.residency.close()


class Pool:
    def __init__(self):
        self.lock = threading.Lock()
        self.idle = {}
        self.closed = False

    def expire(self, worker):
        with self.lock:
            if self.idle.pop(worker, None) is None:
                return
        worker.close()

    @contextmanager
    def reserve(self, user, *, deadline=None):
        with self.lock:
            if self.closed:
                raise Failure("failed")
            worker = next(iter(self.idle), None)
            if worker:
                self.idle.pop(worker).cancel()
        with ExitStack() as pending:
            if worker is None:
                pending.enter_context(resident_slot(user, deadline=deadline))
            def run(binary, env, source, target, text, deadline, model, effort, prompt=None):
                nonlocal worker
                if worker is None:
                    worker = Worker(binary, env, effort, deadline)
                    worker.residency = pending.pop_all()
                return worker.run(model, effort, text, deadline, prompt if prompt is not None else instruction(source, target))
            try:
                yield run
            except BaseException:
                if worker:
                    worker.close()
                raise
        if worker is None:
            return
        with self.lock:
            if self.closed:
                worker.close()
            else:
                timer = threading.Timer(10, self.expire, args=(worker,))
                timer.daemon = True
                self.idle[worker] = timer
                timer.start()

    def close(self):
        with self.lock:
            self.closed = True
            idle = list(self.idle.items())
            self.idle.clear()
        for worker, timer in idle:
            timer.cancel()
            worker.close()
