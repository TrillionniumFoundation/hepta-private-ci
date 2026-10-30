"""Post-run independent NumPy replay and evidence audit; never selects models."""
import hashlib
import json
from pathlib import Path
import sys
import time

import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT))
from next.common import classification_metrics
from third.memory.execution import atomic_json
from task_flow_20261030.memory import reference
from task_flow_20261030.memory.data import make_suite
from task_flow_20261030.memory.freeze import verify, sha


def main():
    start, cpu_start = time.perf_counter(), time.process_time()
    frozen = verify()
    result = json.loads((HERE / "results.json").read_text())
    validation = json.loads((HERE / "validation.json").read_text())
    freshness = json.loads((HERE / "freshness.json").read_text())
    protocol = result["protocol"]
    if not result["complete"]:
        raise RuntimeError("Training matrix is not complete")
    runs = result["runs"]
    expected = {(t, s, v) for t in protocol["tasks"] for s in protocol["seeds"] for v in protocol["variants"]}
    actual = {(r["task"], r["seed"], r["variant"]) for r in runs}
    evidence = dict(scientific_source_unchanged=result["source_sha256"] == frozen["source_sha256"],
                    pretraining_numerics=validation["passed"] and validation["freeze_sha256"] == result["freeze_sha256"],
                    freshness_audit=freshness["passed"] and not freshness["old_confirmation_constructed"],
                    complete_unique_matrix=actual == expected and len(runs) == len(expected),
                    fixed_update_budget=True, identical_paired_initialization=True,
                    all_candidates_retained=True, validation_only_selection=True,
                    complete_update_logs=True, checkpoint_hashes=True,
                    prediction_hashes=True, data_hashes=True, all_aux_finite=True,
                    delta_radius_satisfied=True, actual_parameter_updates=True,
                    finite_update_logs=True, finite_candidate_parameters=True)
    for task in protocol["tasks"]:
        for seed in protocol["seeds"]:
            group = [r for r in runs if r["task"] == task and r["seed"] == seed]
            evidence["identical_paired_initialization"] &= len({r["initial_parameters_sha256"] for r in group}) == 1
    checks = []
    for row in runs:
        directory = (HERE / row["checkpoint"]).parent
        evidence["checkpoint_hashes"] &= sha(HERE / row["checkpoint"]) == row["checkpoint_sha256"]
        params = dict(np.load(HERE / row["checkpoint"]))
        evidence["all_aux_finite"] &= row["diagnostics"]["all_aux_finite"]
        evidence["actual_parameter_updates"] &= row["training"]["parameters_actually_updated"]
        if row["variant"].endswith("delta"):
            evidence["delta_radius_satisfied"] &= row["diagnostics"]["radius_satisfied"]
        _, suite, fingerprints = make_suite(row["task"], row["seed"], protocol)
        evidence["data_hashes"] &= fingerprints == row["data_sha256"]
        evidence["fixed_update_budget"] &= row["training"]["steps"] == 600 and row["training"]["batch_size"] == 32
        candidates = list(directory.glob("candidate_*.npz"))
        evidence["all_candidates_retained"] &= len(candidates) == 12
        evidence["complete_update_logs"] &= len((directory / "updates.csv").read_text().splitlines()) == 601
        updates = np.loadtxt(directory / "updates.csv", delimiter=",", skiprows=1)
        evidence["finite_update_logs"] &= bool(np.isfinite(updates).all()
            and np.array_equal(updates[:, 0], np.arange(1, 601))
            and np.array_equal(updates[:, 1], np.tile(protocol["training_lengths"], 200)))
        for candidate in candidates:
            with np.load(candidate) as weights:
                evidence["finite_candidate_parameters"] &= all(np.isfinite(weights[k]).all() for k in weights.files)
        best = min(row["history"], key=lambda h: h["validation"]["loss"])
        evidence["validation_only_selection"] &= best["step"] == row["training"]["best_step"]
        selected = dict(np.load(directory / best["checkpoint"]))
        evidence["validation_only_selection"] &= all(np.array_equal(params[k], selected[k]) for k in params)
        for name, dataset in suite.items():
            record = row["predictions"][name]
            evidence["prediction_hashes"] &= sha(HERE / record["path"]) == record["sha256"]
            saved = dict(np.load(HERE / record["path"]))
            predicted = []
            for offset in range(0, len(dataset["y"]), 64):
                predicted.append(reference.forward(params, dataset["x"][offset:offset + 64],
                                                    dataset["dt"][offset:offset + 64], row["variant"]))
            logits = np.concatenate(predicted)
            metrics = classification_metrics(logits, dataset["y"])
            metric_error = max(abs(metrics[k] - row["metrics"][name][k]) for k in metrics)
            logit_error = float(np.max(np.abs(logits - saved["logits"])))
            check = dict(run_id=row["run_id"], split=name, logit_error=logit_error,
                         maximum_metric_error=metric_error,
                         accuracy_exact=metrics["accuracy"] == row["metrics"][name]["accuracy"],
                         labels_exact=bool(np.array_equal(saved["labels"], dataset["y"])),
                         passed=metric_error <= protocol["validation"]["replay_metric_max_error"]
                         and logit_error <= protocol["validation"]["numpy_logit_max_error"])
            checks.append(check)
        print("REPLAY", row["run_id"], len(checks), flush=True)
    output = dict(results_sha256=sha(HERE / "results.json"), audit_source_sha256=sha(__file__),
                  evidence=evidence, checks=checks,
                  passed=all(evidence.values()) and all(c["passed"] and c["labels_exact"] for c in checks),
                  wall_seconds=time.perf_counter() - start, cpu_seconds=time.process_time() - cpu_start,
                  scope="NumPy implements the new recurrence independently; common saved financial table and data generator are shared")
    atomic_json(HERE / "audit.json", output)
    print("AUDIT", output["passed"], len(checks), flush=True)
    if not output["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
