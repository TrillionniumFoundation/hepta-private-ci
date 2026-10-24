"""Matched private-gradient engineering probe on sealed real training banks only."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import resource
import re
import time

import numpy as np

from cell_calibrated_curve import sha_file, verify_prepared, write_json
from cell_learning_models import NumpyCellHead
from cell_microbatch_training import FrozenTrainingBank, MicrobatchCellTrainer

CODE_FILES = ("cell_microbatch_training.py", "probe_cell_microbatch_training.py",
              "cell_learning_models.py", "cell_learning_metrics.py", "cell_calibrated_curve.py")


def load_training_banks(study):
    root, features, labels, sources, pins = Path(study), {}, {}, {}, {}
    blobs = {name: (root / name).read_bytes() for name in ("study-plan.json", "selection-seal.json")}
    study_plan, selection = (json.loads(blobs[name]) for name in ("study-plan.json", "selection-seal.json"))
    tasks = study_plan["tasks"]
    if (not isinstance(tasks, list) or len(tasks) != 5 or len(set(tasks)) != 5
            or any(type(t) is not str or re.fullmatch(r"audio_[A-Za-z0-9_-]+", t) is None for t in tasks)
            or selection["all_declared_tasks_frozen_before_any_evaluation"] is not True
            or set(selection["seals"]) != {f"{t}/prepared/seal.json" for t in tasks}):
        raise ValueError("exact five declared and sealed audio tasks required")
    pins.update({str(root / name): hashlib.sha256(value).hexdigest() for name, value in blobs.items()})
    for task_name in sorted(tasks):
        task = root / task_name
        prepared = task / "prepared"
        frozen = verify_prepared(prepared)
        if (sha_file(prepared / "seal.json") != selection["seals"][f"{task_name}/prepared/seal.json"]
                or frozen["plan"]["task_id"] != task_name
                or frozen["plan"]["feature_identity"] != study_plan["feature_identity"]):
            raise ValueError("task preparation differs from the frozen study selection")
        runs = [r for r in frozen["runs"] if (r["seed"], r["budget"]) == (7, 32)]
        if len(runs) != 1:
            raise ValueError("one genuinely selected seed7/n32 training bank per task required")
        run = runs[0]
        directory = prepared / run["directory"]
        rows = json.loads((directory / "baseline_rows.json").read_bytes())
        with np.load(directory / "baseline.npz", allow_pickle=False) as arrays:
            if set(arrays.files) != {"features", "labels"}:
                raise ValueError("unexpected sealed baseline fields")
            x, y = arrays["features"], arrays["labels"]
        ids = [r["source_id"] for r in rows]
        if (x.shape != (32, 80) or y.shape != (32,) or y.dtype.kind not in "iu"
                or ids != run["training_source_ids"] or len(set(ids)) != 32
                or not set(ids) <= set(frozen["plan"]["contexts"][0]["source_ids"])
                or np.bincount(y, minlength=2).tolist() != [16, 16]):
            raise ValueError("source order, real training-only rows or n32 binary bank differs")
        features[task.name], labels[task.name], sources[task.name] = x, y, ids
        current_identity = frozen["plan"]["feature_identity"]
        if len(features) == 1: feature_identity = current_identity
        elif current_identity != feature_identity: raise ValueError("feature identities differ between tasks")
        for path in (prepared / "seal.json", directory / "baseline.npz", directory / "baseline_rows.json"):
            pins[str(path)] = sha_file(path)
    if len(features) != 5:
        raise ValueError("exactly the five frozen real audio tasks required")
    return FrozenTrainingBank.build(features, sources, feature_identity), labels, pins


def compare_condition(bank, labels_by_task, count, mode, *, steps=20, microbatch=32, first="scalar"):
    if (type(count) is not int or not 1 <= count <= 4096 or first not in ("scalar", "batched")
            or set(labels_by_task) != set(bank.task_ids)):
        raise ValueError("bounded matched private training condition required")
    tasks = [bank.task_ids[i % len(bank.task_ids)] for i in range(count)]
    labels = np.stack([labels_by_task[task] for task in tasks])
    raw = {task: bank.raw_rows(task) for task in bank.task_ids}
    reports, states = {}, {}
    for kind in (first, "batched" if first == "scalar" else "scalar"):
        started, cpu = time.perf_counter_ns(), time.process_time_ns()
        heads = [NumpyCellHead(bank._raw.shape[1], 2, mode, rank=4, seed=1000000+i) for i in range(count)]
        for head in heads: head.feature_identity = bank.feature_identity
        initial = [head.digest() for head in heads]
        if len(set(initial)) != count:
            raise ValueError("benchmark must begin with distinct private parameter states")
        if kind == "batched":
            trainer = MicrobatchCellTrainer(heads, [f"cell-{i}" for i in range(count)], tasks, bank,
                                           microbatch=microbatch)
            setup = {"wall_ns": time.perf_counter_ns()-started, "cpu_ns": time.process_time_ns()-cpu}
            report = trainer.train(labels, feature_identity=bank.feature_identity, generation=1, steps=steps)
            state = trainer.parameters()
            losses, digests = report["final_loss"], report["trained_parameter_digests"]
            details = report
        else:
            setup = {"wall_ns": time.perf_counter_ns()-started, "cpu_ns": time.process_time_ns()-cpu}
            fit_started, fit_cpu = time.perf_counter_ns(), time.process_time_ns()
            for index, head in enumerate(heads):
                head.train(raw[tasks[index]], labels[index], steps=steps)
            report = {"wall_ns": time.perf_counter_ns()-fit_started, "cpu_ns": time.process_time_ns()-fit_cpu}
            state = {name: np.stack([h.params[name] for h in heads]) for name in heads[0].params}
            losses, digests = [h.report["final_loss"] for h in heads], [h.digest() for h in heads]
            details = {"private_optimizer_updates": count*steps, "example_updates": count*steps*len(labels[0]),
                "retained_parameter_bytes": sum(h.tensor_bytes for h in heads),
                "peak_single_head_optimizer_bytes": 2*heads[0].tensor_bytes,
                "optimizer_retention": "existing NumpyCellHead.train discards moments after each completed head"}
        reports[kind] = {"setup": setup, "fit": report,
            "inclusive_wall_ns": time.perf_counter_ns()-started, "inclusive_cpu_ns": time.process_time_ns()-cpu,
            "scope": "head initialization plus private training and final parameter snapshot; shared immutable bank construction excluded and recorded separately",
            "initial_parameter_digests": initial, "trained_parameter_digests": digests,
            "distinct_trained_private_states": len(set(digests)), "final_training_loss": losses,
            "process_peak_rss_bytes_so_far": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss*1024,
            "details": details}
        states[kind] = state
    maximum = 0.
    for name in states["scalar"]:
        a, b = states["scalar"][name], states["batched"][name]
        maximum = max(maximum, float(np.max(np.abs(a-b))))
        if not np.allclose(a, b, atol=1e-10, rtol=1e-10):
            raise ValueError("batched private parameters differ from native scalar training")
    if reports["scalar"]["initial_parameter_digests"] != reports["batched"]["initial_parameter_digests"]:
        raise ValueError("scalar and batched experiments began from different private states")
    result = {"mode": mode, "physical_cells": count, "task_count": len(set(tasks)), "steps_per_cell": steps,
        "microbatch": microbatch, "task_ids": tasks, "initial_seed_range": [1000000, 1000000+count-1],
        "comparison_order": [first, "batched" if first == "scalar" else "scalar"], "executions": reports,
        "parameter_parity_atol": 1e-10, "parameter_parity_rtol": 1e-10, "maximum_absolute_parameter_difference": maximum,
        "parameters_bitwise_equal": all(np.array_equal(states["scalar"][k], states["batched"][k]) for k in states["scalar"]),
        "actual_total_private_optimizer_updates_both_methods": 2*count*steps,
        "actual_total_example_updates_both_methods": 2*count*steps*len(labels[0]),
        "encoder_forwards": 0, "new_tasks_inferred_from_cell_count": False,
        "heldout_or_calibration_rows_enter_optimizer": False}
    return result, states


def run_probe(study, output):
    total_started, total_cpu = time.perf_counter_ns(), time.process_time_ns()
    if any(os.environ.get(name) != "1" for name in ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS")):
        raise ValueError("explicit single-thread BLAS environment required")
    root = Path(output)
    if root.exists(): raise ValueError("new probe output directory required")
    began, cpu = time.perf_counter_ns(), time.process_time_ns()
    bank, labels, inputs = load_training_banks(study)
    load = {"wall_ns": time.perf_counter_ns()-began, "cpu_ns": time.process_time_ns()-cpu,
            "cached_tensor_bytes": bank.tensor_bytes, "unique_source_rows": len(bank.source_ids)}
    code = {name: sha_file(Path(__file__).with_name(name)) for name in CODE_FILES}
    plan = {"schema": "hepta.private-gradient-batch-probe.v1", "feature_identity": bank.feature_identity,
        "task_ids": bank.task_ids, "input_files_sha256": inputs, "source_code_sha256": code,
        "cells": [64, 256, 1024], "modes": ["linear", "gated", "residual"], "steps": 20, "microbatch": 32,
        "bank_selection": "prepared seed7/n32 training-only banks", "initialization": "one distinct seed1000000+i per private Cell",
        "scientific_scope": "engineering update parity and resource measurements; does not replace primary learning curves",
        "timing_scope": "matched same-process runs, shared CPU contention; no isolated capacity or energy claim",
        "memory_scope": "explicit tensor bounds and process RSS high-water; Python/BLAS transient allocation peaks not fully measured"}
    root.mkdir(parents=True)
    write_json(root / "plan.json", plan)
    report = {"plan": plan, "feature_bank_load": load, "conditions": []}
    for mode_index, mode in enumerate(plan["modes"]):
        for count in plan["cells"]:
            result, states = compare_condition(bank, labels, count, mode, first="scalar" if mode_index % 2 == 0 else "batched")
            location = root / f"{mode}-{count}"
            location.mkdir()
            for kind, state in states.items():
                path = location / (kind + "-parameters.npz")
                with path.open("xb") as stream: np.savez_compressed(stream, **state)
                result["executions"][kind]["parameter_artifact"] = {"path": str(path.relative_to(root)),
                    "sha256": sha_file(path), "bytes": path.stat().st_size}
            write_json(location / "report.json", result)
            report["conditions"].append(result)
            print(json.dumps({"mode": mode, "cells": count, "max_parameter_difference": result["maximum_absolute_parameter_difference"],
                "scalar_seconds": result["executions"]["scalar"]["inclusive_wall_ns"]/1e9,
                "batched_seconds": result["executions"]["batched"]["inclusive_wall_ns"]/1e9}), flush=True)
    if any(sha_file(path) != pin for path, pin in inputs.items()) or code != {name: sha_file(Path(__file__).with_name(name)) for name in CODE_FILES}:
        raise ValueError("training banks or implementation changed during the probe")
    for task in bank.task_ids:
        verify_prepared(Path(study) / task / "prepared")
    report["inclusive_probe"] = {"wall_ns": time.perf_counter_ns()-total_started,
        "cpu_ns": time.process_time_ns()-total_cpu,
        "scope": "all bank verification/normalization, both matched methods, parity checks, parameter snapshots/compression and condition files, final input verification; excludes final root report/manifest writes; do not add nested components to this total"}
    report.update(authority="DENY_ALL", quality_qualified=False)
    write_json(root / "report.json", report)
    write_json(root / "manifest.json", {str(p.relative_to(root)): {"sha256": sha_file(p), "bytes": p.stat().st_size}
                                       for p in sorted(root.rglob("*")) if p.is_file()})
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--study", required=True)
    parser.add_argument("--output", required=True)
    run_probe(**vars(parser.parse_args()))
