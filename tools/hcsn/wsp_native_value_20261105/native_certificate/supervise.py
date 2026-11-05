#!/usr/bin/env python3
# Copyright 2026 TrillionniumFoundation
# SPDX-License-Identifier: Apache-2.0
"""Create-only whole-process wall/CPU/log receipt for one bounded experiment.

Successful child programs must wait for their descendants. RUSAGE_CHILDREN then
includes those waited descendants. Peak RSS is the maximum reported process
RSS, not a sum of simultaneous memory use. Timeout costs may omit an orphaned
unwaited descendant and are explicitly marked incomplete.
"""
import argparse
import datetime
import hashlib
import json
import os
import pathlib
import resource
import signal
import subprocess
import time


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main(args):
    command = args.command[1:] if args.command[:1] == ["--"] else args.command
    if not command or args.timeout < 1 or args.timeout > 7200:
        raise ValueError("one command and a timeout in [1,7200] seconds are required")
    args.output.mkdir(parents=True, exist_ok=False)
    stdout, stderr = args.output / "stdout.log", args.output / "stderr.log"
    started, self_cpu = time.monotonic(), time.process_time()
    before = resource.getrusage(resource.RUSAGE_CHILDREN)
    result = {"schema": "hepta-whole-process-cost-v1", "command": command,
              "started_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
              "timeout_seconds": args.timeout, "timed_out": False,
              "supervisor_sha256": sha(pathlib.Path(__file__)),
              "child_cpu_scope": "direct child plus descendants it waited for",
              "rss_scope": "maximum reported RSS of a waited process, not concurrent aggregate"}
    try:
        with stdout.open("xb") as out, stderr.open("xb") as err:
            process = subprocess.Popen(command, stdout=out, stderr=err, start_new_session=True)
            result["pid"] = process.pid
            try:
                result["exit_code"] = process.wait(timeout=args.timeout)
            except subprocess.TimeoutExpired:
                result["timed_out"] = True
                os.killpg(process.pid, signal.SIGKILL)
                result["exit_code"] = process.wait()
    except BaseException as error:
        result["supervisor_error"] = repr(error)
        raise
    finally:
        after = resource.getrusage(resource.RUSAGE_CHILDREN)
        result.update(
            completed=True,
            wall_seconds=time.monotonic() - started,
            supervisor_self_cpu_seconds=time.process_time() - self_cpu,
            child_user_cpu_seconds=after.ru_utime - before.ru_utime,
            child_system_cpu_seconds=after.ru_stime - before.ru_stime,
            child_cpu_seconds=after.ru_utime + after.ru_stime - before.ru_utime - before.ru_stime,
            maximum_waited_process_rss_kib=after.ru_maxrss,
            cost_scope_complete_if_child_waited_descendants=not result["timed_out"] and "exit_code" in result,
            completed_utc=datetime.datetime.now(datetime.timezone.utc).isoformat())
        result["logs"] = {x.name: {"bytes": x.stat().st_size, "sha256": sha(x)}
                          for x in (stdout, stderr) if x.exists()}
        with (args.output / "PROCESS_RECEIPT.json").open("x") as stream:
            json.dump(result, stream, sort_keys=True, indent=2, allow_nan=False)
            stream.write("\n")
    print(json.dumps(result), flush=True)
    raise SystemExit(0 if result.get("exit_code") == 0 and not result["timed_out"] else 1)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=pathlib.Path, required=True)
    parser.add_argument("--timeout", type=int, default=900)
    parser.add_argument("command", nargs=argparse.REMAINDER)
    main(parser.parse_args())
