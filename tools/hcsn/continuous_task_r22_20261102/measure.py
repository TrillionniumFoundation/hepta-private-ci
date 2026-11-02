"""Outer child-family receipt; all scientific inner timings are nested."""

import argparse
import json
import os
from pathlib import Path
import subprocess
import time


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--receipt", type=Path, required=True)
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    command = args.command[1:] if args.command[:1] == ["--"] else args.command
    if not command or args.receipt.exists():
        raise ValueError("Fresh receipt and a child command required")
    start, own = time.monotonic(), time.process_time()
    with args.receipt.with_suffix(".stdout.log").open("xb") as out, args.receipt.with_suffix(".stderr.log").open("xb") as err:
        child = subprocess.Popen(command, stdout=out, stderr=err)
        _, status, usage = os.wait4(child.pid, 0)
        child.returncode = os.waitstatus_to_exitcode(status)
    receipt = dict(command=command, exit_code=child.returncode,
        cpu_user_seconds=usage.ru_utime, cpu_system_seconds=usage.ru_stime,
        cpu_seconds=usage.ru_utime + usage.ru_stime, wall_seconds=time.monotonic()-start,
        maximum_single_process_rss_kib=usage.ru_maxrss,
        wrapper_cpu_before_receipt_seconds=time.process_time()-own,
        simultaneous_family_peak_rss_kib=None,
        scope="Complete scientific child and waited descendants, includes interpreter/imports/input checks/numerics/archive and final JSON writes. Wrapper and transport excluded; inner CPU is nested and must not be added. No GPU or energy measurement.")
    with args.receipt.open("x") as stream:
        json.dump(receipt, stream, indent=2, allow_nan=False)
        stream.write("\n")
    print(json.dumps(receipt), flush=True)
    raise SystemExit(child.returncode)
