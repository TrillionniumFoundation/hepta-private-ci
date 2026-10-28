"""Post-seal, read-only analysis of every preregistered study001 configuration.

No training, model loading, benchmark execution or configuration selection occurs.
Writes only derived COMPARISON_SUMMARY.json and COMPARISON_TABLES.md. Partial
inventories retain every planned row and are explicitly marked incomplete.
"""

import argparse
from collections import Counter, defaultdict
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import statistics


NOTES = [
    "No winner or post-hoc configuration selection is assigned by this analysis.",
    "Accuracy is primary; CE and Brier are lower-is-better. Mean and sample SD describe training-seed variation conditional on fixed heldout sources.",
    "Mechanism accuracy contrasts use paired seeds and 98.75% two-sided Student-t intervals (four comparisons per task). PROTOCOL records 0.01 minimum practical effect but no Boolean success rule; 0.01 is displayed as a reference line, not a retrospectively registered verdict.",
    "Representation/scaling have three seeds and are descriptive; common learning rate/updates do not establish each architecture's tuned optimum.",
    "Scaling uses fixed 160x32 sample presentations; capacity configurations change width/depth jointly. Long-memory adds real distractors but retains four early associations; multimodal length stress adds null steps.",
    "CPU-only results do not establish GPU or neuromorphic energy advantages. Mamba is an equation-verified serial CPU reference; actual SDPA operators are reported.",
    "Inference times cover the delivered full-sequence forward, including auxiliary tensors; they are not optimized-kernel lower bounds or fixed-memory streaming measurements.",
    "Profiler FLOPs are partial supported-operator formulas. Special/fused operators without counts remain explicit. Tensor allocations, including UNKNOWN categories, are not RSS.",
    "Inference uses a preregistered single seed and first 16 heldout samples; repeat quantiles are descriptive, not confidence intervals over samples or hardware.",
    "Measurements ran serially on a shared host; serial execution does not establish dedicated-machine isolation. Nonmonotonic small-repeat latency changes do not establish complexity exponents.",
    "Successful RESULT process-CPU excludes interpreter/import and pre-timer startup. EXECUTION wall includes job startup/scheduling. Summed overlapping job-wall is not study calendar time.",
    "Failed-attempt wall is charged separately. Failed process-CPU is unknown unless recorded, and is never imputed as zero.",
]


def read_json(path):
    return json.loads(Path(path).read_text())


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def stats(values):
    values = [float(value) for value in values if value is not None]
    if not all(math.isfinite(value) for value in values):
        raise ValueError("nonfinite measurement in input result")
    return {"n": len(values), "mean": statistics.mean(values) if values else None,
            "sd": statistics.stdev(values) if len(values) > 1 else None,
            "min": min(values) if values else None, "max": max(values) if values else None}


def paired_ci(values, confidence=0.9875):
    estimate = stats(values)
    lower = upper = None
    if len(values) > 1:
        from scipy.stats import t
        margin = float(t.ppf((1 + confidence) / 2, len(values) - 1)) * estimate["sd"] / math.sqrt(len(values))
        lower, upper = estimate["mean"] - margin, estimate["mean"] + margin
    return dict(estimate, confidence=confidence, lower=lower, upper=upper,
                differences=list(values), method="paired Student-t; conditional on heldout sources")


def fingerprints(directory):
    import numpy as np
    heldout, batches = hashlib.sha256(), hashlib.sha256()
    for filename, target, selection in (
        ("split_sources.npz", heldout, lambda key: key.startswith("test_")),
        ("predictions.npz", heldout, lambda key: key == "labels"),
        ("batch_indices.npz", batches, lambda key: True),
    ):
        with np.load(directory / filename, allow_pickle=False) as loaded:
            for key in sorted(loaded.files):
                if selection(key):
                    array = np.ascontiguousarray(loaded[key])
                    target.update(json.dumps([filename, key, array.dtype.str, array.shape]).encode())
                    target.update(array.tobytes())
    return heldout.hexdigest(), batches.hexdigest()


def load_results(root, inventory):
    valid, issues, gradient_zeros, gradient_invalid = {}, [], [], []
    for planned in inventory["runs"]:
        run_id, spec = planned["run_id"], planned["spec"]
        directory = root / run_id
        if not (directory / "RESULT.json").exists():
            continue
        try:
            result = read_json(directory / "RESULT.json")
            actual_spec = ({"stage": "boundary", "seed": result["seed"]}
                           if spec["stage"] == "boundary" else result["spec"])
            if actual_spec != spec or result["source_seal"] != inventory["source_seal"]:
                raise ValueError("result specification/source seal differs from registered inventory")
            item = {"spec": spec, "result": result}
            if spec["stage"] != "boundary":
                if result["checkpoint_reload_max_error"] != 0:
                    raise ValueError("checkpoint reload error is nonzero")
                if digest(directory / "checkpoint" / "manifest.json") != result["checkpoint_manifest_sha256"]:
                    raise ValueError("checkpoint manifest hash differs from result")
                item["fingerprints"] = fingerprints(directory)
                item["data"] = read_json(directory / "DATA.json")
                expected = spec["updates"] * spec["batch_size"]
                if result["training_examples_seen"] != expected or result["training_sequence_positions"] != expected * spec["length"]:
                    raise ValueError("training work counts disagree with specification")
                p = result["parameters"]
                if p["total"] != p["frontend"] + p["backbone"] + p["readout"]:
                    raise ValueError("parameter component counts do not sum to total")
                for name, entry in result["gradient_groups"].items():
                    if entry["l1"] is None or not entry["finite"] or not math.isfinite(entry["l1"]):
                        gradient_invalid.append({"run_id": run_id, "parameter": name})
                    elif entry["l1"] == 0:
                        gradient_zeros.append({"run_id": run_id, "parameter": name})
            valid[run_id] = item
        except (OSError, ValueError, KeyError, TypeError) as error:
            issues.append({"run_id": run_id, "error": f"{type(error).__name__}: {error}"})
    return valid, issues, gradient_zeros, gradient_invalid


def aggregate_section(stage, runs, valid):
    groups = {}
    for run in runs:
        spec = run["spec"]
        if spec["stage"] != stage:
            continue
        group_id = run["run_id"].rsplit("/", 1)[0]
        groups.setdefault(group_id, []).append(run)
    rows = []
    for group_id, planned in groups.items():
        present = [valid[run["run_id"]] for run in planned if run["run_id"] in valid]
        spec = {key: value for key, value in planned[0]["spec"].items() if key != "seed"}
        measurements = {}
        for key in ("accuracy", "cross_entropy", "brier", "image_accuracy", "spoken_accuracy", "conflict_accuracy"):
            measurements[key] = stats([item["result"]["test"].get(key) for item in present])
        for key in ("training_cpu_seconds", "training_wall_seconds", "total_cpu_seconds",
                    "total_wall_seconds", "training_examples_seen", "unique_training_examples_seen"):
            measurements[key] = stats([item["result"].get(key) for item in present])
        parameters = {key: stats([item["result"]["parameters"][key] for item in present])
                      for key in ("total", "frontend", "backbone", "readout")}
        row = {"group_id": group_id, "spec": spec, "expected_seeds": [run["spec"]["seed"] for run in planned],
               "completed_seeds": [item["spec"]["seed"] for item in present],
               "status": "complete" if len(present) == len(planned) else "incomplete",
               "metrics": measurements, "parameters": parameters,
               "mean_presentations_per_available_example": spec["updates"] * spec["batch_size"] / spec["train_size"],
               "capacity_matching": [{"seed": item["spec"]["seed"], "receipt": item["result"]["parameters"]["matching"]}
                                     for item in present],
               "data_source_counts": present[0]["data"].get("source_counts") if present else None}
        if stage == "scaling":
            row["configuration"] = group_id.split("/")[1]
            row["validation_cpu_curves"] = []
            for run in planned:
                item = valid.get(run["run_id"])
                curve = [] if item is None else [
                    {"update": point["update"], "validation_ce": point["validation"]["cross_entropy"],
                     "validation_accuracy": point["validation"]["accuracy"],
                     "training_cpu_seconds": point["training_cpu_seconds"],
                     "training_wall_seconds": point["training_wall_seconds"]}
                    for point in item["result"]["history"]]
                row["validation_cpu_curves"].append({"run_id": run["run_id"], "seed": run["spec"]["seed"],
                                                     "status": "complete" if item else "pending", "points": curve})
        rows.append(row)
    return rows


def mechanism_contrasts(protocol, valid):
    rows = []
    threshold = protocol["mechanism"]["minimum_practical_effect"]
    for task in protocol["mechanism"]["tasks"]:
        for control in protocol["mechanism"]["architectures"]:
            if control == "hcsn":
                continue
            seeds, accuracy, ce, mismatches = [], [], [], []
            for seed in protocol["mechanism_seeds"]:
                first = valid.get(f"mechanism/{task}/hcsn/seed{seed}")
                second = valid.get(f"mechanism/{task}/{control}/seed{seed}")
                if first and second:
                    if first["fingerprints"] != second["fingerprints"]:
                        mismatches.append(seed)
                        continue
                    seeds.append(seed)
                    accuracy.append(first["result"]["test"]["accuracy"] - second["result"]["test"]["accuracy"])
                    ce.append(first["result"]["test"]["cross_entropy"] - second["result"]["test"]["cross_entropy"])
            complete = seeds == protocol["mechanism_seeds"] and not mismatches
            interval = paired_ci(accuracy)
            rows.append({"task": task, "contrast": f"hcsn-minus-{control}", "paired_seeds": seeds,
                         "status": "complete" if complete else "incomplete", "pair_mismatch_seeds": mismatches,
                         "accuracy": interval, "secondary_ce_difference": stats(ce),
                         "practical_accuracy_threshold": threshold,
                         "decision_rule": "No Boolean success rule specified in PROTOCOL; display difference, interval and practical reference only",
                         "winner_assigned": False})
    return rows


def collect_costs(root, runs, valid):
    attempts, stages = [], defaultdict(lambda: {"completed_runs": 0, "result_total_cpu_seconds": 0.0,
                                                "recorded_training_cpu_seconds": 0.0, "result_total_wall_seconds": 0.0})
    for run in runs:
        spec, run_id = run["spec"], run["run_id"]
        for path in sorted((root / run_id).glob("EXECUTION_*.json")):
            receipt = read_json(path)
            attempts.append({"run_id": run_id, "stage": spec["stage"], "receipt": path.name,
                             "status": receipt["status"], "exit_code": receipt["exit_code"],
                             "wall_seconds": receipt["elapsed_seconds"],
                             "process_cpu_seconds": receipt.get("process_cpu_seconds")})
        if run_id in valid:
            result = valid[run_id]["result"]
            entry = stages[spec["stage"]]
            entry["completed_runs"] += 1
            entry["result_total_cpu_seconds"] += result["total_cpu_seconds"]
            entry["result_total_wall_seconds"] += result["total_wall_seconds"]
            entry["recorded_training_cpu_seconds"] += result.get("training_cpu_seconds", result.get("actor", {}).get("training_cpu_seconds", 0))
    failed = [item for item in attempts if item["status"] != "completed" or item["exit_code"] != 0]
    successful = [item for item in attempts if item not in failed]
    return {"completed_result_costs_by_stage": dict(stages),
            "completed_result_total_cpu_seconds": sum(row["result_total_cpu_seconds"] for row in stages.values()),
            "completed_recorded_training_cpu_seconds": sum(row["recorded_training_cpu_seconds"] for row in stages.values()),
            "all_execution_attempts": len(attempts), "successful_execution_attempts": len(successful), "failed_execution_attempts": len(failed),
            "successful_attempt_accumulated_job_wall_seconds": sum(row["wall_seconds"] for row in successful),
            "failed_attempt_accumulated_job_wall_seconds": sum(row["wall_seconds"] for row in failed),
            "all_attempt_accumulated_job_wall_seconds": sum(row["wall_seconds"] for row in attempts),
            "failed_attempts_with_unknown_cpu": sum(row["process_cpu_seconds"] is None for row in failed),
            "failed_attempt_recorded_cpu_seconds": sum(row["process_cpu_seconds"] for row in failed if row["process_cpu_seconds"] is not None),
            "failed_attempt_total_cpu_seconds": (None if any(row["process_cpu_seconds"] is None for row in failed)
                                                  else sum(row["process_cpu_seconds"] for row in failed)),
            "study_calendar_wall_seconds": None, "attempts": attempts,
            "scope": "Successful process-CPU, external job-wall and failed attempt costs are separate. Job-wall sums overlap; failed CPU without a counter is unknown."}


def validate_profile(record, result, spec):
    """Recompute recorded measurement arithmetic without executing the model."""
    measurement, warmup, audit = record["measurement"], record["warmup"], record["operator_audit"]
    if (measurement["forward_calls"] != 7 or warmup["forward_calls"] != 2
            or warmup["included_in_latency_samples"] or audit["forward_calls"] != 1):
        raise ValueError("expected seven measured calls, two excluded warmups and one profiler call")
    if record["repeat_output_max_abs_difference"] != 0 or record["source_audit"]["status"] != "verified":
        raise ValueError("profile output/source audit did not reproduce exactly")
    if record["parameter_counts"] != result["parameters"]:
        raise ValueError("profile parameter counts disagree with RESULT")
    if (record["parameter_bytes"] != result["parameters"]["total"] * 4
            or record["trainable_parameter_bytes"] != record["parameter_bytes"] or record["buffer_bytes"] != 0):
        raise ValueError("expected all-trainable float32 parameters and no registered buffers")
    for work, count in ((measurement, 7), (warmup, 2)):
        if work["examples"] != count * 16 or work["sequence_positions"] != count * 16 * spec["length"]:
            raise ValueError("profile work counts disagree with batch/length")
        for field in ("wall_seconds", "process_cpu_seconds"):
            values = work[field]
            if len(values) != count or not all(math.isfinite(value) and value > 0 for value in values):
                raise ValueError("invalid raw profile clock samples")
    clocks = (("wall_latency_seconds", measurement["wall_seconds"]),
              ("process_cpu_seconds_stats", measurement["process_cpu_seconds"]),
              ("examples_per_second", [16 / value for value in measurement["wall_seconds"]]),
              ("sequence_positions_per_second", [16 * spec["length"] / value for value in measurement["wall_seconds"]]))
    for name, values in clocks:
        ordered = sorted(values)
        expected = {"median": statistics.median(values), "min": min(values), "max": max(values), "sum": sum(values)}
        for key, q in (("p05", 0.05), ("p95", 0.95)):
            position = (len(values) - 1) * q
            lower, upper = math.floor(position), math.ceil(position)
            expected[key] = ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)
        if any(not math.isclose(measurement[name][key], value, rel_tol=1e-12, abs_tol=1e-12)
               for key, value in expected.items()):
            raise ValueError(f"profile statistics do not match raw samples: {name}")
    if audit["status"] != "available" or audit["memory"]["status"] != "available":
        raise ValueError("missing profiler or tensor-allocation record")
    if sum(row["formula_flops"] for row in audit["supported_operator_formulas"]) != audit["observed_formula_flops"]:
        raise ValueError("partial formula FLOPs do not sum")
    if not audit["unsupported_ops"] or "not total model FLOPs" not in audit["flop_scope"]:
        raise ValueError("partial FLOP scope is missing")
    memory = audit["memory"]
    if (sum(memory["created_bytes_by_category"].values()) != memory["forward_created_bytes"]
            or memory["peak_increment_over_preexisting_bytes"] != max(0, memory["peak_managed_bytes"] - memory["preexisting_managed_bytes"])
            or memory["unclassified_created_bytes"] != memory["created_bytes_by_category"]["UNKNOWN"]):
        raise ValueError("allocation category sums or peak increment disagree")
    if spec["architecture"] == "hcsn" and not {"aten::special_erfcx", "aten::special_log_ndtr"}.issubset(audit["unsupported_ops"]):
        raise ValueError("HCSN special-function FLOP limitation not present")
    if spec["architecture"] == "transformer" and "aten::_scaled_dot_product_flash_attention_for_cpu" not in audit["attention_operators"]:
        raise ValueError("expected actual CPU SDPA operator missing")


def collect_performance(root, runs, valid):
    selected = [run for run in runs if (run["spec"]["stage"] == "representation" and run["spec"]["seed"] == 2201)
                or (run["spec"]["stage"] == "scaling" and run["spec"]["seed"] == 3301)]
    rows, batches = [], defaultdict(set)
    work = dict.fromkeys(("reload_cpu_seconds", "data_cpu_seconds", "warmup_cpu_seconds", "timed_forward_cpu_seconds", "profiler_cpu_seconds"), 0.0)
    for run in selected:
        row = {"run_id": run["run_id"], "spec": run["spec"], "status": "pending"}
        path = root / run["run_id"] / "PERFORMANCE.json"
        if path.exists():
            try:
                record = read_json(path)
                result = valid[run["run_id"]]["result"]
                if record["checkpoint_manifest_sha256"] != result["checkpoint_manifest_sha256"] or not record["strict_reload"]:
                    raise ValueError("performance checkpoint differs from selected run")
                if record["source_audit"].get("source_seal") != result["source_seal"] or record["task"] != run["spec"]["task"]:
                    raise ValueError("performance source seal/task differs from selected run")
                if record["fixed_batch"]["batch_size"] != 16 or record["environment"]["cuda"]:
                    raise ValueError("expected batch16 CPU-only measurement")
                if record["fixed_batch"]["sequence_length"] != run["spec"]["length"] or record["environment"]["threads"] != 1:
                    raise ValueError("expected registered sequence length and one CPU thread")
                validate_profile(record, result, run["spec"])
                audit = record["operator_audit"]
                row.update(status="complete", fixed_batch=record["fixed_batch"], measurement=record["measurement"],
                           warmup=record["warmup"], parameter_bytes=record["parameter_bytes"],
                           trainable_parameter_bytes=record["trainable_parameter_bytes"], buffer_bytes=record["buffer_bytes"],
                           observed_formula_flops=audit["observed_formula_flops"], unsupported_ops=audit["unsupported_ops"],
                           attention_operators=audit["attention_operators"], allocations=audit["memory"],
                           profiler_status=audit["status"], arithmetic_audit="passed", environment=record["environment"],
                           total_cpu_seconds=record["total_cpu_seconds"], total_wall_seconds=record["total_wall_seconds"])
                batches[(run["spec"]["task"], run["spec"]["length"])].add(record["fixed_batch"]["sha256"])
                for key, value in (("reload_cpu_seconds", record["reload_work"]["cpu_seconds"]),
                                   ("data_cpu_seconds", record["data_work"]["cpu_seconds"]),
                                   ("warmup_cpu_seconds", sum(record["warmup"]["process_cpu_seconds"])),
                                   ("timed_forward_cpu_seconds", sum(record["measurement"]["process_cpu_seconds"])),
                                   ("profiler_cpu_seconds", audit["cpu_seconds"])):
                    work[key] += value
            except (OSError, ValueError, KeyError, TypeError) as error:
                row.update(status="invalid", error=f"{type(error).__name__}: {error}")
        rows.append(row)
    return {"expected": len(selected), "completed": sum(row["status"] == "complete" for row in rows),
            "arithmetic_audits_passed": sum(row.get("arithmetic_audit") == "passed" for row in rows),
            "profiler_status_counts": dict(Counter(row.get("profiler_status", row["status"]) for row in rows)),
            "allocation_status_counts": dict(Counter(row.get("allocations", {}).get("status", row["status"]) for row in rows)),
            "recorded_component_work": work,
            "fixed_batch_hash_consistent": all(len(values) == 1 for values in batches.values()), "rows": rows,
            "total_measurement_work_cpu_seconds": sum(row.get("total_cpu_seconds", 0) for row in rows),
            "total_measurement_work_wall_seconds": sum(row.get("total_wall_seconds", 0) for row in rows)}


def f(value, digits=4):
    return "pending" if value is None else f"{value:.{digits}f}"


def mean_sd(entry, scale=1, digits=3):
    return "pending" if not entry["n"] else f"{f(entry['mean']*scale, digits)} ± {f(None if entry['sd'] is None else entry['sd']*scale, digits)}"


def markdown(report):
    lines = ["# Study001 comparison tables", "", f"**Status: {report['status']}**. No winner is assigned.", "",
             f"Valid results: {report['completeness']['valid_results']}/{report['completeness']['expected_results']}; "
             f"preselected performance records: {report['performance']['completed']}/{report['performance']['expected']}.", "",
             "Accuracy tables use percent; paired differences use percentage points. SD is across training seeds.", ""]
    for title, section in (("Mechanism", "mechanism"), ("Representation", "representation"), ("Scaling", "scaling")):
        lines += [f"## {title}", "", "| Configuration / task | Architecture | Seeds | Accuracy % mean ± SD | CE mean ± SD | Parameters | Train CPU s mean ± SD | Train wall s mean ± SD |", "|---|---|---:|---:|---:|---:|---:|---:|"]
        for row in report[section]:
            spec, m = row["spec"], row["metrics"]
            label = spec["task"] if section != "scaling" else f"{row['configuration']} {spec.get('axis')} W{spec['width']} D{spec['depth']} N{spec['train_size']} T{spec['length']} {spec['task']}"
            lines.append(f"| {label} | {spec['architecture']} | {len(row['completed_seeds'])}/{len(row['expected_seeds'])} | {mean_sd(m['accuracy'],100)} | {mean_sd(m['cross_entropy'])} | {f(row['parameters']['total']['mean'],0)} | {mean_sd(m['training_cpu_seconds'])} | {mean_sd(m['training_wall_seconds'])} |")
        lines += [""]
    lines += ["## Multimodal query and conflicting-label subsets", "", "These are target accuracies conditional on the requested modality, not separate frozen-encoder probes. Conflict cases have different image and spoken digits. Mean ± sample SD is across training seeds.", "", "| Stage | Architecture | Seeds | Overall % | Image-query % | Spoken-query % | Conflicting-label % |", "|---|---|---:|---:|---:|---:|---:|"]
    for section in ("mechanism", "representation"):
        for row in report[section]:
            if row["spec"]["task"] != "multimodal_select":
                continue
            m = row["metrics"]
            lines.append(f"| {section} | {row['spec']['architecture']} | {len(row['completed_seeds'])}/{len(row['expected_seeds'])} | {mean_sd(m['accuracy'],100)} | {mean_sd(m['image_accuracy'],100)} | {mean_sd(m['spoken_accuracy'],100)} | {mean_sd(m['conflict_accuracy'],100)} |")
    lines += [""]
    lines += ["## All four prespecified mechanism contrasts per task", "", "The protocol contains no Boolean success formula. The 1 pp practical-effect value is a reference, not a newly imposed pass/fail rule.", "", "| Task | Contrast | Paired seeds | Accuracy difference pp | 98.75% CI pp | Practical reference pp | Status |", "|---|---|---:|---:|---:|---:|---|"]
    for row in report["mechanism_contrasts"]:
        interval = row["accuracy"]
        scaled = {key: None if interval[key] is None else 100 * interval[key] for key in ("mean", "lower", "upper")}
        lines.append(f"| {row['task']} | {row['contrast']} | {len(row['paired_seeds'])}/5 | {f(scaled['mean'],3)} | [{f(scaled['lower'],3)}, {f(scaled['upper'],3)}] | {100*row['practical_accuracy_threshold']:.2f} | {row['status']} |")
    lines += ["", "## Every scaling seed: validation versus cumulative training CPU", "", "Each point is `update: CPU seconds / validation CE / validation accuracy %`; these are the three registered checkpoints, not interpolated convergence curves.", "", "| Configuration | Architecture | Seed | Points |", "|---|---|---:|---|"]
    for row in report["scaling"]:
        for curve in row["validation_cpu_curves"]:
            points = "; ".join(f"{p['update']}: {p['training_cpu_seconds']:.3f}s / {p['validation_ce']:.4f} / {100*p['validation_accuracy']:.2f}%" for p in curve["points"]) or "pending"
            lines.append(f"| {row['configuration']} | {row['spec']['architecture']} | {curve['seed']} | {points} |")
    lines += ["", "## Every preselected inference measurement", "", "Batch 16, CPU-only; warmup and profiler are outside latency samples. FLOPs below are **partial**, and allocations are **not RSS**.", "", "| Run | Status | Wall median / p95 ms | CPU median ms | Examples/s median / p95 | Partial MFLOPs | Created / peak additional MiB |", "|---|---|---:|---:|---:|---:|---:|"]
    for row in report["performance"]["rows"]:
        if row["status"] != "complete":
            lines.append(f"| {row['run_id']} | {row['status']} | pending | pending | pending | pending | pending |")
            continue
        m, alloc = row["measurement"], row["allocations"]
        flops = row["observed_formula_flops"]
        memory = "unavailable" if alloc["status"] != "available" else f"{alloc['forward_created_bytes']/2**20:.3f} / {alloc['peak_increment_over_preexisting_bytes']/2**20:.3f}"
        lines.append(f"| {row['run_id']} | complete | {1000*m['wall_latency_seconds']['median']:.3f} / {1000*m['wall_latency_seconds']['p95']:.3f} | {1000*m['process_cpu_seconds_stats']['median']:.3f} | {m['examples_per_second']['median']:.1f} / {m['examples_per_second']['p95']:.1f} | {f(None if flops is None else flops/1e6,3)} | {memory} |")
    costs = report["costs"]
    lines += ["", "## Cost ledger", "", "| Completed stage | Runs | Recorded training CPU s | Total RESULT CPU s | Summed RESULT job-wall s |", "|---|---:|---:|---:|---:|"]
    for stage, row in costs["completed_result_costs_by_stage"].items():
        lines.append(f"| {stage} | {row['completed_runs']} | {row['recorded_training_cpu_seconds']:.3f} | {row['result_total_cpu_seconds']:.3f} | {row['result_total_wall_seconds']:.3f} |")
    lines += ["", "### Representation costs by architecture", "", "Each complete architecture total covers the same four tasks × three seeds × 240 updates; sums are recorded job costs, not calendar elapsed time or inference latency.", "", "| Architecture | Completed runs | Summed training CPU s | Summed training job-wall s | Summed RESULT CPU s |", "|---|---:|---:|---:|---:|"]
    architectures = dict.fromkeys(row["spec"]["architecture"] for row in report["representation"])
    for architecture in architectures:
        rows = [row for row in report["representation"] if row["spec"]["architecture"] == architecture]
        count = sum(len(row["completed_seeds"]) for row in rows)
        totals = [sum(row["metrics"][key]["n"] * (row["metrics"][key]["mean"] or 0) for row in rows)
                  for key in ("training_cpu_seconds", "training_wall_seconds", "total_cpu_seconds")]
        lines.append(f"| {architecture} | {count}/12 | {totals[0]:.3f} | {totals[1]:.3f} | {totals[2]:.3f} |")
    lines += ["", f"All external training/study attempts: {costs['all_execution_attempts']}. Successful attempts: {costs['successful_execution_attempts']}; accumulated job-wall {costs['successful_attempt_accumulated_job_wall_seconds']:.3f}s.", "", f"Failed attempts: {costs['failed_execution_attempts']}; accumulated job-wall {costs['failed_attempt_accumulated_job_wall_seconds']:.3f}s. Failed attempts with unknown process-CPU: {costs['failed_attempts_with_unknown_cpu']}.", "", f"Inference measurement arithmetic audits passed: {report['performance']['arithmetic_audits_passed']}/{report['performance']['expected']}; recorded whole-profile work: {report['performance']['total_measurement_work_cpu_seconds']:.3f} CPU seconds, {report['performance']['total_measurement_work_wall_seconds']:.3f} wall seconds. This includes data, warmup and profiler overhead, unlike the latency samples.", "", "These overlapping job-wall sums are not calendar elapsed time. Failed resource attempts are retained and charged separately.", "", "| Failed run | Attempt | Exit | Wall s |", "|---|---|---:|---:|"]
    for attempt in costs["attempts"]:
        if attempt["status"] != "completed" or attempt["exit_code"] != 0:
            lines.append(f"| {attempt['run_id']} | {attempt['receipt']} | {attempt['exit_code']} | {attempt['wall_seconds']:.3f} |")
    lines += ["", "## Scope and limitations", ""] + [f"- {note}" for note in NOTES]
    lines += ["", "All planned rows are retained; pending/invalid entries are not zero scores. Detailed unsupported operator lists, allocation categories, matching receipts, and seed curves are in COMPARISON_SUMMARY.json.", ""]
    return "\n".join(lines)


def summarize(root, protocol_path):
    inventory, protocol = read_json(root / "RUNS.json"), read_json(protocol_path)
    valid, issues, zeros, invalid_grads = load_results(root, inventory)
    inventory_digest = hashlib.sha256(json.dumps(inventory["runs"], sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    if inventory_digest != protocol["runs_sha256"]:
        issues.append({"run_id": None, "error": "registered inventory differs from protocol digest"})
    expected_ids = {run["run_id"] for run in inventory["runs"]}
    unexpected = sorted(str(path.parent.relative_to(root)) for path in root.rglob("RESULT.json") if str(path.parent.relative_to(root)) not in expected_ids)
    report = {"schema": "hcsn-comparison-summary-v1", "generated_utc": datetime.now(timezone.utc).isoformat(),
              "analysis_script_sha256": digest(__file__), "source_seal": inventory["source_seal"],
              "protocol_sha256": digest(protocol_path), "no_winner_selected": True,
              "completeness": {"expected_results": len(inventory["runs"]), "valid_results": len(valid),
                               "missing_or_invalid": sorted(expected_ids - set(valid)), "unexpected_results": unexpected},
              "input_issues": issues, "first_update_gradient_audit": {"missing_or_nonfinite": invalid_grads,
                                                                       "zero_l1": zeros,
                                                                       "zero_scope": "Zero at first batch does not alone prove an unused parameter"},
              "notes": NOTES}
    for section in ("mechanism", "representation", "scaling"):
        report[section] = aggregate_section(section, inventory["runs"], valid)
    report["mechanism_contrasts"] = mechanism_contrasts(protocol, valid)
    report["costs"] = collect_costs(root, inventory["runs"], valid)
    report["performance"] = collect_performance(root, inventory["runs"], valid)
    execution_path = root / "MEASUREMENT_EXECUTION.json"
    if execution_path.exists():
        execution = read_json(execution_path)
        report["performance"]["external_execution"] = {key: execution[key] for key in
            ("exit_code", "elapsed_seconds", "child_user_cpu_seconds", "child_system_cpu_seconds", "scope")}
    report["observed_counts_by_stage"] = dict(Counter(item["spec"]["stage"] for item in valid.values()))
    audit_path = root / "AUDIT.json"
    report["independent_artifact_audit"] = read_json(audit_path).get("status") if audit_path.exists() else "pending"
    complete = len(valid) == len(inventory["runs"]) and report["performance"]["completed"] == report["performance"]["expected"]
    paired_mismatch = any(row["pair_mismatch_seeds"] for row in report["mechanism_contrasts"])
    clean = not issues and not unexpected and not invalid_grads and not paired_mismatch and report["performance"]["fixed_batch_hash_consistent"]
    report["status"] = "complete" if complete and clean else "incomplete"
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--results", type=Path, default=Path(__file__).resolve().parent.parent)
    parser.add_argument("--protocol", type=Path)
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--require-complete", action="store_true")
    args = parser.parse_args()
    root = args.results.resolve()
    report = summarize(root, args.protocol or root.parent.parent / "PROTOCOL.json")
    output = args.output_dir or root / "analysis"
    output.mkdir(parents=True, exist_ok=True)
    for name, content in (("COMPARISON_SUMMARY.json", json.dumps(report, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n"),
                          ("COMPARISON_TABLES.md", markdown(report))):
        temporary = output / (name + ".tmp")
        temporary.write_text(content)
        temporary.replace(output / name)
    print(json.dumps({"status": report["status"], "missing_results": len(report["completeness"]["missing_or_invalid"]),
                      "completed_results": report["completeness"]["valid_results"],
                      "completed_performance": report["performance"]["completed"], "output": str(output)}))
    if args.require_complete and report["status"] != "complete":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
