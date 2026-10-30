"""Independent optimized-risk cost cohort; frozen workers remain unchanged."""

import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time
import traceback

from experiments.hcsn_cost_scaling_v1 import study as base
from experiments.hcsn_risk_memory_v1.resource_accounting import (
    measurement, own_host_pid, anonymous_credit)
from experiments.hcsn_risk_memory_v1.train_equivalence import verify as verify_memory


ROOT = Path(__file__).resolve().parents[2]
PACKAGE = Path(__file__).resolve().parent
COST_PROTOCOL = ROOT / "experiments/hcsn_cost_scaling_v1/PROTOCOL.json"
MATRIX_PROTOCOL = ROOT / "experiments/hcsn_risk_cost_v1/PROTOCOL.json"
MEMORY_PROTOCOL = ROOT / "experiments/hcsn_risk_memory_v1/PROTOCOL.json"
MATRIX_STUDY = ROOT / "experiments/hcsn_risk_cost_v1/results/risk_scale001"
MEMORY_STUDY = ROOT / "experiments/hcsn_risk_memory_v1/results/memory_profile002"
MODEL = "risk_margin_j_risk"
PROFILE = "backward_poisson_risk_vector_v1"
GIB = 1024 ** 3


def oom_counters(resources):
    return {key: resources["events"][key] for key in ("oom", "oom_kill")}


def factory(name, input_dim, output_dim, width=32, depth=1, seed=0):
    if name != MODEL:
        raise ValueError("Only the registered full-risk model is added")
    from experiments.hcsn_risk_memory_v1.model import build_model
    return build_model(name, input_dim, output_dim, width, depth, seed)


def source_map():
    matrix, memory = base.verify(MATRIX_PROTOCOL), base.read(MEMORY_PROTOCOL)
    verify_memory(memory)
    if len(matrix["source_files_sha256"]) != 63 or len(memory["source_files_sha256"]) != 72:
        raise RuntimeError("Unexpected frozen parent source closure")
    if base.digest(MEMORY_PROTOCOL) != "b265e515263b99cfebe96fe1923a65c89742794f7ea30460c5e6ad6c50edff39":
        raise RuntimeError("Unexpected memory profile registration")
    sources = dict(matrix["source_files_sha256"])
    for name, value in memory["source_files_sha256"].items():
        if name in sources and sources[name] != value:
            raise RuntimeError("Conflicting frozen parents: " + name)
        sources[name] = value
    for path in (MATRIX_PROTOCOL, MEMORY_PROTOCOL, PACKAGE / "study.py",
                 PACKAGE / "preflight.py", PACKAGE / "analyze.py", PACKAGE / "README.md"):
        sources[str(path.relative_to(ROOT))] = base.digest(path)
    for name, value in sources.items():
        if base.digest(ROOT / name) != value:
            raise RuntimeError("Source changed: " + name)
    return sources


def memory_priority_reservation():
    """Reserve declared future capacity of the higher-priority fixed128 queue."""
    for terminal in ("COMPLETE.json", "ABORTED.json"):
        path = MEMORY_STUDY / terminal
        if path.exists():
            value = base.read(path)
            if value["protocol_sha256"] != base.digest(MEMORY_PROTOCOL):
                raise RuntimeError("Foreign queue terminal identity mismatch")
            return dict(reserved_bytes=0, reason="priority queue drained", terminal=terminal,
                        terminal_sha256=base.digest(path))
    protocol = base.read(MEMORY_PROTOCOL)
    folder = MEMORY_STUDY / "EXECUTION_PLAN"
    control = base.read(folder / "CONTROL.json")
    desired = control["desired_workers"]
    if not isinstance(desired, int) or not 0 <= desired <= 4:
        raise RuntimeError("Invalid priority queue control")
    budget = protocol["execution"]["per_worker_peak_budget_bytes"]
    active, host_parent = {}, None
    if (folder / "LAUNCH.json").exists():
        launch = base.read(folder / "LAUNCH.json")
        if launch["protocol_sha256"] != base.digest(MEMORY_PROTOCOL):
            raise RuntimeError("Foreign queue launch identity mismatch")
        host_parent = launch["host_pid"]
        journal = folder / "RESOURCE_JOURNAL.jsonl"
        if journal.exists():
            raw = journal.read_bytes()
            # Only complete append-only lines are inspected.
            for line in raw[:raw.rfind(b"\n") + 1].splitlines():
                row = json.loads(line)
                if row["event"] == "dispatched":
                    active[row["namespace_pid"]] = row["job"]
                elif row["event"] == "reaped":
                    active.pop(row["namespace_pid"], None)
    credits = [anonymous_credit(pid, host_parent) for pid in active]
    pending = sum(max(0, budget - row["credited_anon_bytes"]) for row in credits)
    vacant = max(0, desired - len(active))
    return dict(reserved_bytes=pending + vacant * budget,
        reason="reserve current priority control ceiling and remaining capacity of its live children",
        desired_workers=desired, active_jobs=list(active.values()), verified_credits=credits,
        pending_active_bytes=pending, vacant_slots=vacant, per_worker_budget_bytes=budget,
        control_sha256=base.digest(folder / "CONTROL.json"))


def guarded_resources(execution):
    priority = memory_priority_reservation()
    current = measurement()
    remaining = (current["maximum_bytes"] - current["estimated_nonreclaimable_bytes"]
                 - priority["reserved_bytes"] - execution["per_worker_peak_budget_bytes"])
    return dict(resources=current, priority_queue=priority,
        remaining_shared_reserve_bytes=remaining,
        allowed=remaining >= execution["required_shared_reserve_bytes"])


def matrix_terminal():
    for name in ("COMPLETE.json", "ABORTED.json"):
        path = MATRIX_STUDY / name
        if path.exists():
            value = base.read(path)
            if value["protocol_sha256"] != base.digest(MATRIX_PROTOCOL):
                raise RuntimeError("Matrix-cost dependency identity mismatch")
            return dict(path=str(path.relative_to(ROOT)), sha256=base.digest(path),
                        completed=value["completed"], executed=len(value["records"]))
    return None


def register(protocol_path, output, preflight_path):
    if protocol_path.exists() or output.exists():
        raise FileExistsError("Preserve all previous protocols and outputs")
    cost, matrix, sources = base.verify(COST_PROTOCOL), base.verify(MATRIX_PROTOCOL), source_map()
    proof = base.read(preflight_path)
    if not proof["passed"] or not proof["train_only"] or proof["source_files_sha256"] != sources:
        raise RuntimeError("Exact six-pair train-only source-bound preflight required")
    expected = {(task, width, depth) for task in base.TASKS for width, depth in base.SCALES}
    if {(r["task"], r["width"], r["depth"]) for r in proof["pairs"]} != expected:
        raise RuntimeError("Incomplete scale preflight")
    p = dict(schema="hcsn-risk-vector-cost-supplement.v1", registered_utc=base.utc(),
        source_files_sha256=sources, data=cost["data"], jobs=matrix["jobs"],
        optimization=cost["optimization"], quality=cost["quality"], timing=cost["timing"],
        parent=dict(path=str(COST_PROTOCOL.relative_to(ROOT)), sha256=base.digest(COST_PROTOCOL)),
        matrix_parent=dict(path=str(MATRIX_PROTOCOL.relative_to(ROOT)), sha256=base.digest(MATRIX_PROTOCOL)),
        memory_parent=dict(path=str(MEMORY_PROTOCOL.relative_to(ROOT)), sha256=base.digest(MEMORY_PROTOCOL)),
        preflight=dict(path=str(preflight_path.relative_to(ROOT)), sha256=base.digest(preflight_path)),
        implementation_profile=PROFILE,
        interpretation="Post-baseline engineering supplement after a train-only numerical optimization; existing datasets and matrix study exist; no vector cost cohort outcomes used to choose settings; report both implementations",
        execution=dict(workers=1, expected=18, nominal_training_cpu_seconds=360.,
            per_worker_peak_budget_bytes=int(2.5 * GIB), required_shared_reserve_bytes=2 * GIB,
            poll_seconds=2., heartbeat_seconds=30.,
            prerequisite="original matrix-risk cost18 has a terminal receipt after draining, either complete or aborted; never reuse its jobs",
            priority="reserve remaining and vacant desired-worker capacity of memory_profile002 before each launch; fixed128 has priority",
            budget_scope="2.5GiB large-scale cost worker, distinct from the fixed128 width32 1.25GiB budget; this is a conservative forecast, not a hard guarantee",
            stop_policy="any failure/new OOM/own worker peak budget exceedance stops future dispatch; drain current; retain every receipt; no retry",
            monitored_oom_event_counters=["oom", "oom_kill"],
            authorization="root-supplied public seal before dispatch; existing queues and sources remain unchanged"),
        unchanged_commitments=dict(original_cost_sources=50, matrix_risk_sources=63,
            memory_profile_sources=72, all_hashes_unchanged=True,
            original72_and_matrix18_results_read_only=True,
            all_training_quality_timing_fields_identical_to_original=True),
        merged_analysis=dict(expected_rows=108, treatment=MODEL, controls=list(base.MODELS),
            external_controls=["two_gates", "lif_snn", "transformer"],
            profile_key="study protocol hash plus implementation profile plus registered job",
            matrix_and_vector_panels="always report both; never choose the better backend after results",
            backend_gate="same predeclared targets, both test accuracies reach target and within2pp for all3 paired seeds",
            accounting="original72 counted once; original72 plus matrix18 plus vector18 is108 unique jobs; nested training clocks not added to full worker clocks",
            inference="quality-conditioned descriptive comparisons, not statistical equivalence or architecture-wide superiority"))
    assert len(p["jobs"]) == 18
    assert all(p[key] == matrix[key] == cost[key] for key in ("data", "optimization", "quality", "timing"))
    output.mkdir(parents=True, exist_ok=False)
    base.write(protocol_path, p)
    base.write(output / "REGISTRATION.json", dict(protocol_sha256=base.digest(protocol_path),
        registered_utc=p["registered_utc"], jobs=18, status="before_vector_cost_cohort",
        implementation_profile=PROFILE))
    return p


def worker(protocol, output, job_index):
    original = base.factory
    base.factory = factory
    try:
        return base.worker(protocol, output, job_index)
    finally:
        base.factory = original


def run(protocol, output, public_commit):
    if not re.fullmatch("[0-9a-f]{40}", public_commit or ""):
        raise ValueError("Root-supplied public seal commit required")
    p = base.verify(protocol)
    digest = base.digest(protocol)
    if base.read(output / "REGISTRATION.json")["protocol_sha256"] != digest:
        raise RuntimeError("Registration identity mismatch")
    (output / "runs").mkdir()
    (output / "logs").mkdir()
    base.write(output / "LAUNCH.json", dict(public_commit=public_commit, protocol_sha256=digest,
        started_utc=base.utc(), implementation_profile=PROFILE, command=sys.argv,
        own_host_pid=own_host_pid(), initial_resources=measurement()))
    env = dict(os.environ, OMP_NUM_THREADS="1", MKL_NUM_THREADS="1", OPENBLAS_NUM_THREADS="1",
               NUMEXPR_NUM_THREADS="1", PYTHONDONTWRITEBYTECODE="1")
    initial_oom = oom_counters(measurement())
    records, started, cpu, stopped, last_heartbeat = [], time.perf_counter(), time.process_time(), False, -1e30
    reason = None
    def journal(row):
        with (output / "RESOURCE_JOURNAL.jsonl").open("a") as stream:
            stream.write(json.dumps(dict(utc=base.utc(), **row), sort_keys=True) + "\n")
    for index, job in enumerate(p["jobs"]):
        while True:
            if (output / "STOP_REQUESTED.json").exists():
                stopped, reason = True, "explicit stop request"
                break
            dependency, resources = matrix_terminal(), guarded_resources(p["execution"])
            if oom_counters(resources["resources"]) != initial_oom:
                stopped, reason = True, "new shared cgroup OOM event"
                break
            now = time.perf_counter()
            if now - last_heartbeat >= p["execution"]["heartbeat_seconds"]:
                journal(dict(event="waiting_or_dispatch_check", completed=len(records),
                             matrix_dependency=dependency, guard=resources))
                last_heartbeat = now
            if dependency is not None and resources["allowed"]:
                break
            time.sleep(p["execution"]["poll_seconds"])
        if stopped:
            break
        base.verify(protocol)
        if base.digest(protocol) != digest:
            raise RuntimeError("Protocol changed")
        name = f"{job['task']}__{job['model']}__w{job['width']}d{job['depth']}__{job['seed']}"
        folder, log = output / "runs" / name, output / "logs" / (name + ".log")
        command = [sys.executable, "-m", "experiments.hcsn_risk_vector_cost_v1.study", "worker",
            "--protocol", str(protocol.resolve()), "--output", str(folder.resolve()), "--job-index", str(index)]
        journal(dict(event="dispatch", job=job, command=command, guard=resources, matrix_dependency=dependency))
        wall = time.perf_counter()
        with log.open("xb") as stream:
            process = subprocess.Popen(command, cwd=ROOT, env=env, stdout=stream, stderr=subprocess.STDOUT)
            _, status, usage = os.wait4(process.pid, 0)
            code = os.waitstatus_to_exitcode(status)
            process.returncode = code
        record = dict(job=job, command=command, returncode=code, wall_seconds=time.perf_counter()-wall,
            whole_worker_cpu_seconds=usage.ru_utime+usage.ru_stime, peak_rss_bytes=usage.ru_maxrss*1024,
            directory="runs/"+name, protocol_sha256=digest, stdout_sha256=base.digest(log))
        records.append(record)
        base.write(output / "PROGRESS.json", dict(completed=len(records), expected=18, records=records))
        folder.mkdir(parents=True, exist_ok=True)
        base.write(folder / "EXECUTION.json", record)
        current = measurement()
        stopped = code != 0 or record["peak_rss_bytes"] > p["execution"]["per_worker_peak_budget_bytes"] or oom_counters(current) != initial_oom
        reason = "worker failure, declared peak-memory budget exceedance or new cgroup OOM" if stopped else None
        journal(dict(event="reaped", job=job, returncode=code, peak_rss_bytes=record["peak_rss_bytes"],
                     stopped=stopped, reason=reason, resources=current))
        print(json.dumps(dict(completed=len(records), expected=18, returncode=code, job=job)), flush=True)
        if stopped:
            break
    base.verify(protocol)
    complete = not stopped and len(records) == 18 and all(row["returncode"] == 0 for row in records)
    result = dict(completed=complete, protocol_sha256=digest, records=records, expected=18,
        complete_child_cpu_seconds=sum(row["whole_worker_cpu_seconds"] for row in records),
        coordinator_cpu_seconds=time.process_time()-cpu, wall_seconds=time.perf_counter()-started,
        unstarted=p["jobs"][len(records):], stop_reason=reason)
    base.write(output / ("COMPLETE.json" if complete else "ABORTED.json"), result)
    if not complete:
        raise SystemExit(1)
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("register", "worker", "run"))
    parser.add_argument("--protocol", type=Path, default=PACKAGE / "PROTOCOL.json")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--preflight", type=Path)
    parser.add_argument("--job-index", type=int)
    parser.add_argument("--public-commit")
    args = parser.parse_args()
    if args.action == "register":
        result = register(args.protocol.resolve(), args.output.resolve(), args.preflight.resolve())
        print(json.dumps(dict(protocol_sha256=base.digest(args.protocol), sources=len(result["source_files_sha256"]), jobs=18)))
    elif args.action == "worker":
        try:
            worker(args.protocol, args.output, args.job_index)
        except Exception:
            args.output.mkdir(parents=True, exist_ok=True)
            base.write(args.output / "WORKER_FAILURE.json", dict(traceback=traceback.format_exc()))
            raise
    else:
        run(args.protocol, args.output, args.public_commit)
