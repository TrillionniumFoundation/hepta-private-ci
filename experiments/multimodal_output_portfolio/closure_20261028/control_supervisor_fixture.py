"""Explicit subprocess workloads for the operational resource-guard check."""

import os
from pathlib import Path
import subprocess
import sys
import time


def burn(seconds):
    start = time.process_time()
    value = 1.0
    while time.process_time() - start < seconds:
        value = (value + 1.001) % 37
    return value


if __name__ == "__main__":
    mode = sys.argv[1]
    print(f"fixture={mode} pid={os.getpid()}", flush=True)
    if mode == "burn":
        burn(float(sys.argv[2]))
    elif mode in {"tree", "orphan", "complete"}:
        seconds = .02 if mode == "complete" else 2.0
        children = [subprocess.Popen([sys.executable, str(Path(__file__).resolve()), "burn", str(seconds)])
                    for _ in range(2)]
        print("children=" + ",".join(str(p.pid) for p in children), flush=True)
        if mode != "orphan":
            burn(seconds)
            for child in children:
                child.wait()
    elif mode == "codec":
        child = subprocess.Popen(["ffmpeg", "-v", "error", "-threads", "1", "-f", "lavfi", "-i",
                                  "testsrc=size=512x512:rate=30", "-t", "30", "-f", "null", "-"])
        print(f"codec_child={child.pid}", flush=True)
        child.wait()
    else:
        raise ValueError("Unknown registered workload")
