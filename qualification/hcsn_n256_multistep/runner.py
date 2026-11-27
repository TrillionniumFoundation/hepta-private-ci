"""Source-bound local execution with limits before each fresh interpreter."""

import hashlib
import importlib.metadata
import json
import os
import platform
import resource
import signal
import subprocess
import sys
import time
from pathlib import Path


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
THREADS = {key: "1" for key in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "NUMEXPR_NUM_THREADS", "VECLIB_MAXIMUM_THREADS")}


def write(path, value):
    path.write_text(json.dumps(value, sort_keys=True, indent=2, allow_nan=False) + "\n")


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def runtime():
    distributions = {}
    for name in ("numpy", "scipy"):
        distribution = importlib.metadata.distribution(name)
        records = [entry for entry in distribution.files if str(entry).endswith(".dist-info/RECORD")]
        if len(records) != 1:
            raise ValueError("one runtime distribution RECORD required")
        distributions[name] = {"version": distribution.version,
            "record_sha256": digest(distribution.locate_file(records[0]))}
    return {"executable": str(Path(sys.executable).resolve()), "executable_sha256": digest(sys.executable),
        "python": sys.version, "platform": platform.platform(), "distributions": distributions}


def resources():
    fields = dict(line.split(":", 1) for line in Path("/proc/meminfo").read_text().splitlines())
    cgroup = {}
    for key in ("memory.max", "memory.current", "memory.events", "memory.pressure"):
        path = Path("/sys/fs/cgroup") / key
        cgroup[key] = path.read_text() if path.exists() else None
    return {"sample_unix_seconds": time.time(), "affinity": sorted(os.sched_getaffinity(0)),
        "MemAvailable_bytes": int(fields["MemAvailable"].split()[0])*1024,
        "cgroup_membership": Path("/proc/self/cgroup").read_text(), "visible_cgroup": cgroup}


def child_limits():
    resource.setrlimit(resource.RLIMIT_AS, (4*1024**3, 4*1024**3))
    resource.setrlimit(resource.RLIMIT_CPU, (600, 610))
    os.sched_setaffinity(0, {8})


def child(lane, output, limit):
    snapshot = resources()
    if 8 not in snapshot["affinity"] or snapshot["MemAvailable_bytes"] < 4*1024**3:
        raise ValueError("new bounded local resource preflight")
    write(output / f"PREFLIGHT-{lane}.json", snapshot)
    module = "review" if lane == "review" else "study"
    command = [sys.executable, "-m", "qualification.hcsn_n256_multistep." + module]
    command += [str(output)] if lane == "review" else [lane, str(output)]
    with (output / f"{lane}.stdout").open("xb") as stdout, (output / f"{lane}.stderr").open("xb") as stderr:
        started = time.perf_counter()
        process = subprocess.Popen(command, cwd=ROOT, stdout=stdout, stderr=stderr,
            env={**os.environ, **THREADS}, preexec_fn=child_limits, start_new_session=True)
        write(output / f"START-{lane}.json", {"pid": process.pid, "command": command,
            "started_unix_seconds": time.time(), "deadline_seconds": limit,
            "address_space_limit_bytes": 4*1024**3, "cpu_affinity": [8], "thread_environment": THREADS})
        timed_out, terminated = False, None
        while True:
            pid, status, usage = os.wait4(process.pid, os.WNOHANG)
            if pid:
                break
            elapsed = time.perf_counter() - started
            if elapsed > limit and not timed_out:
                os.killpg(process.pid, signal.SIGTERM)
                timed_out, terminated = True, elapsed
            elif timed_out and elapsed > terminated + 10:
                os.killpg(process.pid, signal.SIGKILL)
            time.sleep(.1)
        process.returncode = os.waitstatus_to_exitcode(status)
    cost = {"lane": lane, "exit_code": process.returncode, "timed_out": timed_out,
        "wall_seconds_including_interpreter_and_imports": time.perf_counter() - started,
        "cpu_user_seconds": usage.ru_utime, "cpu_system_seconds": usage.ru_stime,
        "peak_rss_KiB": usage.ru_maxrss, "terminal_resources": resources()}
    write(output / f"COST-{lane}.json", cost)
    print(json.dumps({"lane": lane, "exit_code": process.returncode, "wall": cost["wall_seconds_including_interpreter_and_imports"]}), flush=True)
    if process.returncode != 0 or timed_out:
        raise RuntimeError("one-shot lane failed: " + lane)
    return cost


def main():
    request = json.loads((HERE / "REQUEST.json").read_text())
    freeze = json.loads((HERE / "SOURCE_FREEZE.json").read_text())
    for name, expected in freeze["sources"].items():
        if digest(ROOT / name) != expected:
            raise ValueError("frozen source changed: " + name)
    if runtime() != freeze["runtime"]:
        raise ValueError("runtime differs from frozen local profile")
    output = Path(sys.argv[1]).resolve()
    output.mkdir(parents=True, exist_ok=False)
    write(output / "REQUEST.json", request)
    write(output / "SOURCE_FREEZE.json", freeze)
    write(output / "INITIAL_RESOURCES.json", resources())
    costs = []
    started = time.perf_counter()
    terminal = {"status": "FAILED_OR_UNKNOWN", "all_closed": False}
    try:
        for lane in request["lanes"]:
            costs.append(child(lane, output, request["deadline_seconds"][lane]))
        terminal["status"] = "COMPLETED_AND_INDEPENDENTLY_REVIEWED"
    finally:
        terminal["completed_lanes"] = [item["lane"] for item in costs]
        terminal["wall_seconds"] = time.perf_counter() - started
        terminal["original_sparse_bitwise_gate"] = "RED_UNCHANGED"
        terminal["optimizer_steps"] = 0
        write(output / "TERMINAL.json", terminal)


if __name__ == "__main__":
    main()
