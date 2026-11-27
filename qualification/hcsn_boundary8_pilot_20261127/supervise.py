"""One Linux public boundary child, within1GiB/oneCPU/120CPU seconds/180wall.

Must be placed in its own systemd cgroup with RuntimeMaxSec210 and KillMode
control-group by the reviewed workflow. No retry, group borrowing or cap change.
"""
import json
import os
from pathlib import Path
import resource
import signal
import sys
import time


def save(path, value):
    with path.open("x") as stream:
        json.dump(value, stream, indent=2, sort_keys=True, allow_nan=False)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())


def cgroup():
    entries = [line.split(":", 2) for line in Path("/proc/self/cgroup").read_text().splitlines()]
    unified = [row[2] for row in entries if row[:2] == ["0", ""]]
    if len(unified) != 1 or unified[0] == "/" or ".." in Path(unified[0]).parts:
        raise ValueError("one dedicated cgroup-v2 service is required")
    root = (Path("/sys/fs/cgroup") / unified[0].lstrip("/")).resolve()
    if not root.is_relative_to("/sys/fs/cgroup"):
        raise ValueError("cgroup root escape")
    memory = (root / "memory.max").read_text().strip()
    tasks = (root / "pids.max").read_text().strip()
    quota, period = (root / "cpu.max").read_text().split()
    if (memory == "max" or not 0 < int(memory) <= 1073741824 or tasks == "max" or not 0 < int(tasks) <= 64 or
            quota == "max" or not 0 < int(quota) <= int(period)):
        raise ValueError("required dedicated memory/task/CPU limits absent or too loose")
    return root, dict(path=str(root), memory_max=int(memory), tasks_max=int(tasks), cpu_quota=int(quota), cpu_period=int(period))


def cpu_usage(root):
    values = dict(line.split() for line in (root / "cpu.stat").read_text().splitlines())
    return int(values["usage_usec"])


def stop_owned_unreaped_child(pid):
    # The child remains ours and cannot have its PID reused until wait4 reaps it.
    try:
        os.killpg(pid, signal.SIGKILL)
    except ProcessLookupError:
        try:
            os.kill(pid, signal.SIGKILL)
        except ProcessLookupError:
            pass


def main():
    if len(sys.argv) != 6:
        raise SystemExit("supervise.py BINDING HELPER PREPARED EVIDENCE NEW_OUTPUT")
    binding, helper, prepared, evidence, output = (Path(value).resolve() for value in sys.argv[1:])
    output.mkdir(parents=True, exist_ok=False)
    started = time.monotonic()
    result = dict(schema="hepta.boundary8-public-supervisor.v1", status="NOT_STARTED", retries=0,
                  processes_started=0, cpu_seconds_limit=120, wall_seconds_limit=180,
                  environment_values_logged=False)
    pid, waited = None, False
    try:
        root, limits = cgroup()
        available = sorted(os.sched_getaffinity(0))
        if not available:
            raise ValueError("no allowed CPU")
        os.sched_setaffinity(0, {available[0]})
        cpu_before = cpu_usage(root)
        result.update(cgroup=limits, cpu_affinity=[available[0]])
        save(output / "START.json", result)
        stdout = (output / "child.stdout").open("xb")
        stderr = (output / "child.stderr").open("xb")
        pid = os.fork()
        if pid == 0:
            try:
                os.setsid()
                resource.setrlimit(resource.RLIMIT_CPU, (120, 121))
                resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
                os.dup2(stdout.fileno(), 1)
                os.dup2(stderr.fileno(), 2)
                env = dict(os.environ)
                env.update(OMP_NUM_THREADS="1", OPENBLAS_NUM_THREADS="1", MKL_NUM_THREADS="1", NUMEXPR_NUM_THREADS="1",
                           CUDA_VISIBLE_DEVICES="", PYTHONDONTWRITEBYTECODE="1")
                script = Path(__file__).resolve().with_name("runner.py")
                args = [sys.executable, str(script), str(binding), str(helper), str(prepared), str(evidence), str(output / "experiment")]
                os.execve(sys.executable, args, env)
            except BaseException:
                os._exit(127)
        result.update(status="STARTED", child_pid=pid, processes_started=1)
        save(output / "CHILD_STARTED.json", result)
        stdout.close()
        stderr.close()
        stopped = None
        while True:
            ended, status, usage = os.wait4(pid, os.WNOHANG)
            if ended:
                waited = True
                break
            elapsed = time.monotonic() - started
            consumed = (cpu_usage(root) - cpu_before) / 1e6
            if stopped is None and (elapsed >= 180 or consumed >= 120):
                stopped = "WALL_LIMIT" if elapsed >= 180 else "AGGREGATE_CPU_LIMIT"
                stop_owned_unreaped_child(pid)
            time.sleep(.2)
        code = os.waitstatus_to_exitcode(status)
        result.update(status="COMPLETED" if code == 0 else "ABORTED", child_exit_code=code,
                      stop_reason=stopped, user_seconds=usage.ru_utime, system_seconds=usage.ru_stime,
                      max_rss_kib=usage.ru_maxrss, aggregate_cgroup_cpu_seconds=(cpu_usage(root)-cpu_before)/1e6,
                      cgroup_memory_events=(root / "memory.events").read_text().splitlines())
        experiment = output / "experiment"
        result["experiment_result_present"] = (experiment / "RESULT.json").is_file()
        calls = experiment / "calls.jsonl"
        if calls.is_file():
            result["last_complete_call_record"] = None
            result["incomplete_trailing_lines"] = 0
            for line in reversed(calls.read_text().splitlines()):
                try:
                    result["last_complete_call_record"] = json.loads(line)
                    break
                except json.JSONDecodeError:
                    result["incomplete_trailing_lines"] += 1
        if code != 0 or not result["experiment_result_present"]:
            raise RuntimeError("single boundary experiment stopped; no retry authorized")
        if json.loads((experiment / "RESULT.json").read_text())["status"] != "COMPLETED":
            raise RuntimeError("boundary result did not complete")
    except BaseException as error:
        result.update(status="ABORTED", error=repr(error))
        if pid is not None and not waited:
            stop_owned_unreaped_child(pid)
            _, status, usage = os.wait4(pid, 0)
            result["cleanup_child_exit_code"] = os.waitstatus_to_exitcode(status)
        raise
    finally:
        result["wall_seconds"] = time.monotonic() - started
        save(output / "OUTER_RESULT.json", result)


if __name__ == "__main__":
    main()
