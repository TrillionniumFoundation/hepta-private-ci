"""Measure actual frozen learned/calibrated states separately from physical fanout."""

import argparse
import hashlib
import json
from pathlib import Path
import time

import numpy as np

from calibrated_cell_runtime import CalibratedCellRuntime
from cell_batch_runtime import BatchedCellRuntime
from cell_calibrated_curve import verify_prepared
from cell_learning_models import NumpyCellHead, canonical
from run_calibrated_cells import load_inputs


def physical_predict(runtime, x, sources, identity, calibrators):
    started = time.perf_counter_ns()
    result = runtime.predict(x, source_digests=sources, feature_identity=identity, generation=1)
    raw = result["logits"]
    alpha, bias, center, scale = calibrators.T
    score = alpha * ((raw[:, :, 1] - raw[:, :, 0] - center) / scale) + bias
    positive = 1 / (1 + np.exp(-np.clip(score, -700, 700)))
    probability = np.stack((1-positive, positive), axis=2)
    return probability, time.perf_counter_ns() - started


def probe(dataset, features, study, output, *, repetitions=7):
    if not 3 <= repetitions <= 21:
        raise ValueError("bounded timing repetitions required")
    data, matrix, receipt, _, _ = load_inputs(dataset, features)
    study = Path(study)
    summary = json.loads((study / "summary.json").read_bytes())
    if summary["plan"]["feature_identity"] != receipt["feature_identity"]:
        raise ValueError("completed study must bind the exact feature identity")
    selection = json.loads((study / "selection-seal.json").read_bytes())
    for relative, digest in selection["seals"].items():
        if hashlib.sha256((study / relative).read_bytes()).hexdigest() != digest:
            raise ValueError("task selection changed")
    holdout = [i for i, row in enumerate(data["rows"]) if row["split"] == "holdout"][:16]
    if not holdout:
        raise ValueError("fixed heldout input rows required for serving probe")
    x = matrix[holdout]
    sources = [hashlib.sha256(canonical({"source_id": data["rows"][i]["source_id"],
               "dataset_sha256": receipt["plan"]["dataset_sha256"],
               "feature_tensor_sha256": hashlib.sha256(matrix[i].tobytes()).hexdigest()})).hexdigest() for i in holdout]
    plans = []
    for task in summary["tasks_evaluated"]:
        prepared = study / task / "prepared"
        frozen = verify_prepared(prepared)
        available = [r for r in frozen["runs"] if r["seed"] == 7]
        if available:
            plans.append((task, prepared, max(available, key=lambda run: run["budget"])))
    if not plans:
        raise ValueError("no genuinely trained task state available")
    root = Path(output)
    root.mkdir(parents=True, exist_ok=False)
    report = {"schema": "hepta.calibrated-serving-probe.v1", "feature_identity": receipt["feature_identity"],
              "dataset_sha256": receipt["plan"]["dataset_sha256"], "source_ids": [data["rows"][i]["source_id"] for i in holdout],
              "tasks": [task for task, _, _ in plans], "selection": "seed7, largest predeclared available budget per task",
              "encoder_instances_owned": 0, "encoder_forwards": 0, "repetitions": repetitions,
              "timing_scope": "shared CPU process; model encoding may run concurrently; not isolated hardware capacity",
              "new_tasks_inferred_from_physical_cells": False, "conditions": []}
    identity = receipt["feature_identity"]
    for mode in ("linear", "gated", "residual"):
        heads = [NumpyCellHead.load(prepared / run["arms"][mode]["artifact"], identity) for _, prepared, run in plans]
        fits = [run["arms"][mode]["calibration"] for _, _, run in plans]
        for count in (64, 256, 1024):
            indices = [i % len(heads) for i in range(count)]
            physical = [heads[i] for i in indices]
            calibrators = [fits[i] for i in indices]
            ids, tasks = [f"cell-{i}" for i in range(count)], [plans[i][0] for i in indices]
            unique = CalibratedCellRuntime(physical, calibrators, ids, tasks, identity)
            reference = BatchedCellRuntime(physical, ids, tasks, identity)
            values = np.array([[fit[k] for k in ("alpha", "bias", "center", "scale")] for fit in calibrators])
            # One untimed warm-up; every timed result is independently compared.
            unique.predict(x, source_digests=sources, feature_identity=identity, generation=1)
            physical_predict(reference, x, sources, identity, values)
            times = {"unique": [], "physical": []}
            for repeat in range(repetitions):
                order = ("unique", "physical") if repeat % 2 else ("physical", "unique")
                results = {}
                for kind in order:
                    if kind == "unique":
                        result = unique.predict(x, source_digests=sources, feature_identity=identity, generation=1)
                        results[kind], elapsed = result["probabilities"], result["elapsed_ns"]
                    else:
                        results[kind], elapsed = physical_predict(reference, x, sources, identity, values)
                    times[kind].append(elapsed)
                if not np.array_equal(results["unique"], results["physical"]):
                    raise ValueError("calibrated fanout differs from actual full physical dispatch")
            report["conditions"].append({"mode": mode, "physical_cells": count,
                "task_count": len(set(tasks)), "state_budgets": {task: run["budget"] for task, _, run in plans},
                "unique_accounting": unique.accounting(), "physical_accounting": reference.accounting(),
                "physical_calibration_tensor_bytes": values.nbytes,
                "probabilities_bitwise_equal_all_repetitions": True, "task_route_coverage": 1.0,
                "timings_ns": times,
                "p50_ns": {key: float(np.median(value)) for key, value in times.items()},
                "p95_ns": {key: float(np.percentile(value, 95)) for key, value in times.items()}})
    (root / "report.json").write_bytes(canonical(report) + b"\n")
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("dataset", "features", "study", "output"):
        parser.add_argument("--" + name, required=True)
    parser.add_argument("--repetitions", type=int, default=7)
    result = probe(**vars(parser.parse_args()))
    print(json.dumps({"tasks": len(result["tasks"]), "conditions": len(result["conditions"]),
                      "all_probabilities_bitwise_equal": all(x["probabilities_bitwise_equal_all_repetitions"] for x in result["conditions"])}))
