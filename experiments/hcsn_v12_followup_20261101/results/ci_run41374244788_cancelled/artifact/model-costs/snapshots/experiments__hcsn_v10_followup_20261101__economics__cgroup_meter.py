"""Linux delegated-cgroup task charge meter; trusted fork/exec workload only.

The meter stays outside a fresh task cgroup. Its gated child joins before the
payload exec; all ordinary descendants inherit membership. memory.peak is the
hierarchical memory-charge highwater, NOT a continuous RSS sum or unique memory.
Shared/existing-page charges can belong elsewhere. No energy is inferred.
"""

import argparse
import ctypes
import hashlib
import json
import math
import os
from pathlib import Path
import signal
import subprocess
import sys
import time
import uuid


def fields(raw):
    result = {}
    for line in raw.splitlines():
        parts = line.split()
        if len(parts) != 2 or parts[0] in result:
            raise ValueError("Malformed/duplicate kernel counter")
        result[parts[0]] = unsigned(parts[1])
    return result


def unsigned(raw):
    token = raw.strip()
    if not token or not token.isascii() or not token.isdecimal():
        raise ValueError("A nonnegative integer kernel counter is required")
    return int(token)


def on_cgroup2(base):
    candidates = []
    for order, line in enumerate(Path("/proc/self/mountinfo").read_text().splitlines()):
        left, right = line.split(" - ", 1)
        token = left.split()[4]
        for code, value in (("\\040", " "), ("\\011", "\t"), ("\\012", "\n"), ("\\134", "\\")):
            token = token.replace(code, value)
        mount = Path(token)
        if base == mount or mount in base.parents:
            candidates.append((len(mount.parts), order, right.split()[0]))
    return bool(candidates) and max(candidates)[2] == "cgroup2"


def gate(fd, command):
    """No payload runs until the owning parent sends exactly one release byte."""
    try:
        token = os.read(fd, 1)
    finally:
        os.close(fd)
    if token != b"R":
        return 125
    try:
        os.execvp(command[0], command)
    except OSError as error:
        print(f"payload exec failed: {error}", file=sys.stderr)
        return 127


def subreaper():
    library = ctypes.CDLL(None, use_errno=True)
    value = ctypes.c_int()
    if library.prctl(36, 1, 0, 0, 0) or library.prctl(37, ctypes.byref(value), 0, 0, 0) or value.value != 1:
        raise OSError(ctypes.get_errno(), "Linux subreaper was not confirmed")


def run(command, out, base, timeout):
    if not command or any(not isinstance(x, str) or not x for x in command):
        raise ValueError("Explicit nonempty argument-vector payload is required")
    if not math.isfinite(timeout) or timeout <= 0:
        raise ValueError("Positive finite timeout required")
    out.mkdir(parents=True, exist_ok=False)
    source = Path(__file__).resolve()
    began = time.monotonic_ns()
    record = {
        "schema": "hcsn-v10-delegated-cgroup.v1", "command": command,
        "source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
        "status": "UNAVAILABLE", "payload_released": False,
        "measurement_valid": False, "cleanup_verified": False,
        "delegated_parent": str(base), "group_created": False,
        "cgroup_memory_charge_peak_bytes": None, "cgroup_cpu_usage_seconds": None,
        "complete_process_family_rss_peak_bytes": None, "device_energy_joules": None,
        "task_success": False, "all_group_tasks_exited": False,
        "errors": [], "waited_subtrees": [], "scope": __doc__,
        "outside_charge_scope": "Parent meter; pre-join gate bootstrap; pages charged elsewhere; deployment preparation/training/energy.",
        "threat_model": "Trusted task cannot migrate out or admit unrelated processes. No malicious escape qualification.",
    }
    group, child, release = None, None, None
    try:
        base = base.resolve(strict=True)
        if not on_cgroup2(base):
            raise ValueError("Delegated parent is not on a kernel cgroup2 mount")
        group = base / ("hcsn-task-" + uuid.uuid4().hex)
        group.mkdir(mode=0o700)
        record["group_created"] = True
        record["group_path"] = str(group)
        record["group_inode"] = group.stat().st_ino
        required = ("memory.peak", "memory.current", "cpu.stat", "cgroup.procs", "cgroup.events", "cgroup.kill")
        if not all((group / name).is_file() for name in required):
            raise ValueError("Delegation lacks required memory/CPU/events/kill files; do not enable controllers implicitly")
        before_cpu = fields((group / "cpu.stat").read_text())["usage_usec"]
        if ((group / "cgroup.procs").read_text().strip()
                or fields((group / "cgroup.events").read_text())["populated"] != 0
                or unsigned((group / "memory.peak").read_text()) != 0 or before_cpu != 0):
            raise ValueError("Fresh task group was not empty with zero charge counters")
        (group / "cgroup.kill").write_text("1")  # Empty owned group: verify cleanup authority before admission.
        record["empty_group_kill_checked_before_admission"] = True
        subreaper()
        read_fd, release = os.pipe()
        try:
            with (out / "stdout.log").open("xb") as stdout, (out / "stderr.log").open("xb") as stderr:
                child = subprocess.Popen(
                    [sys.executable, str(source), "--gate-fd", str(read_fd), "--", *command],
                    pass_fds=(read_fd,), stdout=stdout, stderr=stderr,
                )
        finally:
            os.close(read_fd)
        # Unreaped direct-child identity cannot be reused before this admission.
        (group / "cgroup.procs").write_text(str(child.pid))
        if str(child.pid) not in (group / "cgroup.procs").read_text().split():
            raise ValueError("Kernel did not confirm direct-child task-group membership")
        record["root_pid"] = child.pid
        record["root_membership_confirmed_before_release"] = True
        record["release_monotonic_ns"] = time.monotonic_ns()
        os.write(release, b"R")
        os.close(release)
        release = None
        record["payload_released"] = True
        deadline, cleanup_deadline = time.monotonic() + timeout, None
        while True:
            now = time.monotonic()
            if now >= deadline and cleanup_deadline is None:
                record["timed_out"] = True
                (group / "cgroup.kill").write_text("1")
                cleanup_deadline = now + 3.0
            no_children = False
            while True:
                try:
                    pid, status, usage = os.wait4(-1, os.WNOHANG)
                except ChildProcessError:
                    no_children = True
                    break
                if pid == 0:
                    break
                code = os.waitstatus_to_exitcode(status)
                record["waited_subtrees"].append({
                    "pid": pid, "exit_code": code,
                    "diagnostic_wait4_cpu_seconds": usage.ru_utime + usage.ru_stime,
                    "diagnostic_largest_single_process_rss_bytes": usage.ru_maxrss * 1024,
                })
                if pid == child.pid:
                    child.returncode = code
                    record["root_exit_code"] = code
            populated = fields((group / "cgroup.events").read_text())["populated"]
            if not populated and no_children:
                record["all_group_tasks_exited"] = True
                break
            if cleanup_deadline is not None and now > cleanup_deadline:
                raise TimeoutError("Killed task group did not completely drain within cleanup allowance")
            time.sleep(0.005)
        peak = unsigned((group / "memory.peak").read_text())
        cpu = fields((group / "cpu.stat").read_text())
        current = unsigned((group / "memory.current").read_text())
        if peak < current or cpu["usage_usec"] < before_cpu:
            raise ValueError("Kernel cumulative counters are inconsistent")
        record.update({
            "status": "MEASURED", "measurement_valid": True, "cgroup_memory_charge_peak_bytes": peak,
            "cgroup_memory_current_at_exit_bytes": current, "cgroup_cpu_stat_at_exit": cpu,
            "cgroup_cpu_usage_seconds": (cpu["usage_usec"] - before_cpu) / 1e6,
            "task_success": record.get("root_exit_code") == 0 and not record.get("timed_out", False)
                            and all(x["exit_code"] == 0 for x in record["waited_subtrees"]),
        })
    except (OSError, ValueError, KeyError) as error:
        record["errors"].append({"type": type(error).__name__, "errno": getattr(error, "errno", None), "message": str(error)})
        if record["payload_released"]:
            record["status"] = "INCOMPLETE"
    finally:
        if release is not None:
            os.close(release)  # Fail closed: gate exits without payload exec.
        if record["payload_released"] and not record["all_group_tasks_exited"] and group is not None:
            try:
                (group / "cgroup.kill").write_text("1")
                drain_deadline = time.monotonic() + 3.0
                while time.monotonic() < drain_deadline:
                    try:
                        pid, status, _ = os.wait4(-1, os.WNOHANG)
                    except ChildProcessError:
                        if fields((group / "cgroup.events").read_text())["populated"] == 0:
                            break
                    else:
                        if child is not None and pid == child.pid:
                            child.returncode = os.waitstatus_to_exitcode(status)
                    time.sleep(0.005)
            except (OSError, ValueError, KeyError) as error:
                record["errors"].append({"descendant_cleanup_error": str(error)})
        if child is not None and child.returncode is None:
            # Membership failures occur while the root is gated. Otherwise group kill
            # covers ordinary descendants; never report cleanup as measurement success.
            try:
                os.kill(child.pid, signal.SIGKILL)
                child.wait(timeout=3)
            except (OSError, subprocess.TimeoutExpired) as error:
                record["errors"].append({"cleanup_error": str(error)})
        if group is not None and record["group_created"]:
            try:
                if group.stat().st_ino != record["group_inode"]:
                    raise ValueError("Owned cgroup identity changed before cleanup")
                record["populated_before_removal"] = fields((group / "cgroup.events").read_text())["populated"]
                group.rmdir()
                record["group_absent_after_removal"] = not group.exists()
                record["cleanup_verified"] = record["populated_before_removal"] == 0 and record["group_absent_after_removal"]
            except (OSError, ValueError, KeyError) as error:
                record["errors"].append({"group_cleanup_error": str(error)})
        if not record["cleanup_verified"]:
            record["task_success"] = False
        record["meter_wall_seconds"] = (time.monotonic_ns() - began) / 1e9
        record["source_unchanged"] = record["source_sha256"] == hashlib.sha256(source.read_bytes()).hexdigest()
        (out / "RECEIPT.json").write_text(json.dumps(record, indent=2) + "\n")
    return record


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--gate-fd", type=int)
    parser.add_argument("--base", type=Path)
    parser.add_argument("--out", type=Path)
    parser.add_argument("--timeout", type=float, default=60.0)
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    command = args.command[1:] if args.command[:1] == ["--"] else args.command
    if args.gate_fd is not None:
        return gate(args.gate_fd, command)
    if args.base is None or args.out is None:
        parser.error("--base and --out required; base must be an explicitly delegated cgroup")
    result = run(command, args.out, args.base, args.timeout)
    print(json.dumps({"status": result["status"], "task_success": result["task_success"]}))
    return 0 if result["task_success"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
