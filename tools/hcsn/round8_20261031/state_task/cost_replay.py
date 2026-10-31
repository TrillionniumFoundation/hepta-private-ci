"""Current-host NumPy serving costs for every frozen confirmation regime.

This is a new backend timing study of previously validated frozen predictors.
It neither replaces the historical PyTorch timings nor creates new efficacy
samples. Deployment receives history, lengths and query only.
"""

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import platform
import sys
import time

import numpy as np
import scipy

from .replay import HERE, predict


REGIMES = ("iid", "long_history", "low_noise", "moving_boundary")


def execute(family, state, history, lengths, query):
    # predict includes float32 input rounding, conversion to NumPy float64,
    # all observed features, and the complete predictor. Parameters are already
    # NumPy arrays, so it does not parse/convert serialized weights per call.
    lengths = np.asarray(lengths, dtype=np.int64)
    probability = predict(family, state, history, lengths, query)
    return json.dumps({"risk": probability.tolist(),
        "protect": (probability >= query[:, 4]).tolist()}, allow_nan=False)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--reviewed-replay", type=Path,
        default=HERE / "evidence/RECOVERY_REPLAY_REVIEWED_20261031.json")
    args = parser.parse_args()
    source_protocol = json.loads((HERE / "protocol.json").read_text())
    receipt = json.loads(args.reviewed_replay.read_text())
    manifest_path = HERE.parent / "bundles/state_task.json"
    identity = {"replay_source_sha256": hashlib.sha256((HERE / "replay.py").read_bytes()).hexdigest(),
        "amendment_sha256": hashlib.sha256((HERE / "CONFIRMATION_AMENDMENT.json").read_bytes()).hexdigest(),
        "evidence_manifest_sha256": hashlib.sha256(manifest_path.read_bytes()).hexdigest()}
    if not receipt["passed"] or not receipt["all_actions_identical"] or receipt["audit_identity"] != identity:
        raise ValueError("a source-matched reviewed forward replay is required")
    freeze = json.loads((HERE / "FREEZE.json").read_text())
    for name, sha in freeze["source_and_checkpoint_sha256"].items():
        if hashlib.sha256((HERE / name).read_bytes()).hexdigest() != sha:
            raise ValueError("frozen source/checkpoint changed: " + name)
    manifest = json.loads(manifest_path.read_text())
    for name, meta in manifest["files"].items():
        data = (HERE.parent / name).read_bytes()
        if len(data) != meta["bytes"] or hashlib.sha256(data).hexdigest() != meta["sha256"]:
            raise ValueError("archived evidence changed: " + name)
    paths = {label: args.output.with_name(args.output.stem+suffix)
        for label, suffix in (("protocol", "_PROTOCOL.json"), ("raw", "_RAW.jsonl"))}
    if any(p.exists() for p in [args.output, *paths.values()]):
        raise FileExistsError("new cost outputs must not exist")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    model_ids = [f"{family}_{seed}" for family in source_protocol["models"]
        for seed in source_protocol["model_seeds"]]+["fixed_ordinary_filter"]
    protocol = {"schema": "hepta.r8.numpy-serving-cost-protocol.v1",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "regimes": list(REGIMES), "model_ids": model_ids,
        "batch_repeats": 9, "batch_examples": 2048, "scalar_examples": 64,
        "order_seed": 2026103109,
        "schedule": "Each repeat includes every model once in every regime; regime and model order are independently permuted. Each scalar index is executed once per model and regime.",
        "summary": "Per-checkpoint median cost per example, then arithmetic mean across the three trained seeds; exact control has one implementation.",
        "backend": "NumPy float64 forward with float32-rounded inputs and frozen PyTorch float32 weights exported as JSON",
        "timed_scope": "Input array preparation, every observed feature, predictor, protective action and output JSON; scalar slicing included.",
        "separate_scope": "Checkpoint loading, fixture loading, warmup/forward checks and audit serialization are separately recorded, not hidden in serving throughput.",
        "not_measured": ["energy", "native durable recovery", "complete Hepta application", "new training", "new confirmation examples"],
        "source_sha256": {name:hashlib.sha256((HERE / name).read_bytes()).hexdigest()
            for name in ("replay.py", "cost_replay.py", "data.py", "protocol.json", "FREEZE.json", "CONFIRMATION_AMENDMENT.json")},
        "reviewed_replay_sha256": hashlib.sha256(args.reviewed_replay.read_bytes()).hexdigest(),
        "evidence_manifest_sha256": identity["evidence_manifest_sha256"],
        "environment": {"python": sys.version.split()[0], "numpy": np.__version__,
            "scipy": scipy.__version__, "platform": platform.platform(),
            "thread_environment": {name:os.environ.get(name) for name in
                ("OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS", "MKL_NUM_THREADS")}}}
    with paths["protocol"].open("x") as stream:
        json.dump(protocol, stream, indent=2, sort_keys=True)
        stream.write("\n")
    total_cpu, total_wall = time.process_time_ns(), time.perf_counter_ns()
    models, model_loads = {}, []
    for key in model_ids:
        cpu, wall = time.process_time_ns(), time.perf_counter_ns()
        if key == "fixed_ordinary_filter":
            family, state, sha = key, {}, None
        else:
            family = key.rsplit("_", 1)[0]
            path = HERE / "evidence/models" / (key+".json")
            saved = json.loads(path.read_text())
            state = {name:np.asarray(value, dtype=float) for name,value in saved["state"].items()}
            sha = freeze["source_and_checkpoint_sha256"][str(path.relative_to(HERE))]
        models[key] = (family, state)
        model_loads.append({"model": key, "cpu_ns": time.process_time_ns()-cpu,
            "wall_ns": time.perf_counter_ns()-wall, "checkpoint_sha256": sha,
            "parameter_bytes": sum(value.nbytes for value in state.values())})
    inputs, fixture_loads = {}, []
    for regime in REGIMES:
        cpu, wall = time.process_time_ns(), time.perf_counter_ns()
        with np.load(HERE / "evidence/data" / (regime+".npz"), allow_pickle=False) as stored:
            inputs[regime] = tuple(stored[name] for name in ("history", "lengths", "query"))
        fixture_loads.append({"regime": regime, "cpu_ns": time.process_time_ns()-cpu,
            "wall_ns": time.perf_counter_ns()-wall})
        if len(inputs[regime][0]) != protocol["batch_examples"]:
            raise ValueError("fixed batch budget differs")
    warmup_cpu, checks = time.process_time_ns(), []
    for regime in REGIMES:
        with np.load(HERE / "evidence" / (regime+"_raw_predictions.npz"), allow_pickle=False) as stored:
            for key in model_ids:
                result = json.loads(execute(*models[key], *inputs[regime]))
                actual, expected = np.asarray(result["risk"]), stored[key]
                difference = float(np.max(np.abs(actual-expected)))
                if not np.all(np.isfinite(actual)) or difference > 3e-6:
                    raise AssertionError("preloaded NumPy predictor differs: "+key)
                actions = expected >= inputs[regime][2][:, 4]
                if not np.array_equal(result["protect"], actions):
                    raise AssertionError("preloaded NumPy actions differ: "+key)
                checks.append({"regime": regime, "model": key,
                    "max_abs_prediction_difference": difference, "action_differences": 0})
    warmup_cpu = time.process_time_ns()-warmup_cpu
    rng, rows = np.random.default_rng(protocol["order_seed"]), []
    with paths["raw"].open("x") as raw:
        for workload, count in (("batch", protocol["batch_repeats"]), ("scalar", protocol["scalar_examples"])):
            for repeat in range(count):
                for regime in rng.permutation(REGIMES):
                    for order, key in enumerate(rng.permutation(model_ids)):
                        cpu, wall = time.process_time_ns(), time.perf_counter_ns()
                        sample = inputs[regime] if workload == "batch" else tuple(x[repeat:repeat+1] for x in inputs[regime])
                        output = execute(*models[key], *sample)
                        cpu_elapsed, wall_elapsed = time.process_time_ns()-cpu, time.perf_counter_ns()-wall
                        row = {"regime": str(regime), "model": str(key), "workload": workload,
                            "repeat": repeat, "order": order, "examples": len(sample[0]),
                            "cpu_ns": cpu_elapsed,
                            "wall_ns": wall_elapsed, "output_bytes": len(output)}
                        rows.append(row)
                        raw.write(json.dumps(row, separators=(",", ":"))+"\n")
    expected_keys = {(regime, key, workload, repeat) for regime in REGIMES for key in model_ids
        for workload,count in (("batch", 9), ("scalar", 64)) for repeat in range(count)}
    actual_keys = {(row["regime"], row["model"], row["workload"], row["repeat"]) for row in rows}
    if len(rows) != len(expected_keys) or actual_keys != expected_keys:
        raise AssertionError("balanced timing coverage differs")
    summary, individual = {}, []
    for regime in REGIMES:
        summary[regime] = {}
        for family in source_protocol["models"]+["fixed_ordinary_filter"]:
            members = [f"{family}_{seed}" for seed in source_protocol["model_seeds"]] if family != "fixed_ordinary_filter" else [family]
            summary[regime][family] = {}
            for workload in ("batch", "scalar"):
                cpu_values, wall_values = [], []
                for key in members:
                    selected = [r for r in rows if (r["regime"],r["model"],r["workload"]) == (regime,key,workload)]
                    cpu = float(np.median([r["cpu_ns"]/r["examples"] for r in selected]))/1e9
                    wall = float(np.median([r["wall_ns"]/r["examples"] for r in selected]))/1e9
                    cpu_values.append(cpu)
                    wall_values.append(wall)
                    individual.append({"regime": regime, "model": key, "workload": workload,
                        "repeats": len(selected), "cpu_seconds_per_example": cpu,
                        "wall_seconds_per_example": wall})
                summary[regime][family][workload] = {"cpu_seconds_per_example": float(np.mean(cpu_values)),
                    "wall_seconds_per_example": float(np.mean(wall_values))}
    for name, sha in protocol["source_sha256"].items():
        if hashlib.sha256((HERE/name).read_bytes()).hexdigest() != sha:
            raise ValueError("source changed during timing: "+name)
    report = {"schema": "hepta.r8.numpy-serving-cost.v1", "completed": True,
        "protocol_file": paths["protocol"].name, "protocol_sha256": hashlib.sha256(paths["protocol"].read_bytes()).hexdigest(),
        "raw_file": paths["raw"].name, "raw_sha256": hashlib.sha256(paths["raw"].read_bytes()).hexdigest(),
        "raw_rows": len(rows), "expected_raw_rows": len(expected_keys), "balanced_coverage_verified": True,
        "model_loads": model_loads, "fixture_loads": fixture_loads,
        "warmup_and_forward_check_cpu_ns": warmup_cpu, "forward_checks": checks,
        "summary": summary, "individual_medians": individual,
        "campaign_cpu_seconds": (time.process_time_ns()-total_cpu)/1e9,
        "campaign_wall_seconds": (time.perf_counter_ns()-total_wall)/1e9,
        "source_unchanged": True, "new_confirmation_examples": 0,
        "original_pytorch_timings_replaced": False, "production_activation": False,
        "interpretation": "Descriptive current-host NumPy serving costs per regime, with identical frozen actions. Neither original PyTorch timings nor a new training/quality trial. Load, warmup and fixture costs are separate; native recovery and energy remain outside this track."}
    with args.output.open("x") as stream:
        json.dump(report, stream, indent=2, sort_keys=True, allow_nan=False)
        stream.write("\n")
    print(json.dumps({"completed": True, "raw_rows": len(rows), "summary": summary,
        "campaign_cpu_seconds": report["campaign_cpu_seconds"],
        "output_bytes": sum(p.stat().st_size for p in [args.output,*paths.values()])}, indent=2))


if __name__ == "__main__":
    main()
