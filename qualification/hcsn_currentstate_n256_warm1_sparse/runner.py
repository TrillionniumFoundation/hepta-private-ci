"""New one-shot warm-1 identity, preserving the original hosted resource policy."""

import hashlib
import json
import os
import resource
import signal
import subprocess
import sys
import time
from pathlib import Path

from qualification.hcsn_currentstate_n256_firststep_dense_oracle_hosted.launcher import (
    THREADS, _child_limit, _events, _runtime,
)
from qualification.hcsn_currentstate_n256_firststep_hosted_admission_intent import policy
from qualification.hcsn_currentstate_n256_firststep_resource_snapshot import snapshot_source


ROOT = Path(__file__).parents[2]
HERE = Path(__file__).parent
OUTPUT = HERE / "RUN_OUTPUT"
FREEZE = HERE / "FREEZE.json"
KEY = "hcsn-n256-independent-warm1-sparse-20261119-001"
MODULE = "qualification.hcsn_currentstate_n256_warm1_sparse"
SCOPE = {"start": "0/1", "end": "1/1000", "dynamic_steps": 1,
         "sparse_exponential_actions": 2, "new_dense_actions": 0, "coordinates": 69728}


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write(name, value):
    with (OUTPUT / name).open("x") as stream:
        json.dump(value, stream, allow_nan=False, sort_keys=True, indent=2)
        stream.write("\n")


def check_freeze():
    frozen = json.loads(FREEZE.read_text())
    if frozen["identity"] != KEY or frozen["scope"] != SCOPE or frozen["policy"] != policy.POLICY:
        raise ValueError("new warm-1 identity, scope, or resource policy")
    if frozen["runtime_sha256"] != policy.RUNTIME_SHA256 or frozen["maximum_attempts"] != 1:
        raise ValueError("frozen runtime or attempt count")
    for relative, expected in frozen["source_sha256"].items():
        if sha(ROOT / relative) != expected:
            raise ValueError(f"frozen source mismatch: {relative}")
    return frozen


def assess(preflight, now):
    """Same resource thresholds; this grants only the new warm-1 scope."""
    limits = policy.POLICY
    if preflight["runtime_sha256"] != policy.RUNTIME_SHA256 or preflight["runtime"] != policy.RUNTIME:
        raise ValueError("exact hosted runtime")
    if not 0 <= now - preflight["captured_monotonic_ns"] <= limits["maximum_capture_age_ns"]:
        raise ValueError("stale preflight")
    if preflight["meminfo_kib"].get("MemAvailable", 0) < limits["minimum_mem_available_kib"]:
        raise ValueError("MemAvailable threshold")
    if preflight["meminfo_kib"].get("SwapFree", 0) < limits["minimum_swap_free_kib"]:
        raise ValueError("SwapFree threshold")
    if policy._pressure_avg10(preflight["memory_pressure"]) > limits["maximum_memory_pressure_avg10"]:
        raise ValueError("memory pressure threshold")
    readable, cpus = 0, 0
    for item in preflight["ancestor_cgroup_chain"]:
        fields = item["fields"]
        if "cpuset.cpus.effective" in fields:
            cpus = max(cpus, policy._cpu_count(fields["cpuset.cpus.effective"]))
        if "memory.max" not in fields or "memory.current" not in fields:
            continue
        readable += 1
        events = policy._memory_events(fields.get("memory.events", ""))
        if any(events.get(key, 0) for key in ("oom", "oom_kill", "oom_group_kill")):
            raise ValueError("pre-existing cgroup OOM event")
        if fields["memory.max"] != "max" and int(fields["memory.max"]) - int(fields["memory.current"]) < limits["minimum_finite_cgroup_headroom_bytes"]:
            raise ValueError("finite cgroup headroom")
    if not readable or cpus < limits["minimum_effective_cpus"]:
        raise ValueError("readable ancestor memory limits and effective CPUs")


def verify_child(admission_path):
    check_freeze()
    admission = json.loads(Path(admission_path).read_text())
    if admission["identity"] != KEY or admission["scope"] != SCOPE or admission["freeze_sha256"] != sha(FREEZE):
        raise ValueError("new sparse admission identity")
    if resource.getrlimit(resource.RLIMIT_AS) != (policy.POLICY["child_rlimit_as_bytes"],) * 2:
        raise ValueError("4 GiB RLIMIT_AS must precede numerical imports")
    if any(name in sys.modules for name in ("numpy", "scipy", "torch")):
        raise ValueError("numerical import before admission")
    if {name: os.environ.get(name) for name in THREADS} != THREADS:
        raise ValueError("single-thread environment")
    expected_session = {name: os.environ.get(name) for name in ("GITHUB_RUN_ID", "GITHUB_RUN_ATTEMPT", "GITHUB_JOB")}
    if admission["session"] != expected_session or os.environ.get("UNIQUE_EXECUTION_KEY") != KEY:
        raise ValueError("same-session execution key")
    preflight = admission["preflight"]
    if preflight["boot_id"] != snapshot_source._read("/proc/sys/kernel/random/boot_id") or preflight["self_cgroup"] != snapshot_source._cgroup_chain()[0]:
        raise ValueError("same-boot, same-cgroup binding")
    if _runtime()[2] != policy.RUNTIME_SHA256:
        raise ValueError("child runtime changed")
    assess(preflight, time.monotonic_ns())


def child():
    from qualification.hcsn_currentstate_n256_warm1_sparse.candidate import run_warm1
    from qualification.hcsn_currentstate_n256_warm1_sparse.compare import ORACLE_PATH, compare

    result = run_warm1(ROOT, OUTPUT / "ADMISSION.json", OUTPUT / "N256_WARM1_SPARSE.bin")
    write("RESULT.json", result)
    started = time.perf_counter()
    comparison = compare((OUTPUT / "N256_WARM1_SPARSE.bin").read_bytes(), (ROOT / ORACLE_PATH).read_bytes())
    comparison["comparison_wall_seconds"] = time.perf_counter() - started
    write("COMPARISON.json", comparison)


def main():
    if OUTPUT.exists():
        raise ValueError("one-shot output already exists")
    OUTPUT.mkdir()
    started_child = False
    try:
        check_freeze()
        if os.environ.get("GITHUB_RUN_ATTEMPT") != "1" or not os.environ.get("GITHUB_RUN_ID") or os.environ.get("UNIQUE_EXECUTION_KEY") != KEY:
            raise ValueError("one new hosted attempt required")
        if {name: os.environ.get(name) for name in THREADS} != THREADS:
            raise ValueError("single-thread parent environment")
        if any(name in sys.modules for name in ("numpy", "scipy", "torch")):
            raise ValueError("numerical imports in parent")
        nested, flat, runtime_sha = _runtime()
        cgroup, chain = snapshot_source._cgroup_chain()
        preflight = {"runtime_sha256": runtime_sha, "runtime": flat, "runtime_observation": nested,
                     "captured_monotonic_ns": time.monotonic_ns(), "meminfo_kib": snapshot_source._meminfo(),
                     "memory_pressure": Path("/proc/pressure/memory").read_text().strip().splitlines(),
                     "ancestor_cgroup_chain": chain, "self_cgroup": cgroup,
                     "boot_id": snapshot_source._read("/proc/sys/kernel/random/boot_id")}
        write("PREFLIGHT.json", preflight)
        assess(preflight, time.monotonic_ns())
        admission = {"identity": KEY, "scope": SCOPE, "freeze_sha256": sha(FREEZE),
                     "session": {name: os.environ.get(name) for name in ("GITHUB_RUN_ID", "GITHUB_RUN_ATTEMPT", "GITHUB_JOB")},
                     "preflight": preflight, "policy": policy.POLICY,
                     "allocation": "CURRENT_GITHUB_JOB", "concurrency": 1,
                     "child_timeout_seconds": policy.POLICY["child_timeout_seconds"],
                     "maximum_attempts": 1, "historical_negative_and_unknown_preserved": True,
                     "original_full_roster_admitted": False}
        write("ADMISSION.json", admission)
        wall, before = time.monotonic_ns(), resource.getrusage(resource.RUSAGE_CHILDREN)
        process = subprocess.Popen([sys.executable, "-m", MODULE + ".runner", "--child"],
                                   cwd=ROOT, env={**os.environ, **THREADS, "PYTHONDONTWRITEBYTECODE": "1"},
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, preexec_fn=_child_limit)
        started_child = True
        timed_out = False
        try:
            stdout, stderr = process.communicate(timeout=policy.POLICY["child_timeout_seconds"])
        except subprocess.TimeoutExpired:
            timed_out = True
            os.killpg(process.pid, signal.SIGKILL)
            stdout, stderr = process.communicate()
        after = resource.getrusage(resource.RUSAGE_CHILDREN)
        (OUTPUT / "CHILD.stdout").write_text(stdout)
        (OUTPUT / "CHILD.stderr").write_text(stderr)
        cost = {"wall_seconds": (time.monotonic_ns() - wall) / 1e9,
                "user_cpu_seconds": after.ru_utime - before.ru_utime,
                "system_cpu_seconds": after.ru_stime - before.ru_stime,
                "child_maxrss_kib": after.ru_maxrss, "timed_out": timed_out, "returncode": process.returncode,
                "includes_numerical_imports_and_coordinate_comparison": True}
        write("COST.json", cost)
        _, end_chain = snapshot_source._cgroup_chain()
        write("END_CGROUP.json", {"ancestor_cgroup_chain": end_chain})
        for path, events in _events(chain).items():
            end = _events(end_chain).get(path, {})
            if any(end.get(name, 0) != events.get(name, 0) for name in ("oom", "oom_kill", "oom_group_kill")):
                raise ValueError("cgroup OOM counter changed")
        if timed_out or process.returncode != 0:
            raise ValueError("limited child failed")
        result = json.loads((OUTPUT / "RESULT.json").read_text())
        comparison = json.loads((OUTPUT / "COMPARISON.json").read_text())
        expected = {"dynamic_steps": 1, "sparse_exponential_actions": 2, "dense_expm_actions": 0,
                    "authentic_input_loads": 1, "torch_calls": 0, "optimizer_steps": 0}
        if any(result.get(name) != value for name, value in expected.items()) or comparison["compared_coordinates"] != 69728:
            raise ValueError("bounded execution counts")
        write("TERMINAL.json", {"identity": KEY, "status": "COMPARISON_COMPLETED", "scope": SCOPE,
                                "original_bitwise_gate": "PASS" if comparison["candidate_oracle_bitwise_equal"] else "RED",
                                "new_dense_oracle_executions": 0, "full_roster_qualification": False,
                                "largegrid_qualification": False, "production_adoption": False, "all_closed": False})
    except BaseException as error:
        write("TERMINAL.json", {"identity": KEY, "status": "RED", "error_type": type(error).__name__,
                                "error": str(error), "child_started": started_child,
                                "historical_negative_and_unknown_preserved": True, "all_closed": False})
        raise
    finally:
        write("MANIFEST.json", {path.name: {"bytes": path.stat().st_size, "sha256": sha(path)}
                                for path in sorted(OUTPUT.iterdir()) if path.is_file()})


if __name__ == "__main__":
    if sys.argv[1:] == ["--child"]:
        child()
    elif not sys.argv[1:]:
        main()
    else:
        raise ValueError("only the frozen parent or child entry is supported")
