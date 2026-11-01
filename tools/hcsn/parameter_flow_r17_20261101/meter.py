"""Linux outer-process CPU receipt includes imports, execution and output writes."""

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import time


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    command = args.command[1:] if args.command[:1] == ["--"] else args.command
    if not command or args.output.exists():
        raise ValueError("New output receipt and child command required")
    start = time.perf_counter()
    stdout, stderr = args.output.with_suffix(".stdout.log"), args.output.with_suffix(".stderr.log")
    with stdout.open("xb") as out, stderr.open("xb") as err:
        child = subprocess.Popen(command, stdout=out, stderr=err)
        _, status, usage = os.wait4(child.pid, 0)
        child.returncode = os.waitstatus_to_exitcode(status)
    result = dict(schema="hcsn-r17-gradient-outer-process-v1", command=command,
                  returncode=child.returncode, cpu_user_seconds=usage.ru_utime,
                  cpu_system_seconds=usage.ru_stime, cpu_seconds=usage.ru_utime + usage.ru_stime,
                  wall_seconds=time.perf_counter() - start, max_rss_kib=usage.ru_maxrss,
                  scope="One complete child process, includes Python startup/import and final output. No GPU/energy/service cost.")
    with args.output.open("x") as stream:
        json.dump(result, stream, indent=2)
        stream.write("\n")
    print(json.dumps(result, indent=2))
    sys.exit(child.returncode)
