"""One-shot hosted parent; numerical imports occur only in the limited child."""

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

from qualification.hcsn_currentstate_n256_firststep_hosted_admission_intent import policy
from qualification.hcsn_currentstate_n256_firststep_resource_snapshot import snapshot_source


ROOT = Path(__file__).parents[2]
HERE = Path(__file__).parent
OUTPUT = HERE / "RUN_OUTPUT"
REQUEST = HERE / "REQUEST.json"
THREADS = {name: "1" for name in (
    "MKL_NUM_THREADS", "NUMEXPR_NUM_THREADS", "OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS"
)}


def _canonical(value):
    return json.dumps(value, allow_nan=False, separators=(",", ":"), sort_keys=True).encode()


def _sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _write(name, value):
    path = OUTPUT / name
    path.write_bytes(_canonical(value) + b"\n")
    return path


def _distribution(name):
    distribution = importlib.metadata.distribution(name)
    record = distribution.read_text("RECORD")
    if not record:
        raise ValueError(f"{name} RECORD unavailable")
    init = distribution.locate_file(f"{name}/__init__.py")
    return ({
        "name": name,
        "version": distribution.version,
        "record_sha256": hashlib.sha256(record.encode()).hexdigest(),
    }, _sha(init))


def _runtime():
    numpy, numpy_init = _distribution("numpy")
    scipy, scipy_init = _distribution("scipy")
    nested = {
        "python_version": platform.python_version(),
        "python_executable": str(Path(sys.executable).resolve()),
        "python_executable_sha256": _sha(sys.executable),
        "numpy": numpy,
        "numpy_init_sha256": numpy_init,
        "scipy": scipy,
        "scipy_init_sha256": scipy_init,
        "platform": platform.platform(),
        "machine": platform.machine(),
        "thread_environment": {name: os.environ.get(name) for name in THREADS},
    }
    digest = hashlib.sha256(_canonical(nested)).hexdigest()
    flat = {
        "python_version": nested["python_version"],
        "python_executable_sha256": nested["python_executable_sha256"],
        "numpy_version": numpy["version"],
        "numpy_record_sha256": numpy["record_sha256"],
        "numpy_init_sha256": numpy_init,
        "scipy_version": scipy["version"],
        "scipy_record_sha256": scipy["record_sha256"],
        "scipy_init_sha256": scipy_init,
        "machine": nested["machine"],
        "runner_os": os.environ.get("RUNNER_OS"),
        "runner_arch": os.environ.get("RUNNER_ARCH"),
    }
    return nested, flat, digest


def _events(chain):
    result = {}
    for item in chain:
        raw = item["fields"].get("memory.events")
        if raw is not None:
            result[item["path"]] = {
                key: int(value) for key, value in (line.split() for line in raw.splitlines())
            }
    return result


def _child_limit():
    resource.setrlimit(resource.RLIMIT_AS, (policy.POLICY["child_rlimit_as_bytes"],) * 2)
    os.setsid()


def _run_child(admission):
    capsule = OUTPUT / "N256_WARM1.bin"
    result_path = OUTPUT / "RESULT.json"
    command = [
        sys.executable, "-m",
        "qualification.hcsn_currentstate_n256_firststep_dense_oracle_hosted.child",
        "--root", str(ROOT), "--request", str(REQUEST),
        "--admission", str(admission), "--capsule", str(capsule),
        "--result", str(result_path),
    ]
    started = time.monotonic_ns()
    before = resource.getrusage(resource.RUSAGE_CHILDREN)
    process = subprocess.Popen(
        command, cwd=ROOT, env={**os.environ, **THREADS, "PYTHONDONTWRITEBYTECODE": "1"},
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, preexec_fn=_child_limit,
    )
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
    cost = {
        "wall_seconds": (time.monotonic_ns() - started) / 1e9,
        "user_cpu_seconds": after.ru_utime - before.ru_utime,
        "system_cpu_seconds": after.ru_stime - before.ru_stime,
        "child_maxrss_kib": after.ru_maxrss,
        "returncode": process.returncode,
        "timed_out": timed_out,
    }
    _write("COST.json", cost)
    if timed_out or process.returncode != 0 or not result_path.is_file() or not capsule.is_file():
        raise RuntimeError("limited numerical child failed")
    return json.loads(result_path.read_text()), capsule, cost


def _manifest():
    files = {}
    for path in sorted(OUTPUT.iterdir()):
        if path.name != "MANIFEST.json" and path.is_file():
            files[path.name] = {"bytes": path.stat().st_size, "sha256": _sha(path)}
    _write("MANIFEST.json", {"schema": "hcsn-n256-hosted-manifest-v1", "files": files})


def main():
    if OUTPUT.exists():
        raise ValueError("RUN_OUTPUT already exists")
    OUTPUT.mkdir()
    child_started = False
    try:
        request = json.loads(REQUEST.read_text())
        if request["maximum_attempts"] != 1 or not request["n256_numerical_execution_allowed"]:
            raise ValueError("request admission")
        nested, flat, runtime_sha = _runtime()
        _write("RUNTIME_OBSERVATION.json", {
            "runtime": nested, "runtime_sha256": runtime_sha,
        })
        if runtime_sha != request["runtime_sha256"]:
            raise ValueError("hosted runtime identity")
        session = ":".join(os.environ.get(name, "") for name in (
            "GITHUB_RUN_ID", "GITHUB_RUN_ATTEMPT", "GITHUB_JOB", "RUNNER_NAME"
        ))
        self_cgroup, chain = snapshot_source._cgroup_chain()
        boot = snapshot_source._read("/proc/sys/kernel/random/boot_id")
        captured = time.monotonic_ns()
        preflight = {
            "schema": "hcsn-n256-hosted-preflight-v1", "session_id": session,
            "boot_id": boot, "self_cgroup": self_cgroup,
            "captured_monotonic_ns": captured, "runtime_sha256": runtime_sha,
            "runtime": flat, "runtime_observation": nested,
            "meminfo_kib": snapshot_source._meminfo(),
            "memory_pressure": Path("/proc/pressure/memory").read_text().strip().splitlines(),
            "ancestor_cgroup_chain": chain,
        }
        launch = {
            "schema": "hcsn-n256-hosted-launch-v1", "identity": policy.IDENTITY,
            "session_id": session, "boot_id": boot, "self_cgroup": self_cgroup,
            "execution_monotonic_ns": time.monotonic_ns(),
            "dense_oracle_sha256": request["oracle_source_sha256"],
            "input_bundle_sha256": request["input_bundle_sha256"],
            "target": policy.TARGET, "policy": policy.POLICY,
            "thread_environment": THREADS, "rlimit_as_applied_before_exec": True,
            "numeric_imports_before_child_limit": 0,
        }
        _write("PREFLIGHT.json", preflight)
        _write("LAUNCH.json", launch)
        assessed = policy.assess_preflight(preflight, launch)
        if assessed["preflight_contract_satisfied"] is not True:
            raise ValueError("preflight contract")
        captured_wall = time.time_ns()
        allocation = {
            "schema": "hcsn-n256-hosted-allocation-v1", "session_id": session,
            "github_run_id": os.environ.get("GITHUB_RUN_ID"),
            "github_run_attempt": os.environ.get("GITHUB_RUN_ATTEMPT"),
            "github_job": os.environ.get("GITHUB_JOB"), "runner_name": os.environ.get("RUNNER_NAME"),
            "self_cgroup": self_cgroup, "concurrency": 1,
            "child_rlimit_as_bytes": policy.POLICY["child_rlimit_as_bytes"],
            "status": "CURRENT_JOB_ALLOCATED",
        }
        calendar = {
            "schema": "hcsn-n256-hosted-calendar-v1", "captured_wall_ns": captured_wall,
            "captured_monotonic_ns": time.monotonic_ns(),
            "child_timeout_seconds": policy.POLICY["child_timeout_seconds"],
            "job_timeout_minutes": policy.POLICY["job_timeout_minutes"],
        }
        host_path = _write("HOST_SNAPSHOT.json", {
            "runtime": nested, "runtime_sha256": runtime_sha, "meminfo_kib": preflight["meminfo_kib"],
            "memory_pressure": preflight["memory_pressure"], "boot_id": boot, "session_id": session,
        })
        ancestor_path = _write("ANCESTOR_CGROUP.json", {
            "self_cgroup": self_cgroup, "ancestor_cgroup_chain": chain,
        })
        allocation_path = _write("ALLOCATION.json", allocation)
        calendar_path = _write("CALENDAR.json", calendar)
        admission = _write("ADMISSION.json", {
            "schema": "hcsn-n256-firststep-dense-oracle-admission-v1",
            "request_sha256": _sha(REQUEST), "oracle_source_sha256": request["oracle_source_sha256"],
            "dynamic_steps": 1, "dense_expm_actions": 2, "coordinate_denominator": 69728,
            "unique_execution_key": request["unique_execution_key"], "runtime_sha256": runtime_sha,
            "host_snapshot_sha256": _sha(host_path),
            "ancestor_cgroup_snapshot_sha256": _sha(ancestor_path),
            "allocation_sha256": _sha(allocation_path), "calendar_sha256": _sha(calendar_path),
            "historical_negative_and_unknown_preserved": True,
        })
        start_events = _events(chain)
        child_started = True
        result, capsule, cost = _run_child(admission)
        _, end_chain = snapshot_source._cgroup_chain()
        end_events = _events(end_chain)
        for path, start in start_events.items():
            end = end_events.get(path, {})
            for name in ("oom", "oom_kill", "oom_group_kill"):
                if end.get(name, 0) != start.get(name, 0):
                    raise RuntimeError("cgroup OOM counter changed")
        _write("END_CGROUP.json", {"ancestor_cgroup_chain": end_chain})
        expected = {"dynamic_steps": 1, "dense_expm_actions": 2,
                    "n256_serializer_calls": 1, "torch_calls": 0, "optimizer_steps": 0}
        if any(result.get(name) != value for name, value in expected.items()):
            raise RuntimeError("numerical result counts")
        _write("TERMINAL.json", {
            "schema": "hcsn-n256-hosted-terminal-v1", "status": "SUCCESS",
            "identity": request["identity"], "unique_execution_key": request["unique_execution_key"],
            "result": result, "capsule_sha256": _sha(capsule), "cost": cost,
            "largegrid_qualification": False, "production_adoption": False, "all_closed": False,
        })
    except BaseException as error:
        _write("TERMINAL.json", {
            "schema": "hcsn-n256-hosted-terminal-v1", "status": "RED",
            "error_type": type(error).__name__, "error": str(error),
            "child_started": child_started,
            "dynamic_steps": None if child_started else 0,
            "dense_expm_actions": None if child_started else 0,
            "n256_serializer_calls": None if child_started else 0,
            "torch_calls": None if child_started else 0,
            "optimizer_steps": None if child_started else 0,
            "historical_negative_and_unknown_preserved": True, "all_closed": False,
        })
        _manifest()
        raise
    _manifest()


if __name__ == "__main__":
    main()
