"""Record the complete factorial evaluation child, including imports and exit."""

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import time

from .train import sha, write


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--receipt", type=Path, required=True)
    parser.add_argument("arguments", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    arguments = args.arguments[1:] if args.arguments[:1] == ["--"] else args.arguments
    if not arguments or arguments[0] != "run":
        raise ValueError("This wrapper runs only the frozen factorial evaluation")
    command = [sys.executable, "-B", "-u", "-m", __package__ + ".evaluate", *arguments]
    registration, log = args.receipt.with_suffix(".registration.json"), args.receipt.with_suffix(".log")
    if any(p.exists() for p in (args.receipt, registration, log)):
        raise FileExistsError("Process evidence already exists")
    write(registration, {"command": command, "cwd": str(Path.cwd()), "wrapper_sha256": sha(__file__),
                         "registered_unix_ns": time.time_ns()})
    wall = time.perf_counter_ns()
    with log.open("xb") as stream:
        child = subprocess.Popen(command, stdout=stream, stderr=subprocess.STDOUT)
        waited, status, usage = os.wait4(child.pid, 0)
        child.returncode = os.waitstatus_to_exitcode(status)
        stream.flush()
        os.fsync(stream.fileno())
    receipt = {"command": command, "child_pid": child.pid, "waited_pid": waited,
               "exit_code": child.returncode, "wall_ns": time.perf_counter_ns() - wall,
               "child_cpu_ns": round(1e9 * (usage.ru_utime + usage.ru_stime)),
               "peak_rss_bytes_linux": usage.ru_maxrss * 1024,
               "registration_sha256": sha(registration), "log_sha256": sha(log)}
    write(args.receipt, receipt)
    print(json.dumps(receipt), flush=True)
    raise SystemExit(child.returncode)


if __name__ == "__main__":
    main()
