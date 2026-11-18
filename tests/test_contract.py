import io
import json
import os
from pathlib import Path
import shlex
import sys
import tempfile
import tomllib
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/"src"),str(ROOT/"src/adapter"),str(ROOT/"scripts")]
import check_upstream
import codex_translate as cli
import manage
import migrate
import tomlkit
from common import LOCK, atomic, read, save, slot_path
from pdf2zh_next.config import ConfigManager
from pdf2zh_next.translator.translator_impl.clitranslator import CLITranslatorTranslator


class Contract(unittest.TestCase):
    def test_upstream_report_detects_moved_tag_and_incomplete_candidate(self):
        locked = {"tag": "v1", "commit": "1"*40, "assets": {"server.zip": "a"*64}}
        reply = {
            "commits/v1": {"sha": locked["commit"]},
            "releases/tags/v1": {"assets": [{"name": "server.zip", "digest": "sha256:" + "a"*64}]},
            "releases/latest": {"tag_name": "v2", "html_url": "https://example.com/v2",
                                "assets": [{"name": "server.zip", "digest": "sha256:" + "b"*64}]},
            "commits/v2": {"sha": "2"*40},
        }
        report = "\n".join(check_upstream.inspect(locked, reply.__getitem__))
        self.assertIn("2"*40, report)
        self.assertIn("sha256:" + "b"*64, report)
        reply["releases/latest"]["assets"] = []
        with self.assertRaisesRegex(ValueError, "missing server.zip"):
            check_upstream.inspect(locked, reply.__getitem__)
        reply["commits/v1"]["sha"] = "3"*40
        with self.assertRaisesRegex(ValueError, "moved v1"):
            check_upstream.inspect(locked, reply.__getitem__)

    def test_final_output_and_error_events(self):
        lines=[{"type":"thread.started"},{"type":"item.completed","item":{"type":"agent_message","text":"中文 [1]"}},
               {"type":"turn.completed"}]
        self.assertEqual(cli.final_text("\n".join(map(json.dumps,lines))),"中文 [1]")
        for item in ("command_execution","mcp_tool_call","file_change"):
            with self.assertRaisesRegex(cli.Failure,"tools"):
                cli.final_text(json.dumps({"type":"item.started","item":{"type":item}}))
        with self.assertRaisesRegex(cli.Failure,"format"):
            cli.final_text("{}")
        with self.assertRaisesRegex(cli.Failure,"quota"):
            cli.final_text(json.dumps({"type":"turn.failed","error":"usage limit"}))

    def test_placeholder_nesting_and_citations(self):
        sentence="The <style id='2'>sample {v0}</style> was cold [1]."
        cli.validate(sentence,"<style id='2'>样品 {v0}</style> 很冷 [1]。")
        for bad in ("", "missing [1]", "</style><style id='2'>{v0} [1]"):
            with self.assertRaises(cli.Failure):
                cli.validate(sentence,bad)

    def test_environment_and_command(self):
        with patch.dict(os.environ,{"OPENAI_API_KEY":"example-fixture","CODEX_API_KEY":"example-fixture",
                                    "DEEPSEEK_API_KEY":"example-fixture","ZPC_REAL_PROFILE":"real-profile"}):
            env=cli.environment()
            self.assertEqual(env["USERPROFILE"],"real-profile")
            self.assertFalse(any(k.endswith("API_KEY") for k in env))
        cmd=cli.arguments("codex.exe","en","de")
        self.assertIn("--ignore-user-config",cmd)
        self.assertIn("read-only",cmd)
        for feature in cli.DISABLE:
            self.assertIn(feature,cmd)
        with self.assertRaises(ValueError):
            cli.language("bad option")

    def test_config_preserves_other_provider_and_real_engine_stdin(self):
        with tempfile.TemporaryDirectory(prefix="翻译 test ") as tmp:
            slot=Path(tmp)
            conf=slot/"server/config/config.toml"
            conf.parent.mkdir(parents=True)
            conf.write_text('[translation]\nqps=1\n[clitranslator_detail]\nclitranslator_command=""\n'
                            '[deepseek_detail]\nmodel="test-previous"\n',encoding="utf-8")
            manage.configure(slot,"en","de")
            data=tomllib.loads(conf.read_text("utf-8"))
            self.assertEqual(data["deepseek_detail"]["model"],"test-previous")
            args=shlex.split(data["clitranslator_detail"]["clitranslator_command"])
            self.assertEqual(args[0],(slot/"runtime/Scripts/python.exe").as_posix())
            self.assertIn("de",args)
            fake=slot/"fake cli.py"
            fake.write_text('import sys\nprint("diagnostic",file=sys.stderr)\nprint(sys.stdin.read().strip())',encoding="utf-8")
            opts=slot/"fake.toml"
            opts.write_text("[clitranslator_detail]\nclitranslator_command = "+json.dumps(
                f'"{Path(sys.executable).as_posix()}" -X utf8 "{fake.as_posix()}"')+"\n",encoding="utf-8")
            with patch.object(sys,"argv",["pdf2zh_next","--clitranslator","--config-file",str(opts),"--lang-out","de"]):
                model=ConfigManager().initialize_config()
                engine=CLITranslatorTranslator(model,None)
                self.assertEqual(engine.do_translate("A {v0} [1]\n温度"),"A {v0} [1]\n温度")

    def test_integrity_and_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            for bad in ("..","../elsewhere","legacy","D:thing"):
                with self.assertRaises(ValueError):
                    slot_path(root,bad)
            save(root/"active.json",{"active":"good"})
            with patch("urllib.request.urlopen",side_effect=AssertionError), patch("manage.urlopen",return_value=io.BytesIO(b"bad")):
                with self.assertRaises(ValueError):
                    manage.download("https://example.com",root/"asset.zip","0"*64)
            self.assertEqual(read(root/"active.json"),{"active":"good"})
            self.assertFalse((root/"asset.zip").exists())

    def test_version_switch_failure_defer_and_rollback(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            state=root/"managed/state"
            for name in ("a","b"):
                save(slot_path(root,name)/"ready.json",{"id":name})
            save(state/"active.json",{"active":"a","previous":None})
            with patch.object(manage,"LOCATION",root/"location.json"), patch("manage.subprocess.run") as processes:
                processes.return_value.stdout=b""
                with patch("manage.shortcut",side_effect=OSError("test failure")):
                    with self.assertRaises(OSError):
                        manage.active_switch(root,"b")
                self.assertEqual(read(state/"active.json")["active"],"a")
                with patch("manage.shortcut"):
                    processes.return_value.stdout=b"zotero.exe"
                    manage.active_switch(root,"b")
                    self.assertEqual(read(state/"active.json")["active"],"a")
                    self.assertEqual(read(state/"pending.json")["active"],"b")
                    processes.return_value.stdout=b""
                    manage.active_switch(root,"b")
                    manage.active_switch(root,"a")
                    self.assertEqual(read(state/"active.json"),{"active":"a","previous":"b"})
                    with self.assertRaises(FileNotFoundError):
                        manage.active_switch(root,"incomplete")

    def test_new_template_keeps_known_values_and_new_defaults(self):
        current=tomlkit.parse('[service]\nlabel="default"\nworkers=2\nnew_flag=true\n')
        prior=tomlkit.parse('[service]\nlabel="saved"\nworkers="wrong type"\nretired=42\n')
        migrate.merge(current,prior)
        self.assertEqual(current.unwrap(),{"service":{"label":"saved","workers":2,"new_flag":True}})
