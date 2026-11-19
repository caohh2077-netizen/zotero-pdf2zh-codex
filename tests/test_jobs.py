import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time
import unittest

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/"src"),str(ROOT/"src/launcher")]
import psutil
from winjob import child_tree,mutex
from launch import run


class Lifecycle(unittest.TestCase):
    def test_only_owned_tree_dies_and_can_restart(self):
        with tempfile.TemporaryDirectory() as tmp:
            work=Path(tmp)
            script=work/"owner.py"
            script.write_text("import pathlib,subprocess,sys,time\np=subprocess.Popen([sys.executable,'-c','import time;time.sleep(90)'])\n"
                              "pathlib.Path(sys.argv[1]).write_text(str(p.pid))\ntime.sleep(90)\n",encoding="utf-8")
            independent=subprocess.Popen([sys.executable,"-c","import time;time.sleep(90)"])
            try:
                for n in range(2):
                    marker=work/f"pid{n}"
                    with open(os.devnull,"rb") as inp, open(os.devnull,"wb") as out:
                        with child_tree([sys.executable,script,marker],os.environ.copy(),work,inp,out,out,wait_for_tree=True) as (_,parent):
                            deadline=time.monotonic()+8
                            while not marker.exists() and time.monotonic()<deadline:
                                time.sleep(.05)
                            child=int(marker.read_text())
                            owned=[psutil.Process(parent),psutil.Process(child)]
                            self.assertTrue(owned[1].is_running())
                        self.assertFalse(any(p.is_running() for p in owned))
                        self.assertIsNone(independent.poll())
            finally:
                independent.terminate()
                independent.wait(4)

    def test_foreign_port_is_preserved(self):
        with socket.socket() as foreign, tempfile.TemporaryDirectory() as tmp:
            foreign.bind(("127.0.0.1",0))
            foreign.listen()
            port=foreign.getsockname()[1]
            with self.assertRaisesRegex(RuntimeError,"occupied"):
                run(Path(tmp),{"root":tmp},port,None,os.getpid())
            self.assertEqual(foreign.getsockname()[1],port)
