from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from adapter import appserver, codex_translate as cli
import engine_bridge
from managed_jobs import command
from options import SUBJECT_PRESETS, Selection, normalize_subject, subject_prefix


class SubjectTests(unittest.TestCase):
    def test_protocol_and_normalization(self):
        def parse(protocol, **extra):
            selected = dict(protocol=protocol, model="sol", effort="xhigh", **extra)
            return Selection.parse({"codex": selected}, {"models": [{"id":"sol", "efforts":["xhigh"]}]}).subject
        self.assertEqual(parse(2), "")
        self.assertEqual(list(SUBJECT_PRESETS)[:2], ["ai-ml", "ai-machine-learning"])
        self.assertEqual(SUBJECT_PRESETS["ai-machine-learning"], ("人工智能、机器学习", "artificial intelligence and machine learning"))
        for name, (_, field) in SUBJECT_PRESETS.items():
            self.assertEqual(parse(3, subject={"kind":"preset", "id":name}), field)
            self.assertEqual(normalize_subject(field), field)
        self.assertEqual(parse(3, subject={"kind":"custom", "name":"　脑机接口（ＥＥＧ／ＭＥＧ）  与  C++ "}),
                         "脑机接口(EEG/MEG) 与 C++")
        self.assertEqual(normalize_subject("𠮷"*64), "𠮷"*64)
        for value in ("", " ", "12", "a"*65, "\nAI", "AI\rML", "AI\u200b", "x\u2028y", "AI。", "A!", "A?"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                normalize_subject(value)
        for version, extra in ((2, {"subject":None}), (2, {"subject":{"kind":"preset","id":"ai-ml"}}),
                               (3, {}), (3, {"subject":{"kind":"preset","id":"unknown"}}),
                               (3, {"subject":{"kind":"custom","name":""}}), (4, {})):
            with self.subTest(version=version, extra=extra), self.assertRaises(ValueError):
                parse(version, **extra)

    def test_golden_prompt(self):
        base = cli.effective_instruction("en", "zh-CN").encode()
        self.assertEqual(len(base), 465)
        self.assertEqual(hashlib.sha256(base).hexdigest(), "b6fcd7a93127c0dd398ff909b2582da6ae2f578a06e6fe3e05fe0256adb7a6e6")
        for source, target in (("en","zh-CN"), ("de","en")):
            for field in (SUBJECT_PRESETS["ai-ml"][1], SUBJECT_PRESETS["ai-machine-learning"][1], "电力系统继电保护", "speech science"):
                actual = cli.effective_instruction(source, target, subject_prefix(field)).encode().split(b"\n")
                self.assertEqual(actual, [f"As a translator specializing in {field}, choose established terms in the target language that fit the context.".encode(),
                                          cli.instruction(source, target).removeprefix("You are a scientific translator. ").encode()])

    def test_cli_and_app_server_boundaries(self):
        text = "<style>Signal {v0}</style> [4]\nSecond line"
        answer = "<style>信号 {v0}</style> [4]\n第二行"
        seen = {}
        @contextmanager
        def fake_process(args, env, work, inp, out, err):
            seen["cli"] = (args[-1].encode(), inp.read())
            rows = [{"type":"item.completed","item":{"type":"agent_message","text":answer}}, {"type":"turn.completed"}]
            out.write("\n".join(map(json.dumps, rows)).encode())
            handle = cli.win32event.CreateEvent(None, True, True, None)
            try:
                yield (handle, 0)
            finally:
                handle.Close()
        worker = object.__new__(appserver.Worker)
        worker.cwd = "."
        def rpc(method, params, deadline):
            if method == "thread/start":
                seen["thread"] = params["baseInstructions"].encode()
                return {"thread":{"id":"thread"}}
            if method == "turn/start":
                seen["input"] = params["input"][0]["text"].encode()
                return {"turn":{"id":"turn"}}
            return {}
        worker.call = rpc
        worker.close = lambda: worker.residency.close()
        with tempfile.TemporaryDirectory() as work, patch.object(cli, "ensure_cli"), \
             patch.object(cli, "child_tree", fake_process), \
             patch.object(cli.win32process, "GetExitCodeProcess", return_value=0), patch.object(appserver, "Worker", return_value=worker):
            (Path(work) / "managed/state").mkdir(parents=True)
            settings = {"root":work, "codex":sys.executable}
            for field in ("", SUBJECT_PRESETS["ai-ml"][1], "电气工程"):
                events = iter([
                    {"method":"item/completed","params":{"threadId":"thread","item":{"type":"agentMessage","text":answer}}},
                    {"method":"turn/completed","params":{"threadId":"thread","turn":{"id":"turn","status":"completed"}}},
                ])
                worker.next = lambda deadline: next(events)
                prefix = subject_prefix(field)
                pool = appserver.Pool()
                try:
                    for runner in (None, pool):
                        self.assertEqual(cli.translate(settings, "en", "zh-CN", text, runner=runner, prefix=prefix), answer)
                finally:
                    pool.close()
                self.assertEqual(seen["cli"], (seen["thread"], seen["input"]))
                self.assertEqual(seen["cli"], (cli.effective_instruction("en", "zh-CN", prefix).encode(), text.encode()))

    def test_persistent_cache_and_concurrent_snapshots(self):
        from pdf2zh_next.config import ConfigManager
        from pdf2zh_next.translator.translator_impl.clitranslator import CLITranslatorTranslator
        from pdf2zh_next.translator.rate_limiter.qps_rate_limiter import QPSRateLimiter
        ai, power = (SUBJECT_PRESETS[k][1] for k in ("ai-ml","electrical-power"))
        calls = []
        def capture(settings, source, target, text, model, effort, runner, *, prefix, pace):
            calls.append((text, prefix))
            return prefix + "|" + text
        with tempfile.TemporaryDirectory() as work, patch.object(engine_bridge, "translate", capture), \
             patch.dict(os.environ, {"ZPC_JOB_DIR":work}), patch.object(engine_bridge, "SLOT", Path(work)):
            slot = Path(work)
            (slot/"runtime/Scripts").mkdir(parents=True)
            (slot/"runtime/Scripts/python.exe").touch()
            (slot/"settings.json").write_text("{}")
            cfg = slot/"test.toml"
            cfg.write_text("[clitranslator_detail]\nclitranslator_command="+json.dumps(command(slot,"en","zh-CN","sol","xhigh")))
            with patch.object(sys, "argv", ["pdf2zh_next","--clitranslator","--config-file",str(cfg)]):
                config = ConfigManager().initialize_config()
            def create(field):
                with patch.dict(os.environ, {"ZPC_SUBJECT_FIELD":field}):
                    engine = CLITranslatorTranslator(config, QPSRateLimiter(1000))
                    self.assertTrue(engine_bridge.bind(engine))
                    return engine
            old = CLITranslatorTranslator(config, QPSRateLimiter(1000))
            old.cache.set("legacy", "旧译文")
            self.assertEqual(create("").translate("legacy"), "旧译文")
            old.add_cache_impact_parameters("codex_subject_v1", hashlib.sha256(
                f"Use the standard terminology of {ai}.".encode()).hexdigest())
            old.cache.set("same", "旧领域译文")
            plain_ai = SUBJECT_PRESETS["ai-machine-learning"][1]
            sequence = [("",1),(ai,2),(power,3),(ai,3),("",3),(normalize_subject("  "+ai+"  "),3),
                        (plain_ai,4),(plain_ai,4),(ai,4)]
            for field, expected_calls in sequence:
                self.assertEqual(create(field).translate("same"), subject_prefix(field)+"|same")
                self.assertEqual(len(calls), expected_calls)
            engines = [(create(ai), ai), (create(power), power)]
            with patch.dict(os.environ, {"ZPC_SUBJECT_FIELD":"physics"}), ThreadPoolExecutor(10) as executor:
                jobs = [(executor.submit(engine.translate, "parallel "+str(i)), field, i)
                        for i in range(12) for engine, field in engines]
                for future, field, i in jobs:
                    self.assertEqual(future.result(), subject_prefix(field)+"|parallel "+str(i))
            self.assertEqual(len(calls), 28)
