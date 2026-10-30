"""Measure one explicitly requested reporting/audit command, including process exit.

This helper does not select experiments, change budgets, or supervise training.
Use a new receipt directory outside the command's own output directory. The
child's body timers are nested in complete_child_cpu_seconds and are not added
again. This parent's self clock is independent and ends at its receipt cutoff.
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


def digest(path):
    result = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(1048576), b""):
            result.update(block)
    return result.hexdigest()


def run(output, command):
    if not command:
        raise ValueError("An explicit command after -- is required")
    output = Path(output).resolve()
    output.mkdir(parents=True, exist_ok=False)
    (output / "source").mkdir()
    (output / "source" / Path(__file__).name).write_bytes(Path(__file__).read_bytes())
    request = {
        "schema": "hcsn-measured-support-request.v1",
        "command": command,
        "cwd": str(Path.cwd()),
        "source_sha256": digest(__file__),
        "started_utc": datetime.now(timezone.utc).isoformat(),
        "environment_contract": {name: os.environ.get(name) for name in (
            "PYTHONDONTWRITEBYTECODE", "OMP_NUM_THREADS", "MKL_NUM_THREADS",
            "OPENBLAS_NUM_THREADS", "NUMEXPR_NUM_THREADS")},
    }
    with (output / "REQUEST.json").open("x") as handle:
        json.dump(request, handle, indent=2, sort_keys=True)
        handle.write("\n")
    started = time.monotonic()
    with (output / "process.log").open("xb") as log:
        child = subprocess.Popen(command, stdout=log, stderr=subprocess.STDOUT)
        pid, status, usage = os.wait4(child.pid, 0)
        if pid != child.pid:
            raise RuntimeError("Unexpected waited child")
        child.returncode = os.waitstatus_to_exitcode(status)
    receipt = {
        "schema": "hcsn-measured-support-execution.v1",
        "status": "completed" if child.returncode == 0 else "failed",
        "returncode": child.returncode,
        "request_sha256": digest(output / "REQUEST.json"),
        "source_sha256": digest(__file__),
        "log_sha256": digest(output / "process.log"),
        "complete_child_cpu_seconds": usage.ru_utime + usage.ru_stime,
        "child_user_cpu_seconds": usage.ru_utime,
        "child_system_cpu_seconds": usage.ru_stime,
        "child_peak_rss_kib_linux": usage.ru_maxrss,
        "wall_seconds": time.monotonic() - started,
        "supervisor_self_cpu_seconds_through_receipt": time.process_time(),
        "measurement": "Linux wait4 complete child, including its waited descendants and exit; body timers are nested. Supervisor self is separate through the receipt cutoff.",
        "completed_utc": datetime.now(timezone.utc).isoformat(),
    }
    with (output / "EXECUTION.json").open("x") as handle:
        json.dump(receipt, handle, indent=2, sort_keys=True, allow_nan=False)
        handle.write("\n")
    print(json.dumps({"receipt": str(output / "EXECUTION.json"),
                      "returncode": child.returncode,
                      "complete_child_cpu_seconds": receipt["complete_child_cpu_seconds"]}))
    if child.returncode:
        raise SystemExit(child.returncode)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    command = args.command[1:] if args.command[:1] == ["--"] else args.command
    run(args.output, command)
