"""Paid-feedback execution with private broker and subsequent separate scorer."""

import argparse
import gzip
import json
import os
from pathlib import Path
import resource
import subprocess
import sys
import time

import numpy as np

from ..native_adapter import Native
from ..round3 import feedback as previous
from ..round4.runtime_evidence import EvidenceZip, write_json
from ..round4.runtime_owner import Owner, ZERO, file_sha
from ..runtime import digest
from .continuation import action_values
from .data import ARMS, DATA_OFFSET, DOMAINS, LEARNED, SEEDS, SMOKE_OFFSET, SMOKE_SEED
from .data import dataset, load_data, native_paths
from .learning import law, noise_scale, prepare_seed


def configuration(seed, domain, n, smoke):
    if type(smoke) is not bool or type(n) is not int or n < 1 or domain not in DOMAINS:
        raise ValueError("Explicit declared execution configuration required")
    if smoke:
        if seed != SMOKE_SEED or n > 8 or domain != "nominal":
            raise ValueError("Smoke cannot execute a formal seed, distribution or size")
    elif seed not in SEEDS or n != 128:
        raise ValueError("Formal confirmation requires registered seed and row count")


def verify_scope(run_dir, seed, domain, n, expected_freeze_sha256, smoke):
    configuration(seed, domain, n, smoke)
    if smoke:
        if expected_freeze_sha256 is not None or any((Path(run_dir) / name).exists()
                for name in ("PREPARING.json", "PREPARED.json", "FREEZE.json")):
            raise ValueError("Smoke and formal frozen namespaces cannot be combined")
    else:
        if not isinstance(expected_freeze_sha256, str) or len(expected_freeze_sha256) != 64:
            raise ValueError("Independently expected freeze SHA256 is mandatory")
        from .lifecycle import verify
        verify(run_dir, expected_freeze_sha256)


def output_path(run_dir, seed, domain):
    return Path(run_dir) / "confirmation" / f"seed_{seed}" / domain


def select_action(model, arm, public, received, native, case, stage):
    values = action_values(received["conditional_law"], public, noise_scale(model, arm))
    vector, actual = previous.feature(public, received, arm, model["calibration"], native,
                                     case + f"/stage{stage}/{arm}") if arm in LEARNED else (None, [])
    repair = values["repair_gain"] if vector is None else (
        float(np.dot(vector, model["heads"][arm]["weights"])) + model["heads"][arm]["offset"])
    scores = {"stop": 0.0, "repair": repair}
    if stage == 0:
        scores["wait"] = values["wait_gain"]
    return max(scores, key=scores.get), values, scores, vector, actual


def worker(run_dir, seed, domain, expected_freeze_sha256=None, *, n=128, smoke=False):
    from .broker import Broker
    verify_scope(run_dir, seed, domain, n, expected_freeze_sha256, smoke)
    output = output_path(run_dir, seed, domain)
    model_path = Path(run_dir) / "prepared" / f"seed_{seed}" / "MODELS.json"
    model = json.loads(model_path.read_text())
    job = json.loads((output / "JOB.json").read_text())
    if (job["model_sha256"] != file_sha(model_path) or model["namespace"] != ("smoke" if smoke else "registered")
            or job["seed"] != seed or job["domain"] != domain or job["rows"] != n
            or job["expected_freeze_sha256"] != expected_freeze_sha256
            or job["namespace"] != model["namespace"]):
        raise ValueError("Worker job/model namespace identity mismatch")
    archive, rows = EvidenceZip(output / "execution.zip"), []
    rng = np.random.default_rng((SMOKE_OFFSET if smoke else DATA_OFFSET) + 1000 * seed
                                + 100 * DOMAINS.index(domain) + 99)
    started, cpu = time.perf_counter_ns(), time.process_time_ns()
    original_load = np.load

    def deny_private_load(*args, **kwargs):
        raise RuntimeError("Policy worker cannot load data arrays; use the paid broker")

    np.load = deny_private_load
    try:
        with Native(*native_paths(run_dir)) as native, Broker(
                output / "DATA.npz", output / "broker", "runtime6_confirmation") as broker:
            if model["native_binary_sha256"] != native.receipt["binary_sha256"]:
                raise ValueError("Policy model/native executable identity mismatch")
            for i in range(n):
                for selected in rng.permutation(ARMS):
                    arm = str(selected)
                    case_started, case_cpu = time.perf_counter_ns(), time.process_time_ns()
                    before_calls, before_ticks, before_ipc = native.calls, native.original_sparse_ticks, native.wall_ns
                    public = broker.start(i, arm)
                    directory, case = broker.case_dir, broker.case_id
                    mode = arm if arm in ("event", "direct", "float") else (
                        "float" if arm in ("gaussian", "probit", "uncalibrated") else "event")
                    owner = Owner(directory / "owners", [case, arm], digest(model), native, mode)
                    stages, checkpoint, expected_cost = [], ZERO, 0.0
                    for stage in range(2):
                        if stage:
                            public = broker.wait()
                        receipt = owner.step(public, law(model, public, arm), stage + 1,
                                             expected_checkpoint=checkpoint)
                        checkpoint, received = receipt["checkpoint_after"], receipt["law"]
                        choice, values, scores, vector, actual = select_action(
                            model, arm, public, received, native, str(case), stage)
                        stages.append({"public": public, "runtime": receipt, "values": values,
                            "scores": scores, "feature": None if vector is None else vector.tolist(),
                            "native": actual, "action": choice, "decision_ns": time.perf_counter_ns()})
                        expected_cost += public["wait_cost"] if choice == "wait" else (
                            public["repair_cost"] if choice == "repair" else 0.0)
                        if choice != "wait":
                            break
                    delivered = broker.finish(choice, values["repair_amount"] if choice == "repair" else 0.0)
                    if abs(delivered["cost"] - expected_cost) > 1e-12:
                        raise ValueError("Actual paid broker cost differs from the chosen actions")
                    row = {"index": i, "case": case, "arm": arm, "stages": stages,
                        "actions": [s["action"] for s in stages], **delivered,
                        "wall_ns": time.perf_counter_ns() - case_started,
                        "cpu_ns": time.process_time_ns() - case_cpu,
                        "packet_bytes": sum(s["runtime"]["packet_bytes"] for s in stages),
                        "native_requests": native.calls - before_calls,
                        "native_ticks": native.original_sparse_ticks - before_ticks,
                        "native_roundtrip_ns": native.wall_ns - before_ipc}
                    archive_started = time.perf_counter_ns()
                    archive.append(directory, f"case-{i}/{arm}")
                    row["evidence_archive_wall_ns"] = time.perf_counter_ns() - archive_started
                    rows.append(row)
            broker_receipt = broker.close()
            if not broker_receipt["complete"] or broker_receipt["finished_cases"] != n * len(ARMS):
                raise ValueError("All paid broker cases must finish before accepting a worker")
            costs = {"requests": native.calls, "ticks": native.original_sparse_ticks,
                     "roundtrip_ns": native.wall_ns}
    finally:
        np.load = original_load
    with gzip.open(output / "PUBLIC_ROWS.json.gz", "xt") as stream:
        json.dump(rows, stream, sort_keys=True, separators=(",", ":"), allow_nan=False)
    receipt = {"schema": "hepta.paid-feedback.worker.v6", "pid": os.getpid(),
        "archive": archive.finish(), "native": costs, "broker": broker_receipt,
        "broker_pid": broker.process.pid, "executions": len(rows),
        "model_sha256": file_sha(model_path), "job_sha256": file_sha(output / "JOB.json"),
        "public_rows_sha256": file_sha(output / "PUBLIC_ROWS.json.gz"),
        "wall_ns": time.perf_counter_ns() - started, "cpu_ns": time.process_time_ns() - cpu,
        "private_array_loads_denied_in_policy_process": True,
        "future_observation_only_returned_after_wait": True,
        "same_uid_hostile_isolation_claimed": False, "production_promotion": False}
    write_json(output / "WORKER.json", receipt)
    return receipt


def score(run_dir, seed, domain, expected_freeze_sha256=None, *, n=128, smoke=False):
    verify_scope(run_dir, seed, domain, n, expected_freeze_sha256, smoke)
    output = output_path(run_dir, seed, domain)
    completed = json.loads((output / "WORKER_COMPLETED.json").read_text())
    if completed["returncode"] != 0:
        raise ValueError("Scoring requires a successfully terminated policy process")
    worker_receipt = json.loads((output / "WORKER.json").read_text())
    if worker_receipt["pid"] == os.getpid():
        raise ValueError("Scoring must occur in a different process after policy completion")
    if worker_receipt["public_rows_sha256"] != file_sha(output / "PUBLIC_ROWS.json.gz"):
        raise ValueError("Policy rows differ from completed worker receipt")
    with gzip.open(output / "PUBLIC_ROWS.json.gz", "rt") as stream:
        rows = json.load(stream)
    expected_pairs = {(i, arm) for i in range(n) for arm in ARMS}
    if len(rows) != len(expected_pairs) or {(r["index"], r["arm"]) for r in rows} != expected_pairs:
        raise ValueError("Every declared trajectory/arm must have one completed execution")
    target_read_started_ns = time.perf_counter_ns()
    if target_read_started_ns <= max(r["final_readback_ns"] for r in rows):
        raise ValueError("Scoring started before final delivery readback")
    data = load_data(output / "DATA.npz")
    job = json.loads((output / "JOB.json").read_text())
    if (job["data_sha256"] != file_sha(output / "DATA.npz") or len(data["target"]) != n
            or data["seed"] != seed or data["domain"] != domain or data["split"] != "confirmation"):
        raise ValueError("Private data identity differs from the registered execution job")
    for row in rows:
        target = float(data["target"][row["index"]])
        row.update(target=target, squared_error=(row["delivered"] - target) ** 2,
                   utility=1 - (row["delivered"] - target) ** 2 - row["cost"],
                   score_started_ns=time.perf_counter_ns())
    with gzip.open(output / "ROWS.json.gz", "xt") as stream:
        json.dump(rows, stream, sort_keys=True, separators=(",", ":"), allow_nan=False)
    keys = ("utility", "squared_error", "cost", "wall_ns", "cpu_ns", "packet_bytes",
            "native_requests", "native_ticks", "native_roundtrip_ns", "evidence_archive_wall_ns")
    summary = {arm: {key: float(np.mean([r[key] for r in rows if r["arm"] == arm]))
                     for key in keys} for arm in ARMS}
    report = {"schema": "hepta.paid-feedback.scoring.v6", "seed": seed, "domain": domain,
        "namespace": "smoke" if smoke else "registered", "independent_trajectories": n,
        "executions": len(rows), "summary": summary, "worker": worker_receipt,
        "scorer_pid": os.getpid(), "target_read_started_ns": target_read_started_ns,
        "data_sha256": file_sha(output / "DATA.npz"), "rows_sha256": file_sha(output / "ROWS.json.gz"),
        "policy_process_does_not_load_private_target": True,
        "private_data_generated_before_policy_and_scored_after_policy": True,
        "production_promotion": False}
    write_json(output / "SUMMARY.json", report)
    return report


def invoke(output, role, command):
    started, before = time.perf_counter_ns(), resource.getrusage(resource.RUSAGE_CHILDREN)
    write_json(output / (role + "_STARTED.json"), {"command": command, "started_ns": started})
    completed = subprocess.run(command, capture_output=True, text=True)
    after = resource.getrusage(resource.RUSAGE_CHILDREN)
    (output / (role + ".stdout.log")).write_text(completed.stdout)
    (output / (role + ".stderr.log")).write_text(completed.stderr)
    receipt = {"command": command, "returncode": completed.returncode,
        "wall_ns": time.perf_counter_ns() - started,
        "children_user_seconds": after.ru_utime - before.ru_utime,
        "children_system_seconds": after.ru_stime - before.ru_stime,
        "native_energy": None, "financial_cost": None}
    write_json(output / (role + "_COMPLETED.json"), receipt)
    if completed.returncode:
        raise RuntimeError(role + " failed; partial evidence retained: " + completed.stderr[-4000:])
    return receipt


def confirm_seed(run_dir, seed, domain, expected_freeze_sha256=None, *, n=128, smoke=False):
    verify_scope(run_dir, seed, domain, n, expected_freeze_sha256, smoke)
    output = output_path(run_dir, seed, domain)
    output.mkdir(parents=True, exist_ok=False)
    started, cpu = time.perf_counter_ns(), time.process_time_ns()
    data = dataset(seed, n, "confirmation", domain, smoke=smoke)
    np.savez_compressed(output / "DATA.npz", **data)
    model_path = Path(run_dir) / "prepared" / f"seed_{seed}" / "MODELS.json"
    write_json(output / "JOB.json", {"seed": seed, "domain": domain, "rows": n,
        "namespace": "smoke" if smoke else "registered", "data_sha256": file_sha(output / "DATA.npz"),
        "model_sha256": file_sha(model_path), "expected_freeze_sha256": expected_freeze_sha256})
    arguments = ["--run-dir", str(Path(run_dir).resolve()), "--seed", str(seed),
                 "--domain", domain, "--count", str(n)]
    arguments += ["--smoke"] if smoke else ["--expected-freeze-sha256", expected_freeze_sha256]
    execution = {}
    for role in ("worker", "score"):
        execution[role] = invoke(output, role.upper(), [sys.executable, "-m",
            "experiments.analytic_event_neuron.round6.study", role, *arguments])
    verify_scope(run_dir, seed, domain, n, expected_freeze_sha256, smoke)
    receipt = {"schema": "hepta.paid-feedback.confirmation.v6", "seed": seed, "domain": domain,
        "namespace": "smoke" if smoke else "registered", "execution": execution,
        "summary_sha256": file_sha(output / "SUMMARY.json"),
        "wall_ns": time.perf_counter_ns() - started, "parent_cpu_ns": time.process_time_ns() - cpu,
        "nested_component_times_must_not_be_added": True, "production_promotion": False}
    write_json(output / "RUN_COMPLETED.json", receipt)
    return receipt


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=("prepare", "confirm", "worker", "score"))
    parser.add_argument("--run-dir", required=True)
    parser.add_argument("--seed", required=True, type=int)
    parser.add_argument("--domain", choices=DOMAINS, default="nominal")
    parser.add_argument("--count", type=int, default=128)
    parser.add_argument("--expected-freeze-sha256")
    parser.add_argument("--smoke", action="store_true")
    args = parser.parse_args()
    if args.operation == "prepare":
        result = prepare_seed(args.run_dir, args.seed, 24 if args.smoke else 256,
                              12 if args.smoke else 128, smoke=args.smoke)
    else:
        function = {"confirm": confirm_seed, "worker": worker, "score": score}[args.operation]
        result = function(args.run_dir, args.seed, args.domain, args.expected_freeze_sha256,
                          n=args.count, smoke=args.smoke)
    print(json.dumps({"operation": args.operation, "seed": args.seed,
                      "schema": result["schema"], "completed": True}), flush=True)


if __name__ == "__main__":
    main()
