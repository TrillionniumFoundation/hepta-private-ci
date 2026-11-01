"""Run the support-only contract checks and retain complete worker receipts.

Linux is required for wait4 CPU accounting and the process-memory component.
No trained model or real AV confirmation is executed by this entry point.
"""

import argparse
import datetime
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time


ROOT = Path(__file__).resolve().parent


def utc():
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True,
                        help="New output directory; existing evidence is never overwritten")
    args = parser.parse_args()
    if not sys.platform.startswith("linux") or not hasattr(os, "wait4"):
        parser.error("This validation/accounting entry point requires Linux wait4")
    args.out.mkdir(parents=True, exist_ok=False)
    began = utc()
    wrapper_cpu = time.process_time()
    envelope = time.monotonic()
    receipts = []
    for name, folder, module in (
        ("content_interface", ROOT / "content_interface", "test_content_interface"),
        ("memory_observer", ROOT / "memory_observer", "test_process_memory"),
        ("baseline_recovery", ROOT, "test_restore_check"),
    ):
        command = [sys.executable, "-m", "unittest", "-v", module]
        start_wall = time.monotonic()
        start_utc = utc()
        with (args.out / (name + ".log")).open("xb") as log:
            worker = subprocess.Popen(command, cwd=folder, stdout=log,
                                      stderr=subprocess.STDOUT,
                                      env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"})
            pid, status, usage = os.wait4(worker.pid, 0)
            worker.returncode = os.waitstatus_to_exitcode(status)
        receipt = {
            "name": name, "command": command, "cwd": str(folder),
            "started_at_utc": start_utc, "ended_at_utc": utc(),
            "exit_code": worker.returncode, "waited_namespace_pid": pid,
            "complete_worker_cpu_seconds": usage.ru_utime + usage.ru_stime,
            "wall_seconds": time.monotonic() - start_wall,
            "largest_single_process_highwater_bytes": usage.ru_maxrss * 1024,
            "family_peak_rss_bytes": None,
            "source_sha256": {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                              for p in sorted(folder.glob("*.py"))},
        }
        receipts.append(receipt)
        print(json.dumps({"name": name, "exit_code": worker.returncode,
                          "cpu_seconds": receipt["complete_worker_cpu_seconds"]}), flush=True)
    result = {
        "schema": "hcsn-v7-support-contract-validation.v1",
        "started_at_utc": began, "ended_at_utc": utc(),
        "status": "pass" if all(x["exit_code"] == 0 for x in receipts) else "fail",
        "complete_worker_cpu_seconds": sum(x["complete_worker_cpu_seconds"] for x in receipts),
        "sequential_envelope_wall_seconds": time.monotonic() - envelope,
        "wrapper_measured_interval_cpu_seconds": time.process_time() - wrapper_cpu,
        "receipts": receipts,
        "trained_model_calls": 0, "real_av_confirmations": 0,
        "accounting": "Each complete waited worker is charged once. Nested Git-fixture and "
                      "test stages are not added again. Wrapper interval excludes interpreter "
                      "startup and final receipt serialization. Highwater is not family RSS. "
                      "These are support-test costs, not candidate economics.",
    }
    with (args.out / "RECEIPT.json").open("x") as stream:
        stream.write(json.dumps(result, indent=2) + "\n")
    return 0 if result["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
