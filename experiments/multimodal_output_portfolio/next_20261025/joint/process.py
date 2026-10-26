"""Measure one joint evaluation child, including imports and waited codecs."""

import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import time


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write(path, value):
    with path.open("x") as stream:
        json.dump(value, stream, indent=2, sort_keys=True, allow_nan=False)
        stream.write("\n"); stream.flush(); os.fsync(stream.fileno())


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--receipt", type=Path, required=True)
    parser.add_argument("--module", choices=(__package__ + ".evaluate", __package__ + ".preflight"), required=True)
    parser.add_argument("arguments", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    entry = Path(importlib.util.find_spec(args.module).origin)
    extra = args.arguments[1:] if args.arguments[:1] == ["--"] else args.arguments
    command = [sys.executable, "-B", "-u", "-m", args.module, *extra]
    registration, log = args.receipt.with_suffix(".registration.json"), args.receipt.with_suffix(".log")
    if any(path.exists() for path in (args.receipt, registration, log)):
        raise FileExistsError("Never overwrite an earlier process attempt")
    write(registration, {"command": command, "cwd": os.getcwd(), "entrypoint_sha256": sha(entry),
                         "wrapper_sha256": sha(__file__), "registered_unix_ns": time.time_ns(),
                         "cgroup_memory_events": Path("/sys/fs/cgroup/memory.events").read_text()})
    began = time.monotonic_ns()
    with log.open("xb") as stream:
        child = subprocess.Popen(command, stdout=stream, stderr=subprocess.STDOUT)
        pid, status, usage = os.wait4(child.pid, 0)
        child.returncode = os.waitstatus_to_exitcode(status)
        stream.flush(); os.fsync(stream.fileno())
    write(args.receipt, {"child_pid": child.pid, "waited_pid": pid, "exit_code": child.returncode,
                        "wall_ns": time.monotonic_ns() - began,
                        "child_user_seconds": usage.ru_utime, "child_system_seconds": usage.ru_stime,
                        "peak_rss_bytes": usage.ru_maxrss * 1024,
                        "registration_sha256": sha(registration), "log_sha256": sha(log),
                        "cost_scope": "Whole Python child including imports and waited codec children; RSS is peak, not summed process RSS",
                        "cgroup_memory_events": Path("/sys/fs/cgroup/memory.events").read_text()})
    print(json.dumps({"receipt": str(args.receipt), "exit_code": child.returncode}), flush=True)
    raise SystemExit(child.returncode)


if __name__ == "__main__":
    main()
