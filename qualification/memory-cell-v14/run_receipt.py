"""Retain process-level resource receipts, including failed research attempts."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import resource
import subprocess
import sys
import time


def network():
    path = Path("/proc/net/dev")
    if not path.exists():
        return None
    rows = [line.split(":", 1)[1].split() for line in path.read_text().splitlines()[2:]]
    return {"rx_bytes": sum(int(row[0]) for row in rows),
            "tx_bytes": sum(int(row[8]) for row in rows)}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--receipt", type=Path, required=True)
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    command = args.command[1:] if args.command[:1] == ["--"] else args.command
    if not command:
        parser.error("a command is required")
    args.receipt.parent.mkdir(parents=True, exist_ok=True)
    started, usage, before = time.perf_counter(), resource.getrusage(resource.RUSAGE_CHILDREN), network()
    result = {"schema": "hepta.memory.v14.process-receipt.v1", "command": command,
              "source_commit": os.getenv("GITHUB_SHA"), "run_id": os.getenv("GITHUB_RUN_ID"),
              "run_attempt": os.getenv("GITHUB_RUN_ATTEMPT"), "platform": platform.platform(),
              "boot_id": Path("/proc/sys/kernel/random/boot_id").read_text().strip(),
              "python": sys.version, "script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
              "network_scope": "All interfaces in this runner during the command; includes unrelated runner traffic.",
              "energy_joules": None, "cloud_bill_usd": None}
    code = 1
    try:
        code = subprocess.run(command, check=False).returncode
    finally:
        after_usage, after = resource.getrusage(resource.RUSAGE_CHILDREN), network()
        result.update(exit_code=code, wall_seconds=time.perf_counter() - started,
                      child_cpu_seconds=after_usage.ru_utime + after_usage.ru_stime - usage.ru_utime - usage.ru_stime,
                      child_peak_rss_bytes=after_usage.ru_maxrss * 1024,
                      runner_network_delta=None if before is None else {key: after[key] - before[key] for key in before})
        args.receipt.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    raise SystemExit(code)


if __name__ == "__main__":
    main()
