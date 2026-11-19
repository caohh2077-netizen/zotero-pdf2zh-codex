"""Apply small, verified hooks only to a new release slot."""
from pathlib import Path
import sys
from common import atomic, digest

SERVER = "f5c464f98daa7e466bea33ebc257e0d17beb41513188c9deaed549a84d57e9ee"
MANAGER = "c5c3b61431231d6118a8afd37153e6ff6e0f705ca5090014db2dc609af20e5b2"
TRANSLATOR = "2f670122ccce619e27864aceab763bb687b8ef5fd074c2c0221b41b6db01ff14"


def patched(path, expected, edits):
    src = path.read_text("utf-8")
    marker = "# PDF2ZH_CODEX_V2"
    if src.startswith(marker):
        return
    if digest(path) != expected:
        raise ValueError(f"Unexpected upstream source: {path.name}")
    for old, new, count in edits:
        if src.count(old) != count:
            raise ValueError(f"Upstream changed at {path.name}: {old[:70]}")
        src = src.replace(old, new)
    compile(src, str(path), "exec")
    atomic(path, (marker+"\n"+src).encode("utf-8"))


def install(slot):
    server = slot / "server"
    patched(server/"server.py", SERVER, [
        ("class PDFTranslator:", "from pathlib import Path as CodexPath\nimport sys as codex_sys\n"
         "codex_sys.path.insert(0,str(CodexPath(__file__).resolve().parents[1]/'pkg/src'))\n"
         "from managed_jobs import ManagedJobs\n\nclass PDFTranslator:", 1),
        ("        self.setup_routes()", "        self.codex = ManagedJobs(self.app, task_manager, output_folder)\n        self.setup_routes()", 1),
        ("'version': __version__,\n            'message': 'PDF2zh", "'version': __version__, 'codexProtocol': 2,\n            'message': 'PDF2zh", 1),
        ("def process_request(self):", "def process_request(self, task_id=None):", 1),
        ("        base = os.path.abspath(output_folder)\n        input_path", "        base, file_name = self.codex.input(data, config, file_name, task_id)\n        input_path", 1),
        ("input_path, config = self.process_request()\n            infile_type", "input_path, config = self.process_request(task_id)\n            infile_type", 4),
        ("    def crop(self):\n        try:", "    def crop(self):\n        task_id = str(uuid.uuid4())\n        try:", 1),
        ("        return {\n            'taskId': task_id,", "        return self.codex.info({\n            'taskId': task_id,", 1),
        ("            'config': config_summary,\n        }", "            'config': config_summary,\n        }, config)", 1),
        ("def _success_files_payload(self, paths):\n        existing", """def _success_files_payload(self, paths):
        if paths:
            directory = CodexPath(paths[0]).resolve().parent
            job = self.codex.active.get(directory.name)
            if job and job.directory == directory:
                return self.codex.publish(paths, job, self.get_filetype)
        existing""", 1),
        ("        task_manager.add_task(task_id, task_info)", """        original_worker = worker
        def worker():
            try:
                return original_worker()
            finally:
                self.codex.release(task_id)
        from flask import g
        g.codex_handed_off = True
        task_manager.add_task(task_id, task_info)""", 1),
        ("        config.update_config_file(config_path[pdf2zh_next])", """        job = getattr(config, "codex_job", None)
        if not job:
            config.update_config_file(config_path[pdf2zh_next])""", 1),
        ("        fileName = os.path.splitext(os.path.basename(input_path))[0]\n        no_watermark_mono",
         "        if job:\n            return self.codex.engine(job, config, cmd)\n\n        fileName = os.path.splitext(os.path.basename(input_path))[0]\n        no_watermark_mono", 1),
    ])
    patched(server/"utils/task_manager.py", MANAGER, [
        ('            self.progress_history.insert(0, history_item)', '            if "fragments" in task:\n'
         '                history_item["fragments"] = dict(task["fragments"])\n            self.progress_history.insert(0, history_item)', 1),
    ])
    path = slot/"runtime/Lib/site-packages/pdf2zh_next/translator/utils.py"
    patched(path, TRANSLATOR, [
        ('            translator.translate("Hello", ignore_cache=True)',
         '            from pathlib import Path\n            import sys\n'
         '            package = str(Path(__file__).resolve().parents[5] / "pkg/src")\n'
         '            if package not in sys.path:\n                sys.path.insert(0, package)\n'
         '            from engine_bridge import bind\n            if not bind(translator):\n'
         '                translator.translate("Hello", ignore_cache=True)', 1),
    ])


if __name__ == "__main__":
    install(Path(sys.argv[1]))
