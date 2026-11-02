"""Memory/CPU probe fixture, explicitly not a scientific model benchmark."""

import argparse
import json
import os
from pathlib import Path
import resource
import subprocess
import sys
import time


def identity():
    raw = Path("/proc/self/stat").read_text()
    prefix, rest = raw.rsplit(") ", 1)
    return {"pid": int(prefix.split(" ", 1)[0]), "start_ticks": int(rest.split()[19]),
            "namespace_pid": os.getpid()}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--role", choices=("root", "child", "grandchild", "short"), default="root")
    parser.add_argument("--orphan", action="store_true")
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    sizes = {"root": 8, "child": 12, "grandchild": 16, "short": 24}
    begin = time.monotonic_ns()
    block = bytearray(sizes[args.role] * 1024 * 1024)
    for i in range(0, len(block), 4096):
        block[i] = (i // 4096) % 251
    own = identity()
    child = None
    short = None
    script = str(Path(__file__).resolve())
    if args.role in ("root", "child"):
        role = "child" if args.role == "root" else "grandchild"
        child = subprocess.Popen([sys.executable, script, "--out", str(args.out), "--role", role])
    if args.role == "root":
        short = subprocess.Popen([sys.executable, script, "--out", str(args.out), "--role", "short"])
    duration = {"root": 0.10 if args.orphan else 0.45, "child": 0.35, "grandchild": 0.50, "short": 0.002}[args.role]
    burn_begin = time.process_time()
    value = 1
    while time.process_time() - burn_begin < duration:
        value = (value * 48271) % 2147483647
    waits = []
    for worker in (child, short):
        if worker is not None and not (args.orphan and args.role == "root"):
            _, status, usage = os.wait4(worker.pid, 0)
            worker.returncode = os.waitstatus_to_exitcode(status)
            waits.append({"namespace_pid": worker.pid, "cpu_seconds": usage.ru_utime + usage.ru_stime})
    own_usage = resource.getrusage(resource.RUSAGE_SELF)
    row = {"role": args.role, "identity": own, "allocated_bytes": len(block),
           "begin_ns": begin, "end_ns": time.monotonic_ns(), "self_cpu_seconds":
               own_usage.ru_utime + own_usage.ru_stime, "waited_children": waits,
           "checksum": value, "fixture_not_model": True}
    (args.out / (args.role + ".json")).write_text(json.dumps(row, indent=2) + "\n")


if __name__ == "__main__":
    main()
