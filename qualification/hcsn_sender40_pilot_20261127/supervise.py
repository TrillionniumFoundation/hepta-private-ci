"""Fail-closed Linux CPU/memory qualification and one non-retried child process."""
import json
import os
from pathlib import Path
import resource
import signal
import sys
import time


def save(path, value):
    with Path(path).open("x") as stream:
        json.dump(value, stream, indent=2, sort_keys=True, allow_nan=False)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())


def parse_limits(values):
    memory, pids = values["memory.max"].strip(), values["pids.max"].strip()
    quota, period = values["cpu.max"].split()
    if memory == "max" or not 0 < int(memory) <= 1073741824:
        raise ValueError("dedicated cgroup must cap memory at one GiB")
    if pids == "max" or not 0 < int(pids) <= 64:
        raise ValueError("dedicated cgroup must cap tasks at 64")
    if quota == "max" or not 0 < int(quota) <= int(period):
        raise ValueError("dedicated cgroup must cap aggregate CPU at one core")
    return dict(memory_max_bytes=int(memory), pids_max=int(pids),
                cpu_quota_microseconds=int(quota), cpu_period_microseconds=int(period))


def cgroup_snapshot():
    entries = [line.split(":", 2) for line in Path("/proc/self/cgroup").read_text().splitlines()]
    unified = [entry[2] for entry in entries if entry[:2] == ["0", ""]]
    if len(unified) != 1 or ".." in Path(unified[0]).parts or unified[0] == "/":
        raise ValueError("one dedicated cgroup-v2 service is required")
    root = (Path("/sys/fs/cgroup") / unified[0].lstrip("/")).resolve()
    if not root.is_relative_to("/sys/fs/cgroup"):
        raise ValueError("invalid cgroup path")
    limits = parse_limits({key: (root / key).read_text() for key in ("memory.max", "cpu.max", "pids.max")})
    return root, dict(path=str(root), **limits)


def cpu_usage(root):
    fields = dict(line.split() for line in (root / "cpu.stat").read_text().splitlines())
    return int(fields["usage_usec"])


def stop_child(pid):
    try:
        os.killpg(pid, signal.SIGKILL)
    except ProcessLookupError:
        # A pre-exec error may occur before this owned child has called setsid.
        try:
            os.kill(pid, signal.SIGKILL)
        except ProcessLookupError:
            pass


def main():
    prepared, output = (Path(value).resolve() for value in sys.argv[1:3])
    output.mkdir(parents=True, exist_ok=False)
    start = time.monotonic()
    result = dict(schema="hepta.sender40-one-process-supervisor.v1", status="NOT_STARTED",
                  retries=0, model_processes_started=0, environment_values_logged=False,
                  active_wall_limit_seconds=300, aggregate_cpu_limit_seconds=180)
    pid, waited = None, False
    try:
        root, limits = cgroup_snapshot()
        available = sorted(os.sched_getaffinity(0))
        if not available:
            raise ValueError("no allowed CPU")
        os.sched_setaffinity(0, {available[0]})
        baseline_usage = cpu_usage(root)
        result.update(cgroup=limits, cpu_affinity=[available[0]])
        save(output / "START.json", result)
        stdout = (output / "child.stdout").open("xb")
        stderr = (output / "child.stderr").open("xb")
        pid = os.fork()
        if pid == 0:
            try:
                os.setsid()
                resource.setrlimit(resource.RLIMIT_CPU, (180, 181))
                resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
                os.dup2(stdout.fileno(), 1)
                os.dup2(stderr.fileno(), 2)
                env = dict(os.environ)
                env.update(OMP_NUM_THREADS="1", OPENBLAS_NUM_THREADS="1", MKL_NUM_THREADS="1",
                           NUMEXPR_NUM_THREADS="1", CUDA_VISIBLE_DEVICES="", PYTHONDONTWRITEBYTECODE="1")
                script = Path(__file__).resolve().with_name("pilot.py")
                os.execve(sys.executable, [sys.executable, str(script), str(prepared), str(output / "experiment")], env)
            except BaseException:
                os._exit(127)
        result.update(status="STARTED", model_processes_started=1, child_pid=pid)
        stdout.close()
        stderr.close()
        stopped = None
        while True:
            ended, status, usage = os.wait4(pid, os.WNOHANG)
            if ended:
                waited = True
                break
            elapsed = time.monotonic() - start
            spent = (cpu_usage(root) - baseline_usage) / 1e6
            if stopped is None and (elapsed >= 300 or spent >= 180):
                stopped = "ACTIVE_WALL_LIMIT" if elapsed >= 300 else "AGGREGATE_CGROUP_CPU_LIMIT"
                stop_child(pid)
            time.sleep(.2)
        code = os.waitstatus_to_exitcode(status)
        result.update(status="COMPLETED" if code == 0 else "ABORTED", child_exit_code=code,
                      stop_reason=stopped, child_user_seconds=usage.ru_utime,
                      child_system_seconds=usage.ru_stime, child_peak_rss_kib=usage.ru_maxrss,
                      aggregate_cgroup_cpu_seconds=(cpu_usage(root) - baseline_usage) / 1e6,
                      cgroup_memory_events=(root / "memory.events").read_text().splitlines())
        experiment = output / "experiment"
        result["child_result_present"] = (experiment / "RESULT.json").is_file()
        calls = experiment / "calls.jsonl"
        if calls.is_file():
            lines = calls.read_text().splitlines()
            result["last_complete_ledger_record"] = None
            result["incomplete_trailing_ledger_lines"] = 0
            for line in reversed(lines):
                try:
                    result["last_complete_ledger_record"] = json.loads(line)
                    break
                except json.JSONDecodeError:
                    result["incomplete_trailing_ledger_lines"] += 1
            result["partial_call_record_may_remain"] = code != 0
        if code != 0 or not result["child_result_present"]:
            raise RuntimeError("single frozen child aborted; no retry or replacement is permitted")
        child_result = json.loads((experiment / "RESULT.json").read_text())
        if child_result["status"] != "COMPLETED":
            raise RuntimeError("child result is not a completed frozen experiment")
    except BaseException as error:
        result.update(status="ABORTED", error=repr(error))
        if pid is not None and not waited:
            stop_child(pid)
            os.wait4(pid, 0)
        raise
    finally:
        result["wall_seconds"] = time.monotonic() - start
        save(output / "OUTER_RESULT.json", result)


if __name__ == "__main__":
    main()
