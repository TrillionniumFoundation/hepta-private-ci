"""Compare frozen physical and logical routing on the original held-out rows.

The fixed budget is 16 states. Labels are read for positive training prototypes
and, only after routing, relevance scoring. This is not a new quality study.
"""

import argparse
import hashlib
import json
import os
from pathlib import Path
import time

import numpy as np

from cell_batch_runtime import BatchedCellRuntime, _integer
from cell_learning_models import NumpyCellHead, canonical
from cell_logical_routing import LogicalCellRouter
from cell_scale_probe import _samples
from real_cell_study import inventory_digest


def sha(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def load_bound_study(dataset, feature_directory, study):
    dataset, feature_directory, study = Path(dataset), Path(feature_directory), Path(study)
    bound = {}
    def read(path):
        if path.is_symlink() or path.stat().st_size > 64 * 1024**2:
            raise ValueError("bounded regular source files required")
        bound[str(path.resolve())] = sha(path)
        return json.loads(path.read_bytes())
    data, plan = read(dataset), read(study / "study-plan.json")
    scale, final = read(study / "scale-report.json"), read(study / "finalization.json")
    report = read(feature_directory / "report.json")
    binding = hashlib.sha256(canonical(plan)).hexdigest()
    identity, tasks, rows = plan["feature_identity"], plan["selected_tasks"], data["rows"]
    if (sha(dataset) != plan["dataset_sha256"] or tasks != data["selected_tasks"]
            or final["plan"]["study_plan_sha256"] != binding
            or final["reports"]["scale-report.json"] != sha(study / "scale-report.json")
            or report["feature_identity"] != identity or scale["feature_identity"] != identity
            or sha(feature_directory / "report.json") != plan["feature_receipt_sha256"]):
        raise ValueError("original study, feature receipt or scale identity changed")
    archive = feature_directory / "features.npz"
    bound[str(archive.resolve())] = sha(archive)
    if bound[str(archive.resolve())] != plan["feature_archive_sha256"]:
        raise ValueError("original feature archive changed")
    with np.load(archive, allow_pickle=False) as arrays:
        if arrays.files != ["features"]:
            raise ValueError("unexpected feature archive fields")
        features = arrays["features"]
    if (features.dtype != np.float32 or list(features.shape) != report["feature_shape"]
            or len(features) != len(rows) or not np.isfinite(features).all()
            or hashlib.sha256(features.tobytes()).hexdigest() != report["feature_tensor_sha256"]
            or report["plan"]["source_ids"] != [row["source_id"] for row in rows]):
        raise ValueError("feature values or source order changed")
    positions = {row["source_id"]: i for i, row in enumerate(rows)}
    if len(positions) != len(rows) or len(set(tasks)) != len(tasks):
        raise ValueError("unique task and source identities required")
    heads, keys, head_sources, prototype_sources = [], [], [], {}
    for task in tasks:
        if Path(task).name != task or task in (".", ".."):
            raise ValueError("invalid task artifact location")
        directory = study / "curves" / task
        seal = read(study / "completed" / (task + ".json"))
        if (seal["task"] != task or seal["plan_sha256"] != binding
                or seal["inventory_sha256"] != inventory_digest(directory)):
            raise ValueError("completed original task artifact inventory changed")
        curve = read(directory / "report.json")
        run = next(run for run in curve["runs"] if run["seed"] == 7 and run["budget"] == 128)
        if run["arms"]["gated"]["artifact"] != "seed-7_n-128_gated":
            raise ValueError("only the original seed7 n128 gated artifact is selected")
        artifact = directory / "seed-7_n-128_gated"
        head = NumpyCellHead.load(artifact, identity)
        if head.report["training_rows"] != 128 or head.report["optimizer_steps"] != plan["steps"]:
            raise ValueError("original training budget differs")
        for name in ("manifest.json", "weights.npz"):
            bound[str((artifact / name).resolve())] = sha(artifact / name)
        train = [positions[source] for source in run["training_source_ids"]]
        if len(set(train)) != 128 or any(rows[i]["split"] != "train" for i in train):
            raise ValueError("router prototypes require the original 128 training sources")
        positive = [i for i in train if rows[i]["labels"][task] == 1]
        if not positive:
            raise ValueError("positive training prototype is missing")
        prototype_sources[task] = [rows[i]["source_id"] for i in positive]
        keys.append(features[positive].mean(axis=0))
        heads.append(head)
        head_sources.append({"task": task, "artifact": str(artifact), "tensor_sha256": head.digest()})
    selected = [positions[source] for source in scale["routing_evaluation"]["source_ids"]]
    sources = tuple(report["source_record_digests"][i] for i in selected)
    if (len(tasks) != 32 or len(selected) != 16 or len(set(selected)) != 16
            or any(rows[i]["split"] != "holdout" for i in selected)
            or list(sources) != scale["source_digests"]):
        raise ValueError("exact original 32 tasks and 16 source-bound holdout rows required")
    return {"heads": heads, "tasks": tasks, "features": features[selected].astype(np.float64),
        "sources": sources, "keys": np.stack(keys), "identity": identity, "original": scale,
        "selected_rows": [rows[i] for i in selected], "bound_files": bound,
        "head_sources": head_sources, "prototype_sources": prototype_sources}


def measure_routing(heads, tasks, features, sources, identity, keys, original, *, repeats=20, top_k=16):
    """No relevance labels enter selection or timing. Return raw outputs for replay."""
    repeats = _integer(repeats, 5, 1000)
    top_k = _integer(top_k, 1, len(heads))
    original_states = [head.digest() for head in heads]
    results, arrays = [], {"features": features, "router_keys": keys}
    scalar = np.stack([head.predict_logits(features) for head in heads], axis=1)
    for prior in original["results"]:
        count = _integer(prior["resident_cells"], len(heads), 4096)
        indices = np.arange(count) % len(heads)
        physical = [heads[i] for i in indices]
        ids, physical_tasks = [f"cell-{i:06d}" for i in range(count)], [tasks[i] for i in indices]
        began = time.perf_counter_ns()
        baseline = BatchedCellRuntime(physical, ids, physical_tasks, identity,
                                      router_keys=keys[indices], cache_bytes=8 * 1024**2)
        logical = LogicalCellRouter(physical, ids, physical_tasks, identity,
                                     router_keys=keys[indices], cache_bytes=8 * 1024**2)
        construction_ns = time.perf_counter_ns() - began
        options = dict(source_digests=sources, feature_identity=identity, generation=1)
        reference = baseline.predict(features, **options)
        measured = {}
        for name, runtime, budget in (("physical_top16", baseline, top_k),
                                      ("physical_all", baseline, None),
                                      ("unique_top16", logical, top_k),
                                      ("all_unique_fanout", logical, None)):
            is_physical = name.startswith("physical_")
            warm = runtime.predict(features, top_k=budget, **options)
            if name == "physical_top16":
                if (warm["selected_cell_ids"] != prior["measurements"]["selective"]["selected_cell_ids"]
                        or prior["measurements"]["selective"]["top_k"] != top_k):
                    raise ValueError("original physical routing selection was not reproduced")
            elif name == "physical_all":
                if not np.array_equal(warm["logits"], reference["logits"]):
                    raise ValueError("all-physical reference changed")
            else:
                mask = warm["served_mask"]
                if (not np.array_equal(warm["logits"][mask], reference["logits"][mask])
                        or warm["physical_cell_ids"] != tuple(ids) or warm["source_digests"] != sources):
                    raise ValueError("logical scatter changed original predictions or source binding")
                if name == "all_unique_fanout" and not mask.all():
                    raise ValueError("default all-unique mode failed complete physical coverage")
            observed = {key: [] for key in ("total_wall", "cpu", "outer_routing", "dispatch", "scatter")}
            before = runtime.head_evaluations if is_physical else runtime.runtime.head_evaluations
            for _ in range(repeats):
                began, cpu = time.perf_counter_ns(), time.process_time_ns()
                out = runtime.predict(features, top_k=budget, **options)
                observed["total_wall"].append(time.perf_counter_ns() - began)
                observed["cpu"].append(time.process_time_ns() - cpu)
                observed["outer_routing"].append(out.get("outer_routing_ns", out.get("router_ns")))
                observed["dispatch"].append(out["elapsed_ns"] - out["router_ns"] if is_physical
                                            else out["dispatch_ns"])
                observed["scatter"].append(out.get("scatter_ns", 0))
            after = runtime.head_evaluations if is_physical else runtime.runtime.head_evaluations
            if is_physical:
                selected_tasks = [sorted({physical_tasks[i] for i in row}) for row in out["selected_indices"]]
                states = count if budget is None else top_k
                served = [states] * len(features)
            else:
                selected_tasks = [sorted({logical.logical_task_ids[i] for i in row})
                                  for row in out["selected_logical_indices"]]
                served = out["served_mask"].sum(axis=1).tolist()
                states = out["computed_states_per_row"]
                arrays[f"cells{count}_{name}_served_mask"] = out["served_mask"]
            arrays[f"cells{count}_{name}_logits"] = out["logits"]
            measured[name] = {"timing": {key: _samples(values) for key, values in observed.items()},
                "selected_task_ids": selected_tasks, "selected_cell_ids": out["selected_cell_ids"],
                "computed_states_per_row": states, "served_physical_cells_per_row": served,
                "timing_scope": ("routing=runtime prototype/selection; dispatch=remaining runtime; scatter=0"
                    if is_physical else "routing=logical score preparation; dispatch=representative runtime including topK; scatter=physical fanout"),
                "measured_head_evaluations": after - before,
                "output_logits_bytes": out["logits"].nbytes,
                "encoder_invocations": out["encoder_invocations_by_runtime"], "private_parameter_updates": 0}
        error = float(np.max(np.abs(arrays[f"cells{count}_all_unique_fanout_logits"] - scalar[:, indices])))
        if not np.array_equal(arrays[f"cells{count}_physical_all_logits"],
                              arrays[f"cells{count}_all_unique_fanout_logits"]):
            raise ValueError("timed full-coverage modes produced different physical outputs")
        if error > 1e-9 or not np.array_equal(
                arrays[f"cells{count}_all_unique_fanout_logits"].argmax(axis=-1), scalar[:, indices].argmax(axis=-1)):
            raise ValueError("scattered predictions differ from the scalar learned heads")
        results.append({"physical_cell_ids": count, "retained_private_head_states": len(logical.members),
            "construction_ns": construction_ns, "original_selective_measurement": prior["measurements"]["selective"],
            "measurements": measured, "original_accounting": baseline.accounting(),
            "logical_accounting": logical.accounting(), "scatter_bitwise_matches_physical_all": True,
            "scalar_max_abs_error": error, "scalar_class_predictions_match": True,
            "physical_cell_id_order": ids})
    if [head.digest() for head in heads] != original_states:
        raise ValueError("probe changed learned parameters")
    return results, arrays


def run_probe(dataset, features, study, output, *, repeats=20):
    output, study, features = Path(output).resolve(), Path(study).resolve(), Path(features).resolve()
    if output == study or output.is_relative_to(study) or output.is_relative_to(features):
        raise ValueError("new evidence directory must not modify the original study or features")
    context = load_bound_study(dataset, features, study)
    if [entry["resident_cells"] for entry in context["original"]["results"]] != [64, 256, 1024]:
        raise ValueError("original 64/256/1024 scale plan required")
    output.mkdir(parents=True, exist_ok=False)
    code = {name: sha(Path(__file__).with_name(name)) for name in (
        "logical_routing_probe.py", "cell_logical_routing.py", "cell_batch_runtime.py",
        "cell_learning_models.py", "cell_learning_metrics.py", "cell_scale_probe.py", "real_cell_study.py")}
    plan = {"schema": "hepta.logical-routing-probe.v1", "top_k": 16, "repeats": repeats,
        "modes": ["physical_top16", "physical_all", "unique_top16", "all_unique_fanout"],
        "warmups_per_mode": 1, "measurement_order": "sequential in one process; all wall samples retained",
        "thread_limits": {key: os.environ.get(key) for key in
                          ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS")},
        "scales": [64, 256, 1024], "feature_identity": context["identity"], "tasks": context["tasks"],
        "source_ids": [row["source_id"] for row in context["selected_rows"]],
        "source_digests": context["sources"], "input_files_sha256": context["bound_files"],
        "heads": context["head_sources"], "training_prototype_sources": context["prototype_sources"],
        "code_sha256": code, "heldout_labels_enter_selection": False,
        "cohort": "exact original 16 rows; original positive-task eligibility is preserved",
        "task_family_count": context["original"]["routing_evaluation"]["task_families"],
        "scope": "serving correction; original learning/quality experiment unchanged"}
    (output / "plan.json").write_bytes(canonical(plan) + b"\n")
    results, arrays = measure_routing(context["heads"], context["tasks"], context["features"],
        context["sources"], context["identity"], context["keys"], context["original"], repeats=repeats)
    # All routing is complete before held-out labels are used for relevance scores.
    relevant = [{task for task in context["tasks"] if row["labels"][task] == 1}
                for row in context["selected_rows"]]
    for result in results:
        for measured in result["measurements"].values():
            recalls = [len(set(selected) & wanted) / len(wanted)
                       for selected, wanted in zip(measured["selected_task_ids"], relevant, strict=True)]
            measured["positive_task_recall_per_row"] = recalls
            measured["mean_positive_task_recall"] = float(np.mean(recalls))
    if any(sha(path) != digest for path, digest in context["bound_files"].items()):
        raise ValueError("original study inputs changed during probe")
    if any(sha(Path(__file__).with_name(name)) != digest for name, digest in code.items()):
        raise ValueError("routing implementation changed during probe")
    np.savez_compressed(output / "raw_outputs.npz", **arrays)
    report = {"plan": plan, "results": results, "original_inputs_unchanged": True,
        "raw_outputs_sha256": sha(output / "raw_outputs.npz"), "encoder_invocations": 0,
        "private_parameter_updates": 0, "default_mode": "all_unique_fanout",
        "copies_are_independent_learning": False, "selective_complete_coverage_claimed": False,
        "source_binding_verified": True, "quality_experiment_modified": False, "authority": "DENY_ALL"}
    (output / "report.json").write_bytes(canonical(report) + b"\n")
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("dataset", "features", "study", "output"):
        parser.add_argument("--" + name, required=True)
    parser.add_argument("--repeats", type=int, default=20)
    args = parser.parse_args()
    report = run_probe(**vars(args))
    print(json.dumps({"output": args.output, "encoder_invocations": 0,
        "scales": [{"cells": row["physical_cell_ids"], "states": row["retained_private_head_states"],
            "recall": {name: value["mean_positive_task_recall"] for name, value in row["measurements"].items()}}
            for row in report["results"]]}))


if __name__ == "__main__":
    main()
