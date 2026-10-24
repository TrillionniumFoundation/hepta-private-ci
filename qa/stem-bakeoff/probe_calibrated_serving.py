"""Measure actual frozen learned/calibrated states separately from physical fanout."""

import argparse
import hashlib
import json
from pathlib import Path
import resource
import time

import numpy as np

from calibrated_cell_runtime import CalibratedCellRuntime
from cell_batch_runtime import BatchedCellRuntime
from cell_calibrated_curve import verify_prepared
from cell_learning_models import NumpyCellHead, canonical
from run_calibrated_cells import load_inputs

CODE_FILES = (
    "probe_calibrated_serving.py", "calibrated_cell_runtime.py", "cell_batch_runtime.py",
    "cell_learning_models.py", "cell_learning_metrics.py", "cell_calibrated_curve.py",
    "run_calibrated_cells.py", "real_cell_features.py",
)


def sha_file(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def array_digest(value):
    return hashlib.sha256(canonical([list(value.shape), value.dtype.str]) + value.tobytes()).hexdigest()


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
    began, cpu = time.perf_counter_ns(), time.process_time_ns()
    if not 3 <= repetitions <= 21:
        raise ValueError("bounded timing repetitions required")
    study = Path(study)
    source_pins = {name: sha_file(Path(__file__).with_name(name)) for name in CODE_FILES}
    inputs = [Path(dataset), Path(features)/"report.json", Path(features)/"features.npz"]
    inputs += [study/name for name in ("study-plan.json", "summary.json", "selection-seal.json")]
    input_pins = {str(path.resolve()): sha_file(path) for path in inputs}
    data, matrix, receipt, _, _ = load_inputs(dataset, features)
    summary = json.loads((study / "summary.json").read_bytes())
    study_plan = json.loads((study / "study-plan.json").read_bytes())
    if (summary["plan"] != study_plan or study_plan["feature_identity"] != receipt["feature_identity"]
            or study_plan["dataset_sha256"] != input_pins[str(Path(dataset).resolve())]
            or study_plan["feature_receipt_sha256"] != input_pins[str((Path(features)/"report.json").resolve())]):
        raise ValueError("completed study must bind the exact dataset and feature receipt")
    selection = json.loads((study / "selection-seal.json").read_bytes())
    for relative, digest in selection["seals"].items():
        if sha_file(study / relative) != digest:
            raise ValueError("task selection changed")
        input_pins[str((study/relative).resolve())] = digest
    holdout = [i for i, row in enumerate(data["rows"]) if row["split"] == "holdout"][:16]
    if not holdout:
        raise ValueError("fixed heldout input rows required for serving probe")
    x = matrix[holdout]
    sources = [hashlib.sha256(canonical({"source_id": data["rows"][i]["source_id"],
               "dataset_sha256": receipt["plan"]["dataset_sha256"],
               "feature_tensor_sha256": hashlib.sha256(matrix[i].tobytes()).hexdigest()})).hexdigest() for i in holdout]
    plans, frozen_inputs = [], {}
    for task in summary["tasks_evaluated"]:
        prepared = study / task / "prepared"
        frozen = verify_prepared(prepared)
        frozen_inputs[task] = frozen
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
              "new_tasks_inferred_from_physical_cells": False, "conditions": [],
              "instrumentation_version": 2, "source_code_sha256": source_pins,
              "input_files_sha256": input_pins, "source_digests": sources,
              "selected_feature_array_sha256": array_digest(x), "head_state_bindings": {}}
    identity = receipt["feature_identity"]
    for mode in ("linear", "gated", "residual"):
        heads = [NumpyCellHead.load(prepared / run["arms"][mode]["artifact"], identity) for _, prepared, run in plans]
        fits = [run["arms"][mode]["calibration"] for _, _, run in plans]
        report["head_state_bindings"][mode] = [
            {"task": task, "budget": run["budget"], "parameter_digest": head.digest(),
             "artifact": str((prepared/run["arms"][mode]["artifact"]).resolve()),
             "calibration_sha256": hashlib.sha256(canonical(fit)).hexdigest()}
            for (task, prepared, run), head, fit in zip(plans, heads, fits, strict=True)]
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
            times, output_digests = {"unique": [], "physical": []}, []
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
                output_digests.append(array_digest(results["unique"]))
            report["conditions"].append({"mode": mode, "physical_cells": count,
                "task_count": len(set(tasks)), "state_budgets": {task: run["budget"] for task, _, run in plans},
                "unique_accounting": unique.accounting(), "physical_accounting": reference.accounting(),
                "physical_calibration_tensor_bytes": values.nbytes,
                "probabilities_bitwise_equal_all_repetitions": True, "task_route_coverage": 1.0,
                "output_probability_sha256_each_repetition": output_digests,
                "timings_ns": times,
                "p50_ns": {key: float(np.median(value)) for key, value in times.items()},
                "p95_ns": {key: float(np.percentile(value, 95)) for key, value in times.items()}})
    raw_path = root / "measurement-report.json"
    raw_bytes = canonical(report) + b"\n"
    raw_path.write_bytes(raw_bytes)
    if (any(sha_file(path) != digest for path, digest in input_pins.items())
            or any(sha_file(Path(__file__).with_name(name)) != digest for name, digest in source_pins.items())
            or any(verify_prepared(study/task/"prepared") != frozen for task, frozen in frozen_inputs.items())
            or raw_path.read_bytes() != raw_bytes):
        raise ValueError("source, numerical code, learned state or persisted measurement changed during serving")
    report["measurement_report_sha256"] = hashlib.sha256(raw_bytes).hexdigest()
    report["inclusive_probe"] = {"wall_ns": time.perf_counter_ns()-began,
        "cpu_ns": time.process_time_ns()-cpu,
        "scope": "input/code verification and loading, all setup, warmups, physical/unique repetitions, parity and output hashes, measurement artifact write and final input/output verification; excludes final cost receipt and manifest writes; nested samples are not additional cost"}
    report["process_peak_rss_bytes"] = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss*1024
    report["rss_scope"] = "whole process high-water, not incremental serving storage or simultaneous multi-process RSS"
    (root / "report.json").write_bytes(canonical(report) + b"\n")
    manifest = {path.name: {"sha256": sha_file(path), "bytes": path.stat().st_size}
                for path in (raw_path, root/"report.json")}
    (root / "manifest.json").write_bytes(canonical(manifest) + b"\n")
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("dataset", "features", "study", "output"):
        parser.add_argument("--" + name, required=True)
    parser.add_argument("--repetitions", type=int, default=7)
    result = probe(**vars(parser.parse_args()))
    print(json.dumps({"tasks": len(result["tasks"]), "conditions": len(result["conditions"]),
                      "all_probabilities_bitwise_equal": all(x["probabilities_bitwise_equal_all_repetitions"] for x in result["conditions"])}))
