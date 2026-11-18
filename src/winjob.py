"""Own exactly the Windows children started for this operation."""
from contextlib import contextmanager
import msvcrt
import os
import subprocess
import uuid

import win32api
import win32con
import win32event as event
import win32job
import win32process as proc


@contextmanager
def mutex(name, milliseconds=0):
    handle = event.CreateMutex(None, False, "Local\\ZPC." + name)
    acquired = False
    try:
        acquired = event.WaitForSingleObject(handle, milliseconds) in (0, 128)
        yield acquired
    finally:
        if acquired:
            event.ReleaseMutex(handle)
        handle.Close()


@contextmanager
def child_tree(argv, env, cwd, stdin, stdout, stderr):
    job = win32job.CreateJobObject(None, "Local\\ZPC.job." + uuid.uuid4().hex)
    process = thread = None
    try:
        info = win32job.QueryInformationJobObject(job, win32job.JobObjectExtendedLimitInformation)
        info["BasicLimitInformation"]["LimitFlags"] |= win32job.JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        win32job.SetInformationJobObject(job, win32job.JobObjectExtendedLimitInformation, info)
        startup = proc.STARTUPINFO()
        startup.dwFlags = win32con.STARTF_USESTDHANDLES
        handles = [msvcrt.get_osfhandle(f.fileno()) for f in (stdin, stdout, stderr)]
        startup.hStdInput, startup.hStdOutput, startup.hStdError = handles
        originals = {h: os.get_handle_inheritable(h) for h in handles}
        try:
            for h in originals:
                os.set_handle_inheritable(h, True)
            process, thread, pid, _ = proc.CreateProcess(
                str(argv[0]), subprocess.list2cmdline(list(map(str, argv))), None, None, True,
                win32con.CREATE_SUSPENDED | win32con.CREATE_NO_WINDOW, env, str(cwd), startup)
        finally:
            for h, value in originals.items():
                os.set_handle_inheritable(h, value)
        try:
            win32job.AssignProcessToJobObject(job, process)
            proc.ResumeThread(thread)
        except BaseException:
            win32api.TerminateProcess(process, 1)
            raise
        yield process, pid
    finally:
        job.Close()
        if thread:
            thread.Close()
        if process:
            event.WaitForSingleObject(process, 3000)
            process.Close()
