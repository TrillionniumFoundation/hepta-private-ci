"""Measure one experiment stage's complete Linux child-process lifetime.

This outer record includes interpreter/import startup, frozen-byte verification,
artifact loading, execution, final serialization and process shutdown. Nested
stage/component timers remain useful attribution and must not be added to this
enclosing resource measure. No shell or proxy/environment changes are made.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time


def run(command, out):
    if not command or not sys.platform.startswith("linux"):
        raise ValueError("A command and Linux wait4 are required")
    out.mkdir(parents=True, exist_ok=False)
    started = datetime.now(timezone.utc).isoformat()
    wall = time.perf_counter()
    with (out/"OUTPUT.log").open("xb") as log:
        process = subprocess.Popen(command, stdout=log, stderr=subprocess.STDOUT)
        child, status, usage = os.wait4(process.pid, 0)
        if child != process.pid:
            raise RuntimeError("Unexpected child identity")
        process.returncode = os.waitstatus_to_exitcode(status)
    report = dict(schema="hcsn.experiment.stage-process.v1", command=command,
        started_at=started, finished_at=datetime.now(timezone.utc).isoformat(),
        returncode=process.returncode, child_pid=child,
        user_cpu_seconds=usage.ru_utime, system_cpu_seconds=usage.ru_stime,
        total_cpu_seconds=usage.ru_utime+usage.ru_stime,
        wall_seconds=time.perf_counter()-wall, peak_rss_bytes=usage.ru_maxrss*1024,
        voluntary_context_switches=usage.ru_nvcsw, involuntary_context_switches=usage.ru_nivcsw,
        output_sha256=hashlib.sha256((out/"OUTPUT.log").read_bytes()).hexdigest(),
        measurement="Linux wait4 on this exact stage process; retain nested subprocess records separately, do not add nested and enclosing totals",
        runner_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest())
    (out/"PROCESS.json").write_text(json.dumps(report, indent=2)+"\n")
    print(json.dumps(report), flush=True)
    return process.returncode


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    command = args.command[1:] if args.command[:1] == ["--"] else args.command
    raise SystemExit(run(command, args.out))
