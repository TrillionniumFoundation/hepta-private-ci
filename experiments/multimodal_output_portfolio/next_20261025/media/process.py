"""Whole-child cost and exit receipts, including imports and final writes."""

import argparse
import json
from pathlib import Path
import resource
import subprocess
import sys
import time


def save(path, value):
    with path.open("x") as stream:
        json.dump(value, stream, indent=2, allow_nan=False)
        stream.write("\n")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("argv", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    command = args.argv[1:] if args.argv[:1] == ["--"] else args.argv
    if not command:
        raise ValueError("Require one explicit child command")
    args.output.mkdir(parents=True, exist_ok=False)
    started = time.perf_counter_ns()
    before = resource.getrusage(resource.RUSAGE_CHILDREN)
    save(args.output / "started.json", {"argv": command, "started_unix_ns": time.time_ns(), "cwd": str(Path.cwd())})
    with (args.output / "stdout.log").open("x") as log:
        process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        for line in process.stdout:
            log.write(line)
            log.flush()
            print(line, end="", flush=True)
        code = process.wait()
    after = resource.getrusage(resource.RUSAGE_CHILDREN)
    receipt = {"returncode": code, "wall_ns": time.perf_counter_ns() - started,
               "user_cpu_seconds": after.ru_utime - before.ru_utime,
               "system_cpu_seconds": after.ru_stime - before.ru_stime,
               "max_rss_kib": after.ru_maxrss, "ended_unix_ns": time.time_ns(),
               "scope": "Whole child and codec subprocess CPU; includes child imports and final writes"}
    save(args.output / "receipt.json", receipt)
    print(json.dumps(receipt), flush=True)
    sys.exit(code if code >= 0 else 128 - code)


if __name__ == "__main__":
    main()
