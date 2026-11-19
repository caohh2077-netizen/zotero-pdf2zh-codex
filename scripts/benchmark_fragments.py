"""Measure single-attempt A/B translation of numbered synthetic samples without a PDF cache."""
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from contextlib import contextmanager
from functools import partial
import json
import os
from pathlib import Path
import re
import statistics
import sys
import tempfile
import threading
import time

import psutil

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"src"))
from adapter.appserver import Pool
from adapter.codex_translate import Failure, invoke, translate
from common import read
from winjob import resident_slot


def measure(settings, count, limit, mode, model, effort):
    starts, spans, latencies, errors = [], [], [], {}
    stop = threading.Event()
    process = psutil.Process()
    rss = [0]
    def monitor():
        while not stop.wait(.2):
            total = 0
            for p in [process,*process.children(recursive=True)]:
                try:
                    total += p.memory_info().rss
                except psutil.Error:
                    pass
            rss[0] = max(rss[0], total)
    thread = threading.Thread(target=monitor,daemon=True)
    thread.start()
    pool = Pool() if mode == "B" else None
    guard = threading.Lock()
    epoch = time.monotonic()
    def sample(n):
        tag = "[%d]" % (101+n)
        text = "The experiment recorded a stable temperature of 23.5 degrees "+tag+"."
        def timed(dispatch,*args):
            start = time.monotonic()
            with guard:
                starts.append(start)
            try:
                result = dispatch(*args)
                if tag not in result or "23.5" not in result or len(re.findall(r"\[\d+\]",result))!=1 or not re.search(r"[\u3400-\u9fff]",result):
                    raise Failure("format")
                return result
            finally:
                with guard:
                    spans.append((start,time.monotonic()))
        @contextmanager
        def reserve(user):
            with (pool.reserve(user) if pool else resident_slot(user)) as dispatch:
                yield partial(timed,dispatch or invoke)
        timed.reserve = reserve
        then = time.monotonic()
        try:
            translate(settings,"en","zh-CN",text,model,effort,timed)
            return time.monotonic()-then
        except Failure as error:
            return str(error)
    try:
        with ThreadPoolExecutor(max_workers=limit) as executor:
            futures = []
            for n in range(count):
                futures.append(executor.submit(sample,n))
                time.sleep(.1)  # Same 10 starts/second admission target in every group.
            first = None
            for future in as_completed(futures):
                value = future.result()
                if isinstance(value,str):
                    errors[value] = errors.get(value,0)+1
                else:
                    latencies.append(value)
                    if first is None:
                        first = time.monotonic()-epoch
    finally:
        if pool:
            pool.close()
        stop.set()
        thread.join()
    duration = time.monotonic()-epoch
    peak = max((sum(a<=at<b for a,b in spans) for at,_ in spans),default=0)
    return dict(mode=mode,workers=limit,submitted=count,started=len(starts),successful=len(latencies),errors=errors,
                peakLocalCalls=peak,firstObservedSeconds=round(first,3) if first else None,
                elapsedSeconds=round(duration,3),medianSeconds=round(statistics.median(latencies),3) if latencies else None,
                p95Seconds=round(sorted(latencies)[max(0,(len(latencies)*95+99)//100-1)],3) if latencies else None,
                successfulPerMinute=round(60*len(latencies)/duration,2),peakWorkingSetMiB=round(rss[0]/1048576,1))


if __name__ == "__main__":
    p=argparse.ArgumentParser()
    p.add_argument("--settings",type=Path,required=True)
    p.add_argument("--live",action="store_true",required=True)
    p.add_argument("--workers",nargs="+",type=int,default=[1,10,20])
    p.add_argument("--modes",nargs="+",choices=["A","B"],default=["A","B"])
    p.add_argument("--count",type=int,default=40)
    p.add_argument("--model",default="gpt-6.2-sol")
    p.add_argument("--effort",default="xhigh")
    p.add_argument("--out",type=Path,required=True)
    a=p.parse_args()
    if not 1<=a.count<=1000 or any(not 1<=v<=20 for v in a.workers):
        p.error("Invalid count or workers")
    settings=read(a.settings)
    with tempfile.TemporaryDirectory(prefix="pdf2zh-bench-") as tmp:
        state=Path(tmp)/"managed/state"
        state.mkdir(parents=True)
        settings["root"]=tmp
        for workers in a.workers:
            for mode in a.modes:
                result = measure(settings,a.count,workers,mode,a.model,a.effort)
                line=json.dumps(result)
                print(line,flush=True)
                with a.out.open("a",encoding="utf-8") as f:
                    f.write(line+"\n")
                if result["errors"]:
                    sys.exit(2)
