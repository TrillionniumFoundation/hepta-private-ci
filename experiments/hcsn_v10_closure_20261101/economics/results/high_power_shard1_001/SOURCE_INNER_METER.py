"""Linux task CPU envelope and namespace-aware sampled family RSS/PSS.

The proc mount can expose host PIDs while getpid returns namespace PIDs. Tree
traversal therefore stays in the proc mount's observed PID space. Samples are
explicitly non-atomic and do not qualify a continuous family memory peak.
"""

import argparse
import ctypes
import hashlib
import json
import math
import os
from pathlib import Path
import resource
import signal
import subprocess
import sys
import time


def proc_stat(path):
    raw = path.read_text()
    prefix, rest = raw.rsplit(") ", 1)
    values = rest.split()
    return {"pid": int(prefix.split(" ", 1)[0]), "state": values[0],
            "ppid": int(values[1]), "start_ticks": int(values[19])}


def proc_snapshot(root):
    """Read a best-effort global process table, then select root descendants."""
    table = {}
    races = 0
    unreadable = 0
    began = time.monotonic_ns()
    for path in Path("/proc").glob("[0-9]*/stat"):
        try:
            item = proc_stat(path)
            table[item["pid"]] = item
        except (FileNotFoundError, ProcessLookupError):
            races += 1
        except (OSError, ValueError, IndexError):
            unreadable += 1
    current = table.get(root["pid"])
    if current is None or current["start_ticks"] != root["start_ticks"]:
        raise RuntimeError("Observer identity absent or reused in proc snapshot")
    chosen = {root["pid"]}
    while True:
        expanded = chosen | {pid for pid, item in table.items() if item["ppid"] in chosen}
        if expanded == chosen:
            break
        chosen = expanded
    members = []
    for pid in sorted(chosen):
        item = dict(table[pid])
        item["read_begin_ns"] = time.monotonic_ns()
        try:
            before = proc_stat(Path(f"/proc/{pid}/stat"))
            if before["start_ticks"] != item["start_ticks"]:
                raise RuntimeError("PID reused before memory read")
            status = Path(f"/proc/{pid}/status").read_text()
            values = {}
            for line in Path(f"/proc/{pid}/smaps_rollup").read_text().splitlines():
                if line.startswith(("Rss:", "Pss:")):
                    key, number, unit = line.split()
                    if unit != "kB":
                        raise RuntimeError("Unknown proc memory unit")
                    values[key[:-1].lower() + "_bytes"] = int(number) * 1024
            after = proc_stat(Path(f"/proc/{pid}/stat"))
            if after["start_ticks"] != before["start_ticks"]:
                raise RuntimeError("PID reused during memory read")
            if "rss_bytes" not in values or "pss_bytes" not in values:
                raise RuntimeError("smaps_rollup did not provide both RSS and PSS")
            item.update(values)
            item["namespace_pids"] = next(
                ([int(x) for x in line.split()[1:]] for line in status.splitlines()
                 if line.startswith("NSpid:")), None)
            item["available"] = True
        except (OSError, RuntimeError, ValueError) as error:
            item.update(available=False, reason=str(error), rss_bytes=None, pss_bytes=None)
        item["read_end_ns"] = time.monotonic_ns()
        members.append(item)
    return {"begin_ns": began, "end_ns": time.monotonic_ns(), "members": members,
            "proc_disappearance_races": races, "global_unreadable_entries": unreadable,
            "all_enumerated_members_read": all(x["available"] for x in members),
            "observed_rss_sum_bytes": sum(x["rss_bytes"] or 0 for x in members),
            "observed_pss_sum_bytes": sum(x["pss_bytes"] or 0 for x in members)}


def capabilities():
    cgroup = Path("/sys/fs/cgroup")
    cgroup_result = {"available": False, "attributable_memory_peak_bytes": None}
    probe = cgroup / ("hcsn-v9-capability-" + str(os.getpid()))
    try:
        probe.mkdir()
        probe.rmdir()
        cgroup_result.update(available=True, reason="Writable child cgroup, not used by this sampler")
    except OSError as error:
        cgroup_result["reason"] = str(error)
    counters = {}
    for directory in ("/sys/class/powercap", "/sys/class/hwmon", "/sys/class/drm"):
        path = Path(directory)
        counters[directory] = {"exists": path.exists(), "energy_files":
                              sorted(str(x) for x in path.glob("**/energy*_input")) if path.exists() else []}
    return {"cgroup": cgroup_result, "energy": {"joules": None, "attributable": False,
            "counters": counters, "reason": "No configured attributable device-energy counter"}}


def subreaper():
    libc = ctypes.CDLL(None, use_errno=True)
    if libc.prctl(36, 1, 0, 0, 0):
        raise OSError(ctypes.get_errno(), "PR_SET_CHILD_SUBREAPER failed")
    value = ctypes.c_int()
    if libc.prctl(37, ctypes.byref(value), 0, 0, 0) or value.value != 1:
        raise RuntimeError("Could not confirm child subreaper")


def measured_run(command, out, interval=0.02, timeout=120.0):
    if not command or not all(isinstance(x, str) and x for x in command):
        raise ValueError("Nonempty command argument vector required")
    if not math.isfinite(interval) or interval <= 0 or not math.isfinite(timeout) or timeout <= 0:
        raise ValueError("Finite positive interval and timeout required")
    out = Path(out).resolve()
    out.mkdir(parents=True, exist_ok=False)
    subreaper()
    capability = capabilities()
    root = proc_stat(Path("/proc/self/stat"))
    root["getpid"] = os.getpid()
    source_sha = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    began = time.monotonic_ns()
    self_before = resource.getrusage(resource.RUSAGE_SELF)
    waits, errors, seen, totals = [], [], {}, []
    timeout_sent = False
    with (out / "stdout.log").open("wb") as stdout, (out / "stderr.log").open("wb") as stderr, \
            (out / "MEMORY_SAMPLES.jsonl").open("w") as samples:
        worker = subprocess.Popen(command, stdout=stdout, stderr=stderr, start_new_session=True)
        while True:
            try:
                sample = proc_snapshot(root)
                samples.write(json.dumps(sample, allow_nan=False) + "\n")
                samples.flush()
                totals.append((sample["observed_rss_sum_bytes"], sample["observed_pss_sum_bytes"],
                               sample["all_enumerated_members_read"]))
                for member in sample["members"]:
                    key = str(member["pid"]) + ":" + str(member["start_ticks"])
                    row = seen.setdefault(key, {"identity": {k: member[k] for k in ("pid", "start_ticks")},
                                               "sample_count": 0, "available_samples": 0,
                                               "observed_ppids": [], "namespace_pids": None})
                    row["sample_count"] += 1
                    row["available_samples"] += int(member["available"])
                    if member["ppid"] not in row["observed_ppids"]:
                        row["observed_ppids"].append(member["ppid"])
                    if member.get("namespace_pids"):
                        row["namespace_pids"] = member["namespace_pids"]
            except RuntimeError as error:
                errors.append(str(error))
            all_done = False
            while True:
                try:
                    pid, status, usage = os.wait4(-1, os.WNOHANG)
                except ChildProcessError:
                    all_done = True
                    break
                if pid == 0:
                    break
                code = os.waitstatus_to_exitcode(status)
                waits.append({"namespace_pid": pid, "direct_worker": pid == worker.pid,
                              "exit_code": code, "user_cpu_seconds": usage.ru_utime,
                              "system_cpu_seconds": usage.ru_stime,
                              "cpu_seconds": usage.ru_utime + usage.ru_stime,
                              "largest_process_hwm_bytes": usage.ru_maxrss * 1024})
                if pid == worker.pid:
                    worker.returncode = code
            if all_done:
                break
            if (time.monotonic_ns() - began) / 1e9 > timeout and not timeout_sent:
                # Dedicated process group only. A child can escape it; that case is not qualified.
                timeout_sent = True
                try:
                    os.killpg(worker.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
            if timeout_sent and (time.monotonic_ns() - began) / 1e9 > timeout + 5:
                errors.append("Waitable descendants remain after bounded timeout cleanup")
                break
            time.sleep(interval)
    ended = time.monotonic_ns()
    self_after = resource.getrusage(resource.RUSAGE_SELF)
    monitor_cpu = ((self_after.ru_utime + self_after.ru_stime)
                   - (self_before.ru_utime + self_before.ru_stime))
    task_cpu = sum(x["cpu_seconds"] for x in waits)
    receipt = {"schema": "hcsn-v9-process-family-cost.v1", "command": command,
               "source_sha256": source_sha, "observer_identity": root,
               "boundary_begin_ns": began, "boundary_end_ns": ended,
               "elapsed_seconds": (ended - began) / 1e9, "sample_interval_seconds": interval,
               "task_cpu_seconds": task_cpu, "measurement_cpu_seconds": monitor_cpu,
               "enclosing_observed_cpu_seconds": task_cpu + monitor_cpu,
               "cpu_scope": "Disjoint wait4 child subtrees, adopted children included; observer CPU delta added once",
               "cpu_complete_for_ordinary_waitable_family": all_done and not errors,
               "wait4_subtrees": waits, "task_success": worker.returncode == 0 and all_done
                   and all(x["exit_code"] == 0 for x in waits) and not timeout_sent and not errors,
               "capabilities": capability, "errors": errors,
               "memory": {"status": "sampled_partial", "samples": len(totals),
                          "observed_peak_nonatomic_rss_sum_bytes": max((x[0] for x in totals), default=None),
                          "observed_peak_nonatomic_pss_sum_bytes": max((x[1] for x in totals), default=None),
                          "samples_with_all_enumerated_members_read": sum(x[2] for x in totals),
                          "continuous_complete_family_peak_bytes": None, "complete": False,
                          "seen_processes": list(seen.values()),
                          "limits": ["Enumeration and smaps reads are non-atomic",
                                     "Processes born and exited between samples may be absent",
                                     "RSS double-counts shared pages; PSS apportions pages shared outside the family",
                                     "Observed sums are not a simultaneous physical memory measurement"]},
               "historical_preparation_cpu_seconds": None, "economic_advantage_established": False}
    receipt["sample_sha256"] = hashlib.sha256((out / "MEMORY_SAMPLES.jsonl").read_bytes()).hexdigest()
    (out / "RECEIPT.json").write_text(json.dumps(receipt, indent=2, allow_nan=False) + "\n")
    return receipt


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--interval", type=float, default=0.02)
    parser.add_argument("--timeout", type=float, default=120)
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    command = args.command[1:] if args.command[:1] == ["--"] else args.command
    result = measured_run(command, args.out, args.interval, args.timeout)
    print(json.dumps({"out": str(args.out), "task_success": result["task_success"],
                      "task_cpu_seconds": result["task_cpu_seconds"],
                      "seen_processes": len(result["memory"]["seen_processes"])}))
    return 0 if result["task_success"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
