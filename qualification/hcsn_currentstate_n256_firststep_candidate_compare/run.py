"""One-shot hosted parent; numerical imports occur only after the child limit."""

import argparse
import hashlib
import json
import os
import resource
import signal
import subprocess
import sys
import time
from pathlib import Path

from qualification.hcsn_currentstate_n256_firststep_dense_oracle_hosted import launcher as prior
from qualification.hcsn_currentstate_n256_firststep_hosted_admission_intent import policy
from qualification.hcsn_currentstate_n256_firststep_resource_snapshot import snapshot_source


ROOT = Path(__file__).parents[2]
HERE = Path(__file__).parent
OUTPUT = HERE / "RUN_OUTPUT"
REQUEST = HERE / "REQUEST.json"
FREEZE = HERE / "SOURCE_FREEZE.json"
THREADS = prior.THREADS


def _canonical(value):
    return json.dumps(value, allow_nan=False, separators=(",", ":"), sort_keys=True).encode()


def _sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _write(name, value):
    path = OUTPUT / name
    path.write_bytes(_canonical(value) + b"\n")
    return path


def _manifest():
    files = {}
    for path in sorted(OUTPUT.iterdir()):
        if path.name != "MANIFEST.json" and path.is_file():
            files[path.name] = {"bytes": path.stat().st_size, "sha256": _sha(path)}
    _write("MANIFEST.json", {"schema": "hcsn-n256-candidate-compare-manifest-v1", "files": files})


def _child():
    from qualification.hcsn_currentstate_n256_firststep_candidate_compare.compare import execute

    result = execute(
        ROOT,
        ROOT / json.loads(REQUEST.read_text())["oracle_artifact_zip"],
        OUTPUT / "N256_CANDIDATE_WARM1.bin",
    )
    _write("RESULT.json", result)
    print(json.dumps(result, allow_nan=False, separators=(",", ":"), sort_keys=True))


def _limit():
    resource.setrlimit(resource.RLIMIT_AS, (4 * 1024**3,) * 2)
    os.setsid()


def _run_child():
    started = time.monotonic_ns()
    before = resource.getrusage(resource.RUSAGE_CHILDREN)
    process = subprocess.Popen(
        [sys.executable, "-m", __package__ + ".run", "--child"],
        cwd=ROOT, env={**os.environ, **THREADS, "PYTHONDONTWRITEBYTECODE": "1"},
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, preexec_fn=_limit,
    )
    timed_out = False
    try:
        stdout, stderr = process.communicate(timeout=600)
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
        "returncode": process.returncode, "timed_out": timed_out,
    }
    _write("COST.json", cost)
    return cost


def main():
    if OUTPUT.exists():
        raise ValueError("RUN_OUTPUT already exists")
    OUTPUT.mkdir()
    child_started = False
    try:
        request = json.loads(REQUEST.read_text())
        if os.environ.get("UNIQUE_EXECUTION_KEY") != request["unique_execution_key"]:
            raise ValueError("unique execution key")
        nested, flat, runtime_sha = prior._runtime()
        if runtime_sha != request["runtime_sha256"]:
            raise ValueError("runtime identity")
        session = ":".join(os.environ.get(name, "") for name in (
            "GITHUB_RUN_ID", "GITHUB_RUN_ATTEMPT", "GITHUB_JOB", "RUNNER_NAME"
        ))
        self_cgroup, chain = snapshot_source._cgroup_chain()
        boot = snapshot_source._read("/proc/sys/kernel/random/boot_id")
        preflight = {
            "schema": "hcsn-n256-hosted-preflight-v1", "session_id": session,
            "boot_id": boot, "self_cgroup": self_cgroup,
            "captured_monotonic_ns": time.monotonic_ns(), "runtime_sha256": runtime_sha,
            "runtime": flat, "runtime_observation": nested,
            "meminfo_kib": snapshot_source._meminfo(),
            "memory_pressure": Path("/proc/pressure/memory").read_text().strip().splitlines(),
            "ancestor_cgroup_chain": chain,
        }
        launch = {
            "schema": "hcsn-n256-hosted-launch-v1", "identity": policy.IDENTITY,
            "session_id": session, "boot_id": boot, "self_cgroup": self_cgroup,
            "execution_monotonic_ns": time.monotonic_ns(),
            "dense_oracle_sha256": policy.DENSE_ORACLE_SHA256,
            "archived_oracle_capsule_sha256": request["oracle_capsule_sha256"],
            "input_bundle_sha256": request["input_bundle_sha256"],
            "target": policy.TARGET, "policy": policy.POLICY,
            "thread_environment": THREADS, "rlimit_as_applied_before_exec": True,
            "numeric_imports_before_child_limit": 0,
        }
        _write("PREFLIGHT.json", preflight)
        _write("LAUNCH.json", launch)
        policy.assess_preflight(preflight, launch)
        _write("ADMISSION.json", {
            "schema": "hcsn-n256-candidate-compare-admission-v1",
            "request_sha256": _sha(REQUEST), "freeze_sha256": _sha(FREEZE),
            "unique_execution_key": request["unique_execution_key"],
            "runtime_sha256": runtime_sha, "oracle_capsule_sha256": request["oracle_capsule_sha256"],
            "candidate_dynamic_steps": 1, "candidate_sparse_exponential_actions": 2,
            "historical_negative_and_unknown_preserved": True,
        })
        start_events = prior._events(chain)
        child_started = True
        cost = _run_child()
        _, end_chain = snapshot_source._cgroup_chain()
        _write("END_CGROUP.json", {"ancestor_cgroup_chain": end_chain})
        for path, start in start_events.items():
            end = prior._events(end_chain).get(path, {})
            for name in ("oom", "oom_kill", "oom_group_kill"):
                if end.get(name, 0) != start.get(name, 0):
                    raise RuntimeError("cgroup OOM counter changed")
        result = json.loads((OUTPUT / "RESULT.json").read_text()) if (OUTPUT / "RESULT.json").is_file() else None
        if cost["timed_out"] or cost["returncode"] != 0 or result is None:
            raise RuntimeError("limited numerical child failed")
        if result["candidate_oracle_bitwise_equal"] is not True:
            raise RuntimeError("candidate/oracle bitwise gate")
        _write("TERMINAL.json", {
            "schema": "hcsn-n256-candidate-compare-terminal-v1", "status": "SUCCESS",
            "result": result, "cost": cost, "qualification": False,
            "production_adoption": False, "all_closed": False,
        })
    except BaseException as error:
        _write("TERMINAL.json", {
            "schema": "hcsn-n256-candidate-compare-terminal-v1", "status": "RED",
            "error_type": type(error).__name__, "error": str(error),
            "child_started": child_started,
            "historical_negative_and_unknown_preserved": True, "all_closed": False,
        })
        _manifest()
        raise
    _manifest()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--child", action="store_true")
    args = parser.parse_args()
    _child() if args.child else main()
