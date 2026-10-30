"""Conservative cgroup accounting with verified namespace-to-host PID mapping."""

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import time

from .train_equivalence import GIB, sha, write, utc


def measurement():
    directory = Path("/sys/fs/cgroup")
    parse = lambda name: {key: int(value) for key, value in
        (line.split() for line in (directory / name).read_text().splitlines())}
    stat, events = parse("memory.stat"), parse("memory.events")
    maximum = int((directory / "memory.max").read_text())
    current = int((directory / "memory.current").read_text())
    components = sum(stat.get(name, 0) for name in
        ("kernel_stack", "pagetables", "sec_pagetables", "percpu", "vmalloc", "slab_unreclaimable"))
    kernel = max(0, stat.get("kernel", 0) - stat.get("slab_reclaimable", 0), components)
    component_estimate = stat.get("anon", 0) + kernel + sum(stat.get(name, 0) for name in
        ("sock", "shmem", "unevictable", "file_dirty", "file_writeback"))
    current_minus_cache = max(0, current - stat.get("file", 0) - stat.get("slab_reclaimable", 0))
    nonreclaimable = max(component_estimate, current_minus_cache)
    return dict(utc=utc(), maximum_bytes=maximum, current_bytes=current, stat=stat, events=events,
        kernel_nonreclaimable_bytes=kernel, estimated_nonreclaimable_bytes=nonreclaimable,
        estimated_headroom_bytes=maximum - nonreclaimable,
        note="Sequential kernel observations; conservative estimate, not an atomic or future-memory guarantee")


def status(path):
    return {key: value.strip() for key, value in
            (line.split(":", 1) for line in Path(path).read_text().splitlines() if ":" in line)}


def own_host_pid():
    own = status("/proc/self/status")
    if not own.get("NSpid") or int(own["NSpid"].split()[-1]) != os.getpid():
        raise RuntimeError("Cannot verify own PID namespace identity")
    return int(own["Pid"])


def anonymous_credit(namespace_pid, parent_host_pid):
    """Credit only a unique direct child with verified host PPid and NSpid.

    /proc is mounted in the host namespace in this environment, whereas
    Popen.pid belongs to the task namespace. Direct /proc/Popen.pid lookup
    could therefore read an unrelated host process. Any ambiguity gets zero
    credit and consequently retains the worker's full future-memory reserve.
    """
    matches = []
    for folder in Path("/proc").glob("[0-9]*"):
        try:
            item = status(folder / "status")
            if int(item["PPid"]) != parent_host_pid or not item.get("NSpid"):
                continue
            namespace_ids = [int(value) for value in item["NSpid"].split()]
            if namespace_ids[-1] != namespace_pid:
                continue
            host_pid = int(item["Pid"])
            if host_pid != int(folder.name) or namespace_ids[0] != host_pid:
                continue
            matches.append(dict(namespace_pid=namespace_pid, host_pid=host_pid,
                parent_host_pid=parent_host_pid, namespace_ids=namespace_ids,
                credited_anon_bytes=int(item.get("RssAnon", "0 kB").split()[0]) * 1024,
                observed_rss_bytes=int(item.get("VmRSS", "0 kB").split()[0]) * 1024))
        except (FileNotFoundError, ProcessLookupError, PermissionError, KeyError, ValueError):
            continue
    if len(matches) != 1:
        return dict(namespace_pid=namespace_pid, parent_host_pid=parent_host_pid,
                    verified=False, credited_anon_bytes=0, matching_processes=len(matches),
                    reason="no unique verified direct-child host PPid/NSpid match")
    return dict(matches[0], verified=True)


def decision(resources, credits, desired_workers, budget, shared_reserve, registered_limit):
    pending = [max(0, budget - row["credited_anon_bytes"]) for row in credits]
    limit = min(resources["maximum_bytes"], registered_limit)
    after_future_and_new = limit - resources["estimated_nonreclaimable_bytes"] - sum(pending) - budget
    return dict(allowed=len(credits) < desired_workers and after_future_and_new >= shared_reserve,
        own_active_workers=len(credits), desired_workers=desired_workers,
        effective_memory_limit_bytes=limit, own_worker_credits=credits,
        own_pending_reservations_bytes=pending, new_worker_budget_bytes=budget,
        remaining_shared_reserve_bytes=after_future_and_new,
        required_shared_reserve_bytes=shared_reserve)


def probe(output):
    output.mkdir(parents=True, exist_ok=False)
    source = Path(__file__)
    registration = dict(schema="hcsn-risk-resource-namespace-probe.v1", registered_utc=utc(),
        source_sha256=sha(source), allocation_bytes=64 * 1024 ** 2,
        requirement="unique host PPid plus NSpid[-1] matches real Popen child; credit >= allocated bytes; unknown child receives zero credit",
        no_unrelated_process_modified=True, shared_reserve_bytes=2 * GIB, worker_budget_bytes=int(1.25 * GIB))
    write(output / "REGISTRATION.json", registration)
    (output / "resource_accounting_snapshot.py").write_bytes(source.read_bytes())
    child_source = (
        "import json,os,sys\n"
        "allocation=bytearray(64*1024**2)\n"
        "for index in range(0,len(allocation),4096): allocation[index]=1\n"
        "print(json.dumps({'namespace_pid':os.getpid(),'allocated_bytes':len(allocation)}),flush=True)\n"
        "sys.stdin.readline()\n")
    (output / "allocation_child.py").write_text(child_source)
    before, started = measurement(), time.perf_counter()
    process = subprocess.Popen([sys.executable, str(output / "allocation_child.py")],
                               stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    error, child, credit, unknown, checks = None, None, None, None, {}
    try:
        child = json.loads(process.stdout.readline())
        host_parent = own_host_pid()
        credit = anonymous_credit(process.pid, host_parent)
        unknown = anonymous_credit(2 ** 30, host_parent)
        checks["reported_namespace_pid_matches_popen"] = child["namespace_pid"] == process.pid
        checks["host_ppid_and_namespace_child_verified"] = credit["verified"]
        checks["anonymous_credit_covers_touched_allocation"] = credit["credited_anon_bytes"] >= child["allocated_bytes"]
        checks["unknown_child_credit_is_zero"] = not unknown["verified"] and unknown["credited_anon_bytes"] == 0
        budget, reserve = registration["worker_budget_bytes"], registration["shared_reserve_bytes"]
        fixture = dict(maximum_bytes=8 * GIB, estimated_nonreclaimable_bytes=8 * GIB - budget - reserve)
        checks["exact_budget_plus_reserve_allowed"] = decision(fixture, [], 2, budget, reserve, 8 * GIB)["allowed"]
        fixture["estimated_nonreclaimable_bytes"] += 1
        checks["one_byte_short_rejected"] = not decision(fixture, [], 2, budget, reserve, 8 * GIB)["allowed"]
        fixture["estimated_nonreclaimable_bytes"] -= 1
        checks["unknown_active_worker_full_budget_reserved"] = not decision(fixture, [unknown], 2, budget, reserve, 8 * GIB)["allowed"]
        checks["zero_workers_pauses"] = not decision(fixture, [], 0, budget, reserve, 8 * GIB)["allowed"]
    except Exception as caught:
        error = dict(type=type(caught).__name__, message=str(caught))
    finally:
        try:
            process.stdin.write("release\n")
            process.stdin.flush()
        except BrokenPipeError:
            pass
        process.stdin.close()
        got, wait_status, usage = os.wait4(process.pid, 0)
        code = os.waitstatus_to_exitcode(wait_status)
        process.returncode = code
        stderr = process.stderr.read()
        process.stdout.close()
        process.stderr.close()
    passed = error is None and code == 0 and bool(checks) and all(checks.values())
    result = dict(schema="hcsn-risk-resource-namespace-probe-results.v1", passed=passed, checks=checks,
        error=error, child=child, verified_credit=credit, unknown_credit=unknown,
        child_returncode=code, child_user_cpu_seconds=usage.ru_utime,
        child_system_cpu_seconds=usage.ru_stime, child_total_cpu_seconds=usage.ru_utime + usage.ru_stime,
        child_peak_rss_kib_linux=usage.ru_maxrss, wall_seconds=time.perf_counter() - started,
        stderr=stderr, resources_before=before, resources_after=measurement(),
        source_sha256=sha(source), registration_sha256=sha(output / "REGISTRATION.json"),
        previous_guard_relationship="Old helper directly indexed /proc using namespace Popen.pid; this environment exposes host PID paths. New unique PPid/NSpid mapping corrects accounting. The old OOM also involved shared concurrent allocations; this does not prove that PID mismatch caused or fully explains that OOM.")
    write(output / "RESULTS.json", result)
    print(json.dumps(dict(passed=passed, checks=checks, namespace_pid=process.pid,
                         host_pid=None if credit is None else credit.get("host_pid"))), flush=True)
    if not passed:
        raise RuntimeError("Namespace resource probe failed")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args()
    probe(arguments.output.resolve())
