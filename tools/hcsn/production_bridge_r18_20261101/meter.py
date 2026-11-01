"""Outer Linux process-family cost for the Python/Rust bridge checks."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import time


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("binary", type=Path)
    parser.add_argument("output", type=Path)
    a = parser.parse_args()
    if a.output.exists():
        raise FileExistsError(a.output)
    root = Path(__file__).resolve().parent
    started = time.perf_counter()
    with a.output.with_suffix(".stdout").open("x") as stdout, a.output.with_suffix(".stderr").open("x") as stderr:
        child = subprocess.Popen([sys.executable, str(root / "check.py"), str(a.binary.resolve()),
                                  str(a.output), "--external-receipts", str(root / "PROVIDER_RECEIPTS.json")],
                                 stdout=stdout, stderr=stderr)
        _, status, usage = os.wait4(child.pid, 0)
        child.returncode = os.waitstatus_to_exitcode(status)
    receipt = dict(exit_code=child.returncode, total_cpu_seconds=usage.ru_utime + usage.ru_stime,
                   wall_seconds=time.perf_counter() - started, max_rss_linux_kib=usage.ru_maxrss,
                   scope="Complete check interpreter and waited Rust descendants; compile and developer/auditor costs separate")
    with a.output.with_suffix(".process.json").open("x") as stream:
        json.dump(receipt, stream, indent=2)
        stream.write("\n")
    print(json.dumps(receipt))
    raise SystemExit(child.returncode)
