"""Record an entire invocation, including failures and child-process CPU."""

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import resource
import subprocess
import sys
import time


def write(path, value):
    with path.open("x") as stream:
        json.dump(value, stream, sort_keys=True, indent=2, allow_nan=False)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())


def run(root, label, command):
    output = root / "execution"
    output.mkdir(parents=True, exist_ok=True)
    if not label or any(x not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-" for x in label):
        raise ValueError("Invalid execution label")
    started = {"schema": "hepta.analytic-event.round4.execution.v1", "label": label,
               "started_utc": datetime.now(timezone.utc).isoformat(), "command": command,
               "cwd": str(Path.cwd()), "full_invocation_scope": True,
               "nested_component_times_must_not_be_added": True}
    write(output / (label + "_STARTED.json"), started)
    start = time.perf_counter_ns()
    before = resource.getrusage(resource.RUSAGE_CHILDREN)
    with (output / (label + ".log")).open("xb") as log:
        process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        for chunk in iter(lambda: process.stdout.read1(16384), b""):
            log.write(chunk)
            log.flush()
            sys.stdout.buffer.write(chunk)
            sys.stdout.buffer.flush()
        returncode = process.wait()
    after = resource.getrusage(resource.RUSAGE_CHILDREN)
    result = {**started, "finished_utc": datetime.now(timezone.utc).isoformat(),
              "returncode": returncode, "wall_ns": time.perf_counter_ns() - start,
              "children_user_seconds": after.ru_utime - before.ru_utime,
              "children_system_seconds": after.ru_stime - before.ru_stime,
              "native_energy": None, "financial_cost": None,
              "log": str((output / (label + ".log")).relative_to(root))}
    write(output / (label + "_COMPLETED.json"), result)
    print(json.dumps(result), flush=True)
    return returncode


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--label", required=True)
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    command = args.command[1:] if args.command[:1] == ["--"] else args.command
    if not command:
        parser.error("An invocation is required after --")
    sys.exit(run(args.run_dir.resolve(), args.label, command))
