"""Dedicated cgroup-v2 memory.peak; probe is read-only unless 'run' is explicit.

Peak is the kernel's cgroup memory charge (including descendants/kernel/cache),
not RSS/PSS or a sum of sampled process peaks. No host controller is modified.
"""

import argparse
import ctypes
import json
import math
import os
from pathlib import Path
import signal
import subprocess
import sys
import time
import uuid


def read(path):
    return path.read_text().strip()


def populated(group):
    return dict(line.split() for line in read(group/"cgroup.events").splitlines())["populated"] == "1"


def probe(root):
    return {"schema": "hcsn-v10-cgroup-capability.v1", "read_only": True,
        "root": str(root), "unified": (root/"cgroup.controllers").is_file(),
        "controllers": read(root/"cgroup.controllers") if (root/"cgroup.controllers").exists() else None,
        "subtree_control": read(root/"cgroup.subtree_control") if (root/"cgroup.subtree_control").exists() else None,
        "creation_attempted": False, "exact_family_memory_peak_bytes": None}


def run(args):
    args.out.mkdir(parents=True, exist_ok=False)
    record = {"schema": "hcsn-v10-private-cgroup-memory.v1", "status": "FAIL",
        "command": args.command, "source_commit": os.environ.get("HCSN_SOURCE_SHA"),
        "memory_peak_bytes": None, "scope": "dedicated cgroup v2 memory.peak: task plus descendants, kernel memory and charged page cache; not RSS",
        "device_energy_joules": None, "capability": probe(args.root), "gated_before_exec": False,
        "cleanup_own_group_only": True, "source_interpreter": sys.executable}
    group, child, root_status, released = None, None, None, False
    started = time.monotonic()
    try:
        if not args.command or args.uid <= 0 or args.gid < 0:
            raise RuntimeError("Explicit command and non-root task uid/gid required")
        if not math.isfinite(args.timeout) or args.timeout <= 0:
            raise RuntimeError("Finite positive task timeout required")
        if "memory" not in read(args.root/"cgroup.subtree_control").split():
            raise RuntimeError("Memory controller not already enabled at selected parent; host controls unchanged")
        group = args.root/("codex-hcsn-v10-"+str(os.getpid())+"-"+uuid.uuid4().hex)
        group.mkdir()
        for name in ("memory.peak", "memory.max", "cgroup.procs", "cgroup.events", "cgroup.kill"):
            if not (group/name).exists():
                raise RuntimeError("Required private cgroup interface missing: "+name)
        (group/"memory.max").write_text(str(1024**3))
        record.update(cgroup=str(group), memory_limit_bytes=1024**3, initial_peak_bytes=int(read(group/"memory.peak")))
        gate_read, gate_write = os.pipe()
        with (args.out/"stdout.log").open("wb") as stdout, (args.out/"stderr.log").open("wb") as stderr:
            child = os.fork()
            if child == 0:
                try:
                    os.close(gate_write)
                    if os.read(gate_read, 1) != b"G":
                        os._exit(125)
                    os.close(gate_read)
                    os.dup2(stdout.fileno(), 1)
                    os.dup2(stderr.fileno(), 2)
                    libc = ctypes.CDLL(None, use_errno=True)
                    if libc.prctl(38, 1, 0, 0, 0) != 0:  # PR_SET_NO_NEW_PRIVS.
                        raise RuntimeError("Could not prohibit privilege escalation")
                    if os.geteuid() == 0:
                        os.setgroups([])
                        os.setgid(args.gid)
                        os.setuid(args.uid)
                    elif (os.geteuid(), os.getegid()) != (args.uid, args.gid):
                        raise RuntimeError("Task identity differs from delegated identity")
                    os.execvp(args.command[0], args.command)
                except BaseException as error:
                    os.write(2, (repr(error)+"\n").encode())
                    os._exit(126)
            os.close(gate_read)
            try:
                (group/"cgroup.procs").write_text(str(child))
                if str(child) not in read(group/"cgroup.procs").split():
                    raise RuntimeError("Child membership not observed before execution")
                os.write(gate_write, b"G")
                released = True
                record["gated_before_exec"] = True
            finally:
                os.close(gate_write)
            deadline = time.monotonic()+args.timeout
            while True:
                if root_status is None:
                    waited, status = os.waitpid(child, os.WNOHANG)
                    if waited:
                        root_status = status
                if root_status is not None and not populated(group):
                    break
                if time.monotonic() > deadline:
                    raise TimeoutError("Private process family exceeded timeout")
                time.sleep(.01)
        record.update(memory_peak_bytes=int(read(group/"memory.peak")),
            final_memory_current_bytes=int(read(group/"memory.current")),
            memory_events=read(group/"memory.events"), family_empty_after_exit=not populated(group),
            command_exit_code=os.waitstatus_to_exitcode(root_status))
        events = dict(line.split() for line in record["memory_events"].splitlines())
        if int(events.get("oom_kill", "0")) or int(events.get("oom_group_kill", "0")):
            raise RuntimeError("Kernel recorded an OOM-killed member of the measured family")
        if record["command_exit_code"] != 0 or record["memory_peak_bytes"] <= 0:
            raise RuntimeError("Task failed or kernel peak was not positive")
        record["status"] = "PASS"
    except BaseException as error:
        record["error"] = f"{type(error).__name__}: {error}"
    finally:
        if child is not None and not released:
            try:
                os.kill(child, signal.SIGKILL)  # Unreleased/unreaped own gated child.
            except ProcessLookupError:
                pass
        if group is not None and group.exists():
            try:
                if populated(group):
                    (group/"cgroup.kill").write_text("1")
                if child is not None and root_status is None:
                    try:
                        os.kill(child, signal.SIGKILL)  # Own unreaped child only.
                    except ProcessLookupError:
                        pass
                cleanup_end = time.monotonic()+3
                while True:
                    if child is not None and root_status is None:
                        waited, status = os.waitpid(child, os.WNOHANG)
                        if waited:
                            root_status = status
                    if not populated(group) and (child is None or root_status is not None):
                        break
                    if time.monotonic() >= cleanup_end:
                        raise TimeoutError("Owned family cleanup exceeded three seconds")
                    time.sleep(.01)
                if (group/"memory.peak").exists():
                    record["memory_peak_bytes"] = int(read(group/"memory.peak"))
                group.rmdir()
                record["own_group_removed"] = True
            except BaseException as error:
                record.update(status="FAIL", cleanup_error=repr(error), own_group_removed=False)
        record["wall_seconds"] = time.monotonic()-started
        (args.out/"RECEIPT.json").write_text(json.dumps(record, indent=2)+"\n")
        print(json.dumps(record), flush=True)
    return 0 if record["status"] == "PASS" else 1


def fixture():
    memory = bytearray(16*1024**2)
    for index in range(0, len(memory), 4096):
        memory[index] = 1
    script = "import time; a=bytearray(32*1024**2); a[::4096]=b'x'*len(a[::4096]); time.sleep(.15)"
    subprocess.run([sys.executable, "-c", script], check=True)
    print(json.dumps({"simultaneous_touched_payload_bytes": 48*1024**2}))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("probe", "run", "fixture"), nargs="?", default="probe")
    parser.add_argument("--root", type=Path, default=Path("/sys/fs/cgroup"))
    parser.add_argument("--out", type=Path)
    parser.add_argument("--uid", type=int, default=-1)
    parser.add_argument("--gid", type=int, default=-1)
    parser.add_argument("--timeout", type=float, default=180)
    args, args.command = parser.parse_known_args()
    if args.command[:1] == ["--"]:
        args.command = args.command[1:]
    if args.mode == "fixture":
        fixture()
        return 0
    if args.mode == "run":
        if args.out is None:
            parser.error("run requires --out")
        return run(args)
    result = probe(args.root)
    if args.out:
        args.out.mkdir(parents=True, exist_ok=False)
        (args.out/"CAPABILITY.json").write_text(json.dumps(result, indent=2)+"\n")
    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
