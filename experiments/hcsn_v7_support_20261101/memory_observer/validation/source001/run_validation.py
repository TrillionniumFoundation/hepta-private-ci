"""Fresh complete-worker receipts for observer tests and controlled probe."""

import datetime
import hashlib
import json
import os
from pathlib import Path
import resource
import subprocess
import sys
import time


ROOT = Path(__file__).resolve().parent


def run(name, arguments):
    destination = ROOT / "validation" / name
    destination.mkdir(parents=True, exist_ok=False)
    command = [sys.executable, *arguments]
    began_wall, began_cpu = time.monotonic(), time.process_time()
    began_utc = datetime.datetime.now(datetime.timezone.utc).isoformat()
    with (destination / "worker.log").open("wb") as log:
        worker = subprocess.Popen(command, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT)
        pid, status, measured = os.wait4(worker.pid, 0)
        worker.returncode = os.waitstatus_to_exitcode(status)
    receipt = {"schema": "hcsn-v7-memory-observer-complete-worker.v1", "command": command,
               "began_at_utc": began_utc, "ended_at_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
               "waited_pid_in_parent_namespace": pid, "exit_code": worker.returncode,
               "complete_worker_cpu_seconds": measured.ru_utime + measured.ru_stime,
               "wall_seconds": time.monotonic() - began_wall,
               "wrapper_own_cpu_seconds": time.process_time() - began_cpu,
               "wait4_largest_single_process_highwater_bytes": measured.ru_maxrss * 1024,
               "family_peak_rss_bytes": None,
               "accounting": "Complete waited-worker subtree CPU once; nested stage/process figures are not added again. Largest-single-process high-water is not family RSS.",
               "source_sha256": {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(ROOT.glob("*.py"))}}
    (destination / "RECEIPT.json").write_text(json.dumps(receipt, indent=2) + "\n")
    print(json.dumps({"name": name, "exit_code": worker.returncode, "cpu_seconds": receipt["complete_worker_cpu_seconds"],
                      "wall_seconds": receipt["wall_seconds"]}), flush=True)
    return worker.returncode


if __name__ == "__main__":
    status = run("tests001", ["-m", "unittest", "-v", "test_process_memory"])
    if status:
        raise SystemExit(status)
    raise SystemExit(run("probe001", ["probe_memory.py", "--output", "PROBE_REPORT.json"]))
