import io
import hashlib
import json
import os
from pathlib import Path
import shlex
import sys
import tarfile
import tempfile
import time
import tomllib
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/"src"),str(ROOT/"src/adapter"),str(ROOT/"scripts")]
import check_upstream
import codex_runtime
import codex_translate as cli
import manage
import managed_jobs
import migrate
import options
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
            with patch("common.urlopen",return_value=io.BytesIO(b"bad")):
                with self.assertRaises(ValueError):
                    manage.download("https://example.com",root/"asset.zip","0"*64)
            self.assertEqual(read(root/"active.json"),{"active":"good"})
            self.assertFalse((root/"asset.zip").exists())

    def test_desktop_update_does_not_change_catalog_or_translation_executable(self):
        content = b"pinned official fixture"
        sha = hashlib.sha256(content).hexdigest()
        with tempfile.TemporaryDirectory() as folder, patch.dict(LOCK["codex_cli"], {"sha256": sha}):
            root = Path(folder)
            old = root/"WindowsApps/OpenAI.Codex_old/app/resources/codex.exe"
            atomic(old, content)
            binary = codex_runtime.ensure(root, source=old)
            self.assertEqual(binary, root/"managed/tools/codex"/LOCK["codex_cli"]["version"]/"codex.exe")
            before = binary.stat().st_mtime_ns
            old.unlink()
            newer = root/"WindowsApps/OpenAI.Codex_new/app/resources/codex.exe"
            atomic(newer, b"different CLI")
            with patch.dict(os.environ, {"PATH": str(newer.parent)}), patch("common.urlopen", side_effect=AssertionError):
                self.assertEqual(codex_runtime.ensure(root), binary)
                self.assertEqual(binary.stat().st_mtime_ns, before)
            self.assertEqual(binary.read_bytes(), content)
            jobs = object.__new__(managed_jobs.ManagedJobs)
            jobs.settings = {"root": str(root), "codex": str(old)}
            env = dict(cli.environment(), TEMP=folder)
            with patch.object(managed_jobs, "environment", return_value=env), patch.object(managed_jobs, "capabilities") as catalog:
                jobs.catalog(refresh=True)
                catalog.assert_called_once_with(binary, env, True)
            (root/"managed/state").mkdir()
            with patch.object(cli, "environment", return_value=env), patch.object(cli, "ensure_cli") as check, \
                 patch.object(cli, "invoke", return_value="样品") as invoke:
                self.assertEqual(cli.translate(jobs.settings, "en", "zh-CN", "sample"), "样品")
                self.assertEqual(check.call_args.args[0], binary)
                self.assertEqual(invoke.call_args.args[0], binary)

    def test_archive_integrity_and_offline_repair(self):
        data = b"known CLI fixture"
        spec = LOCK["codex_cli"]
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            archive = root/(spec["asset"] + ".tar.gz")
            with tarfile.open(archive, "w:gz") as package:
                member = tarfile.TarInfo(spec["asset"])
                member.size = len(data)
                package.addfile(member, io.BytesIO(data))
            archive_sha = hashlib.sha256(archive.read_bytes()).hexdigest()
            binary = codex_runtime.executable(root)
            atomic(binary, b"old executable")
            with patch.dict(spec, {"sha256": "0"*64, "tar_gz_sha256": "0"*64}):
                with self.assertRaisesRegex(ValueError, "SHA-256 mismatch"):
                    codex_runtime.ensure(root, asset_dir=root)
            with patch.dict(spec, {"sha256": "0"*64, "tar_gz_sha256": archive_sha}):
                with self.assertRaisesRegex(ValueError, "SHA-256 mismatch"):
                    codex_runtime.ensure(root, asset_dir=root)
            self.assertEqual(binary.read_bytes(), b"old executable")
            self.assertEqual(list(binary.parent.iterdir()), [binary])
            archive.unlink()
            with patch.dict(spec, {"sha256": hashlib.sha256(data).hexdigest(), "tar_gz_sha256": archive_sha}), \
                 patch("common.urlopen", side_effect=AssertionError):
                self.assertEqual(codex_runtime.ensure(root), binary)
                binary.unlink()
                self.assertEqual(codex_runtime.ensure(root).read_bytes(), data)

    def test_compatible_rollback_migrates_only_the_executable(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            binary = codex_runtime.executable(root)
            slot = root/"old-slot"
            manifest = slot/"pkg/compat/upstream.lock.toml"
            version = LOCK["codex_cli"]["version"]
            atomic(manifest, f'codex_versions=["{version}"]'.encode())
            config = slot/"settings.json"
            external = root/"WindowsApps/OpenAI.Codex_old/app/resources/codex.exe"
            settings = {"root": folder, "source": "de", "target": "zh-CN", "codex": str(external)}
            save(config, settings)
            codex_runtime.migrate_previous(slot, binary)
            self.assertEqual(read(config), dict(settings, codex=str(binary)))
            custom = root/"standalone/codex.exe"
            atomic(custom, b"older user-managed CLI")
            save(config, dict(settings, codex=str(custom)))
            codex_runtime.migrate_previous(slot, binary)
            self.assertEqual(read(config)["codex"], str(custom))
            atomic(manifest, b'codex_versions=["other"]')
            save(config, settings)
            codex_runtime.migrate_previous(slot, binary)
            self.assertEqual(read(config), settings)

    def test_refresh_distinguishes_bundled_models_from_account_updates(self):
        def catalog(model):
            return {"models": [{"slug": model, "supported_reasoning_levels": [{"effort": "xhigh"}]}]}
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            binary = root/"codex.exe"
            atomic(binary, b"fixture")
            cache = root/"models_cache.json"
            env = {"CODEX_HOME": folder}
            bundled, account, changed = map(catalog, ("bundled-model", "account-model", "new-account-model"))
            save(cache, account)
            with patch.object(options, "cli_catalog", return_value=bundled) as run:
                result = options.capabilities(binary, env, refresh=True)
                self.assertEqual((result["source"], result["models"][0]["id"]), ("account-cache", "account-model"))
                self.assertEqual(result, options.capabilities(binary, env))
                self.assertEqual(run.call_count, 2)
                self.assertTrue(run.call_args.kwargs["bundled"])
            with patch.object(options, "cli_catalog", side_effect=[changed, bundled]):
                result = options.capabilities(binary, env, refresh=True)
                self.assertEqual((result["source"], result["models"][0]["id"]), ("codex-debug", "new-account-model"))
            yesterday = time.time() - options.ACCOUNT_FALLBACK_SECONDS - 10
            os.utime(cache, (yesterday, yesterday))
            with patch.object(options, "cli_catalog", return_value=bundled) as run:
                result = options.capabilities(binary, env, refresh=True)
                self.assertEqual(result["models"][0]["id"], "bundled-model")
                run.assert_called_once_with(binary, env)
            atomic(cache, b"unrecognized cache format")
            with patch.object(options, "cli_catalog", return_value=changed):
                self.assertEqual(options.capabilities(binary, env)["models"][0]["id"], "new-account-model")

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

    def test_upgrade_from_enabled_previous_paired_xpi(self):
        from launcher.launch import compatible
        from pair_frontend import EXTENSION, pairing_state

        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            profile = root/"profile"
            app = root/"zotero.exe"
            (root/"application.ini").write_text("[App]\nVersion="+LOCK["zotero_versions"][0], "utf-8")
            extension = {"id": EXTENSION, "active": True, "version": "4.1.8.2"}
            save(profile/"extensions.json", {"addons": [extension]})
            marker, _, path, _ = pairing_state(root/"managed", profile)
            atomic(path, b"previous managed XPI")
            save(marker, {"sha": hashlib.sha256(path.read_bytes()).hexdigest()})
            compatible(profile, app, pairing_root=root)
            with self.assertRaises(RuntimeError):
                compatible(profile, app)
            extension["active"] = False
            save(profile/"extensions.json", {"addons": [extension]})
            with self.assertRaises(RuntimeError):
                compatible(profile, app, pairing_root=root)
            extension.update(active=True, version=LOCK["xpi_version"])
            save(profile/"extensions.json", {"addons": [extension]})
            atomic(path, b"unrecognized XPI")
            with self.assertRaises(RuntimeError):
                compatible(profile, app, pairing_root=root)

    def test_new_template_keeps_known_values_and_new_defaults(self):
        current=tomlkit.parse('[service]\nlabel="default"\nworkers=2\nnew_flag=true\n')
        prior=tomlkit.parse('[service]\nlabel="saved"\nworkers="wrong type"\nretired=42\n')
        migrate.merge(current,prior)
        self.assertEqual(current.unwrap(),{"service":{"label":"saved","workers":2,"new_flag":True}})
