"""Linux operational process-tree budget with measured, uncapped overshoot.

Run this CLI in a dedicated supervisor process, not inside a training runtime.
It kills only its own newly created job and reaps orphaned job descendants. The
polling threshold is NOT a deterministic future physical-cost support proof.
"""

import argparse
import ctypes
import json
import math
import os
from pathlib import Path
import resource
import signal
import subprocess
import time


def process_table():
    result = {}
    for path in Path("/proc").iterdir():
        if not path.name.isdigit():
            continue
        try:
            raw = (path / "stat").read_text()
            fields = raw[raw.rfind(")") + 2:].split()
            result[int(path.name)] = {"ppid": int(fields[1]), "pgid": int(fields[2]),
                "starttime": int(fields[19]), "state": fields[0],
                "cpu_ticks": sum(int(fields[i]) for i in (11, 12, 13, 14))}
        except (FileNotFoundError, ProcessLookupError):
            pass
    return result


def probe():
    path = Path("/sys/fs/cgroup")
    return {"platform": os.uname().sysname, "clock_ticks_per_second": os.sysconf("SC_CLK_TCK"),
            "cgroup_root_writable": os.access(path, os.W_OK),
            "own_cgroup_membership": Path("/proc/self/cgroup").read_text().strip(),
            "shared_cgroup_cpu_is_not_episode_cpu": True,
            "RLIMIT_CPU_scope": "each process independently, including independently inherited child limits",
            "finite_total_cpu_support_proved": False,
            "references": ["https://man7.org/linux/man-pages/man2/getrlimit.2.html",
                           "https://www.kernel.org/doc/html/latest/admin-guide/cgroup-v2.html",
                           "https://man7.org/linux/man-pages/man2/PR_SET_CHILD_SUBREAPER.2const.html"]}


def run(command, output, *, cpu_budget=.2, wall_budget=5.0, poll_seconds=.005, file_bytes=16777216):
    if (not command or not all(isinstance(s, str) for s in command)
            or any(not math.isfinite(v) or v <= 0 for v in (cpu_budget, wall_budget, poll_seconds))):
        raise ValueError("An explicit command and finite positive operational budgets are required")
    table = process_table()
    if any(row["ppid"] == os.getpid() for row in table.values()):
        raise ValueError("Use a dedicated supervisor process with no pre-existing children")
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    own_start = resource.getrusage(resource.RUSAGE_SELF)
    child_start = resource.getrusage(resource.RUSAGE_CHILDREN)
    started = time.monotonic()
    libc = ctypes.CDLL(None, use_errno=True)
    if libc.prctl(36, 1, 0, 0, 0) != 0:  # PR_SET_CHILD_SUBREAPER
        raise OSError(ctypes.get_errno(), "Cannot account for orphaned job descendants")
    protocol = {"command": command, "cpu_budget_seconds": cpu_budget,
                "wall_budget_seconds": wall_budget, "poll_seconds": poll_seconds,
                "per_process_hard_CPU_seconds": max(1, math.ceil(cpu_budget) + 1),
                "per_file_bytes": file_bytes, "kill_scope": "new job session plus adopted job descendants",
                "finite_cost_support_claim": False, "environment_probe": probe()}
    (output / "PROTOCOL.json").write_text(json.dumps(protocol, indent=2) + "\n")

    def child_limits():
        resource.setrlimit(resource.RLIMIT_CPU, (protocol["per_process_hard_CPU_seconds"],) * 2)
        resource.setrlimit(resource.RLIMIT_FSIZE, (file_bytes, file_bytes))

    reaped, known, peak, kill_reason, kill_time = [], {}, 0.0, None, None
    with (output / "stdout.txt").open("xb") as stdout, (output / "stderr.txt").open("xb") as stderr:
        job = subprocess.Popen(command, stdout=stdout, stderr=stderr, start_new_session=True,
                               preexec_fn=child_limits, stdin=subprocess.DEVNULL)
        job_pid = job.pid
        while True:
            table = process_table()
            members = {pid for pid, row in table.items()
                       if row["pgid"] == job_pid or row["ppid"] == os.getpid()}
            previous = None
            while previous != members:
                previous = set(members)
                members.update(pid for pid, row in table.items() if row["ppid"] in members)
            for pid in members:
                known[pid] = table[pid]["starttime"]
            # A live process's cutime/cstime includes only descendants it has
            # already reaped. Still-live descendants are separate members.
            measured = (sum(table[pid]["cpu_ticks"] for pid in members) / os.sysconf("SC_CLK_TCK")
                        + sum(row["cpu_seconds"] for row in reaped))
            peak = max(peak, measured)
            elapsed = time.monotonic() - started
            escaped = any(table[pid]["pgid"] != job_pid for pid in members)
            if kill_reason is None:
                if escaped:
                    kill_reason = "job_descendant_changed_process_group"
                elif measured >= cpu_budget:
                    kill_reason = "observed_process_tree_cpu_budget"
                elif elapsed >= wall_budget:
                    kill_reason = "wall_watchdog"
                if kill_reason:
                    kill_time = time.monotonic()
            if kill_reason:
                try:
                    os.killpg(job_pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                for pid in members:
                    if table[pid]["starttime"] == known[pid]:
                        try:
                            os.kill(pid, signal.SIGKILL)
                        except ProcessLookupError:
                            pass
            while True:
                try:
                    pid, status, usage = os.wait4(-1, os.WNOHANG)
                except ChildProcessError:
                    pid = 0
                if not pid:
                    break
                reaped.append({"pid": pid, "exit_status": os.waitstatus_to_exitcode(status),
                               "cpu_seconds": usage.ru_utime + usage.ru_stime,
                               "own_and_waited_descendant_usage": True})
                if pid == job_pid:
                    job.returncode = os.waitstatus_to_exitcode(status)
            if job.returncode is not None and not members:
                break
            if kill_time is not None and time.monotonic() - kill_time > 15:
                break
            time.sleep(poll_seconds)
    remaining = process_table()
    live = [pid for pid, birth in known.items() if pid in remaining and remaining[pid]["starttime"] == birth]
    own_end = resource.getrusage(resource.RUSAGE_SELF)
    child_end = resource.getrusage(resource.RUSAGE_CHILDREN)
    child_cpu = child_end.ru_utime + child_end.ru_stime - child_start.ru_utime - child_start.ru_stime
    # This CLI is a dedicated supervisor. Charge its full process lifetime,
    # including module/argument/preflight setup, rather than hiding startup.
    supervisor_cpu = own_end.ru_utime + own_end.ru_stime
    exact_reaped = sum(row["cpu_seconds"] for row in reaped)
    reconciliation_delta = child_cpu - exact_reaped
    reconciles = abs(reconciliation_delta) <= 2e-6 * (len(reaped) + 1)
    result = {"schema": "hepta.ndu.operational-process-tree-budget.v1", "protocol": protocol,
              "job_pid": job_pid, "job_returncode": job.returncode, "kill_reason": kill_reason,
              "observed_tree_cpu_peak_seconds": peak, "actual_reaped_tree_cpu_seconds": exact_reaped,
              "supervisor_cpu_seconds": supervisor_cpu, "complete_cpu_seconds": child_cpu + supervisor_cpu,
              "cumulative_waited_child_cpu_seconds": child_cpu,
              "wait4_sum_vs_cumulative_delta_seconds": reconciliation_delta,
              "child_accounting_reconciles_within_microsecond_rounding": reconciles,
              "uncapped_cpu_overshoot_seconds": max(0.0, child_cpu - cpu_budget),
              "actual_wall_seconds": time.monotonic() - started, "reaped": reaped,
              "remaining_known_pids": live, "all_job_descendants_reaped": not live,
              "physical_accounting_complete": not live and reconciles, "finite_future_cpu_support_proved": False,
              "full_episode_integration": False,
              "scope": "actual operational job cleanup/accounting test; not an NDU certificate or a capability gain"}
    (output / "RESULT.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True)
    parser.add_argument("--cpu-budget", type=float, default=.2)
    parser.add_argument("--wall-budget", type=float, default=5.)
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    command = args.command[1:] if args.command[:1] == ["--"] else args.command
    run(command, args.output, cpu_budget=args.cpu_budget, wall_budget=args.wall_budget)
