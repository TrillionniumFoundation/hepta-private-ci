"""External full-process accounting without changing frozen scientific source.

Run this in its own process. os.wait4 measures the complete child lifetime. On
this Linux host the separate local probe verifies inclusion of waited-for
descendants, so this total must NOT be added to the child's nested CPU totals.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import platform
import time


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--receipt", type=Path, required=True)
    parser.add_argument("--stdout", type=Path, required=True)
    parser.add_argument("--stderr", type=Path, required=True)
    parser.add_argument("--identity", type=Path, action="append", default=[])
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    command = args.command[1:] if args.command[:1] == ["--"] else args.command
    if not command:
        raise ValueError("an explicit child command is required")
    outputs = [args.receipt, args.stdout, args.stderr]
    if len({p.resolve() for p in outputs}) != 3 or any(p.exists() for p in outputs):
        raise ValueError("three distinct, previously absent output paths required")
    for p in outputs:
        p.parent.mkdir(parents=True, exist_ok=True)
    identities = {str(p.resolve()): sha(p) for p in args.identity}
    source_identity = sha(__file__)
    started = datetime.now(timezone.utc).isoformat()
    wall, parent_cpu = time.perf_counter(), time.process_time()
    with args.stdout.open("xb") as stdout, args.stderr.open("xb") as stderr:
        pid = os.fork()
        if pid == 0:
            try:
                os.dup2(stdout.fileno(), 1)
                os.dup2(stderr.fileno(), 2)
                os.execvpe(command[0], command, os.environ.copy())
            except BaseException as error:
                os.write(2, (f"supervisor exec failed: {error}\n").encode())
                os._exit(127)
        waited_pid, status, usage = os.wait4(pid, 0)
    if waited_pid != pid:
        raise AssertionError("wait4 returned an unrelated process")
    code = os.waitstatus_to_exitcode(status)
    receipt = dict(schema="digital-external-wait4-receipt-v1", command=command,
                   child_pid=pid, started_at=started, finished_at=datetime.now(timezone.utc).isoformat(),
                   returncode=code, raw_wait_status=status,
                   wall_seconds=time.perf_counter()-wall,
                   child_user_cpu_seconds=usage.ru_utime, child_system_cpu_seconds=usage.ru_stime,
                   outer_wait4_cpu_seconds=usage.ru_utime+usage.ru_stime,
                   accounting_scope="complete child lifetime; local Linux probe establishes waited descendants included; do not add inner subprocess CPU",
                   supervisor_python_cpu_seconds=time.process_time()-parent_cpu,
                   kernel_maxrss=usage.ru_maxrss, kernel_maxrss_unit="KiB on this recorded Linux host",
                   minor_faults=usage.ru_minflt, major_faults=usage.ru_majflt,
                   voluntary_context_switches=usage.ru_nvcsw, involuntary_context_switches=usage.ru_nivcsw,
                   platform=platform.platform(), python_version=platform.python_version(),
                   supervisor_sha256=source_identity,
                   input_sha256_before=identities,
                   input_sha256_after={str(p.resolve()): sha(p) for p in args.identity},
                   stdout=dict(path=str(args.stdout), bytes=args.stdout.stat().st_size, sha256=sha(args.stdout)),
                   stderr=dict(path=str(args.stderr), bytes=args.stderr.stat().st_size, sha256=sha(args.stderr)))
    with args.receipt.open("x") as stream:
        json.dump(receipt, stream, sort_keys=True, indent=2, allow_nan=False)
        stream.write("\n")
    print(json.dumps({key: receipt[key] for key in ("returncode", "outer_wait4_cpu_seconds", "wall_seconds", "supervisor_sha256")}, sort_keys=True))
    raise SystemExit(code if code >= 0 else 128-code)


if __name__ == "__main__":
    main()
