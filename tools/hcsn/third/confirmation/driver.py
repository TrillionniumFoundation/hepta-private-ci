"""Conditional local execution, with bounded parallel seed workers on Linux."""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess
import sys
import time

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT))
from third.confirmation.contract import atomic_json, require_development, sha, verify


def snapshot():
    folder = Path("/sys/fs/cgroup")
    stat = {k: int(v) for k, v in (line.split() for line in (folder / "memory.stat").read_text().splitlines())}
    current, maximum = int((folder / "memory.current").read_text()), int((folder / "memory.max").read_text())
    clean = max(0, stat["inactive_file"] - stat["file_dirty"] - stat["file_writeback"])
    return dict(raw_current_bytes=current, cgroup_limit_bytes=maximum,
        clean_inactive_estimate_bytes=clean, conservative_working_set_bytes=max(0, current - clean),
        estimated_headroom_bytes=maximum - max(0, current - clean),
        utc=datetime.now(timezone.utc).isoformat())


def wait_capacity(folder, name, reserved_workers):
    started = time.perf_counter()
    policy = json.loads((HERE / "protocol.json").read_text())["execution"]
    required = reserved_workers * policy["minimum_headroom_bytes_per_worker"]
    observations = []
    while True:
        state = snapshot()
        if state["estimated_headroom_bytes"] >= required:
            return dict(seconds=time.perf_counter() - started, admission=state,
                        required_headroom_bytes=required, observations=observations)
        observations.append(state)
        atomic_json(Path(folder) / ("resource_pause_" + name.replace("/", "_") + ".json"),
                    dict(run=name, required_headroom_bytes=required, observations=observations))
        print("CONFIRMATION_RESOURCE_PAUSE", name, state["estimated_headroom_bytes"], flush=True)
        time.sleep(policy["pause_seconds"])


def main(wait):
    verify()
    protocol = json.loads((HERE / "protocol.json").read_text())
    output = HERE / "execution.json"
    result = json.loads(output.read_text()) if output.exists() else dict(
        confirmation_freeze_sha256=sha(HERE / "freeze.json"), status="not_started",
        no_confirmation_data_constructed=True, children=[], preparation_attempts=[])
    if result["confirmation_freeze_sha256"] != sha(HERE / "freeze.json"):
        raise RuntimeError("Execution receipt belongs to another freeze")
    if result["status"] == "complete":
        require_development()
        return
    last_count = None
    while True:
        development = json.loads((ROOT / "third/memory/development_results.json").read_text())
        if development.get("complete"):
            if not development.get("development_gate", {}).get("passed"):
                if (HERE / "data_manifest.json").exists():
                    raise RuntimeError("A previously used development prerequisite no longer passes; preserve prior evidence")
                result.update(status="not_executed_development_failed", no_confirmation_data_constructed=True,
                              development_gate=development["development_gate"],
                              development_result_sha256=sha(ROOT / "third/memory/development_results.json"))
                atomic_json(output, result)
                print("CONFIRMATION_NOT_EXECUTED_DEVELOPMENT_FAILED", flush=True)
                return
            break
        result.update(status="waiting_for_complete_development_gate", observed_development_runs=len(development["runs"]))
        atomic_json(output, result)
        if last_count != len(development["runs"]):
            print("WAIT_DEVELOPMENT", len(development["runs"]), flush=True)
            last_count = len(development["runs"])
        if not wait:
            return
        time.sleep(protocol["execution"]["pause_seconds"])
    prerequisite = require_development()
    atomic_json(HERE / "prerequisite.json", prerequisite)
    cpus = sorted(os.sched_getaffinity(0))
    count = protocol["execution"]["cpus_per_worker"]
    if len(cpus) < count:
        raise RuntimeError("Two available CPUs are required for the declared worker configuration")
    groups = [cpus[i:i + count] for i in range(0, len(cpus) - count + 1, count)]
    groups = groups[:protocol["execution"]["max_workers"]]
    env = dict(os.environ, OPENBLAS_NUM_THREADS="1", OMP_NUM_THREADS=str(count),
               PYTHONDONTWRITEBYTECODE="1", XLA_PYTHON_CLIENT_PREALLOCATE="false")
    env["PYTHONPATH"] = str(ROOT) + os.pathsep + env.get("PYTHONPATH", "")
    wait_capacity(HERE, "prepare", 1)
    start = time.perf_counter()
    prepared = subprocess.run([sys.executable, str(HERE / "data.py")], cwd=ROOT, env=env,
                              preexec_fn=lambda: os.sched_setaffinity(0, groups[0]))
    result["preparation_attempts"].append(dict(returncode=prepared.returncode, wall_seconds=time.perf_counter() - start))
    result.update(no_confirmation_data_constructed=False, status="prepared" if prepared.returncode == 0 else "preparation_failed")
    atomic_json(output, result)
    if prepared.returncode:
        raise SystemExit(prepared.returncode)
    pending = list(protocol["seeds"])
    active, failed = [], False
    while pending or active:
        for item in list(active):
            code = item["process"].poll()
            if code is not None:
                item["log"].close()
                item["receipt"].update(returncode=code, wall_seconds=time.time() - item["receipt"]["started_epoch_seconds"])
                active.remove(item)
                failed |= code != 0
                atomic_json(output, result)
        if failed and not active:
            break
        if pending and not failed and len(active) < len(groups):
            required = (len(active) + 1) * protocol["execution"]["minimum_headroom_bytes_per_worker"]
            if snapshot()["estimated_headroom_bytes"] >= required:
                seed = pending.pop(0)
                used = [item["receipt"]["cpus"] for item in active]
                group = next(group for group in groups if group not in used)
                log = (HERE / f"worker_seed{seed}.log").open("a")
                receipt = dict(seed=seed, cpus=group, started_epoch_seconds=time.time(),
                               admission=snapshot(), log_file=f"worker_seed{seed}.log")
                process = subprocess.Popen([sys.executable, str(HERE / "worker.py"), "--seed", str(seed)],
                    cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT,
                    preexec_fn=lambda: os.sched_setaffinity(0, group))
                receipt["pid"] = process.pid
                result["children"].append(receipt)
                active.append(dict(process=process, log=log, receipt=receipt))
                result["status"] = "running"
                atomic_json(output, result)
                print("CONFIRMATION_WORKER_STARTED", seed, group, flush=True)
                continue
        if pending or active:
            time.sleep(protocol["execution"]["pause_seconds"])
    if failed:
        result.update(status="worker_failed", unstarted_seeds=pending)
        atomic_json(output, result)
        raise SystemExit("A fixed worker failed; receipts and attempts retained")
    completed = subprocess.run([sys.executable, str(HERE / "analyze.py")], cwd=ROOT, env=env)
    result.update(status="complete" if completed.returncode == 0 else "analysis_failed",
                  analysis_returncode=completed.returncode)
    atomic_json(output, result)
    if completed.returncode:
        raise SystemExit(completed.returncode)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--wait", action="store_true")
    main(parser.parse_args().wait)
