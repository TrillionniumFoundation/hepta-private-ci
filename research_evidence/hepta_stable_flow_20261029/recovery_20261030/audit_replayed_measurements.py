"""Independently audit saved predictions and replay timing without model execution."""

import collections
import datetime
import hashlib
import io
import json
import math
import statistics
import sys
import traceback
from pathlib import Path

import numpy as np
import scipy
from scipy.special import logsumexp
from scipy.stats import t as student_t


ROOT = Path(__file__).resolve().parents[3]
BASE = Path("research_evidence/hepta_stable_flow_20261029")
FORMAL = BASE / "formal_run001"
RUNTIME = BASE / "inference_cost_replay_20261030"
OUTPUT = BASE / "recovery_20261030"
inputs = {}
counts = collections.Counter()
mismatches = []
primary_observations = []
comparison_observations = []
runtime_observations = []
quality_observations = []


def read_bytes(path):
    path = Path(path)
    payload = (ROOT / path).read_bytes()
    inputs[str(path)] = {
        "path": str(path),
        "bytes": len(payload),
        "sha256": hashlib.sha256(payload).hexdigest(),
    }
    return payload


def read_json(path):
    return json.loads(read_bytes(path))


def read_npz(path):
    with np.load(io.BytesIO(read_bytes(path)), allow_pickle=False) as archive:
        return {name: archive[name].copy() for name in archive.files}


def check(label, actual, expected, category):
    counts[category] += 1
    if actual != expected:
        mismatches.append({"check": label, "actual": actual, "expected": expected})


def near(label, actual, expected, category, tolerance=1e-12):
    counts[category] += 1
    difference = abs(float(actual) - float(expected))
    if not math.isfinite(difference) or difference > tolerance:
        mismatches.append(
            {
                "check": label,
                "actual": float(actual),
                "expected": float(expected),
                "absolute_difference": difference,
                "absolute_tolerance": tolerance,
            }
        )
    return difference


def digest_check(path, expected, label):
    read_bytes(path)
    check(label, inputs[str(path)]["sha256"], expected, "file_hash_checks")


def slot(row):
    return row["task"], row["arm"], row["seed"], row["regime"]


def audit_primary():
    protocol = read_json(FORMAL / "protocol.json")
    primary = read_json(FORMAL / "results.json")
    selected = read_json(FORMAL / "selection.json")
    seal = read_json(FORMAL / "selection_seal.json")
    check(
        "sealed selection",
        inputs[str(FORMAL / "selection.json")]["sha256"],
        seal["selection_sha256"],
        "binding_checks",
    )
    selection = {slot(row): row for row in selected["selected"]}
    indexed = {slot(row): row for row in primary["results"]}
    check("selected aliases", len(selection), 60, "coverage_checks")
    check("primary aliases", len(indexed), 60, "coverage_checks")
    check("primary rows", len(primary["results"]), 60, "coverage_checks")
    check("primary/selection slots", set(indexed) == set(selection), True, "coverage_checks")
    test_data = {
        task: read_npz(FORMAL / "data" / task / "test.npz")
        for task in sorted({row["task"] for row in primary["results"]})
    }
    for row in primary["results"]:
        key = slot(row)
        label = "/".join(map(str, key))
        for name, expected in selection[key].items():
            check(label + "/selection/" + name, row[name], expected, "selection_identity_checks")
        path = FORMAL / row["prediction_file"]
        arrays = read_npz(path)
        check(label + "/prediction digest", inputs[str(path)]["sha256"], row["prediction_sha256"], "file_hash_checks")
        checkpoint = FORMAL / "candidates" / row["id"] / (row["checkpoint"] + ".npz")
        digest_check(checkpoint, row["checkpoint_sha256"], label + "/checkpoint")
        check(label + "/NPZ keys", sorted(arrays), ["logits", "refined_logits_first64", "targets"], "array_contract_checks")
        logits, targets = arrays["logits"], arrays["targets"]
        check(label + "/logits shape", list(logits.shape), [512, 32, 8], "array_contract_checks")
        check(label + "/targets shape", list(targets.shape), [512, 32], "array_contract_checks")
        check(label + "/refined shape", list(arrays["refined_logits_first64"].shape), [64, 32, 8], "array_contract_checks")
        check(label + "/logits dtype", str(logits.dtype), "float32", "array_contract_checks")
        check(label + "/finite logits", bool(np.isfinite(logits).all()), True, "array_contract_checks")
        check(label + "/test targets", bool(np.array_equal(targets, test_data[row["task"]]["targets"])), True, "array_contract_checks")
        mask = targets != -100
        scores = logits[mask].astype(np.float64)
        labels = targets[mask]
        losses = logsumexp(scores, axis=1) - scores[np.arange(len(labels)), labels]
        hits = logits.argmax(axis=-1) == targets
        computed = {
            "accuracy": float(hits[mask].mean()),
            "sequence_accuracy": float(np.logical_or(hits, ~mask).all(axis=1).mean()),
            "queries": int(mask.sum()),
            "examples": int(targets.shape[0]),
            "cross_entropy": float(losses.mean()),
        }
        for metric in ("accuracy", "sequence_accuracy", "queries", "examples"):
            check(label + "/" + metric, computed[metric], row["test"][metric], "primary_metric_checks")
        ce_difference = near(
            label + "/cross_entropy",
            computed["cross_entropy"],
            row["test"]["cross_entropy"],
            "primary_metric_checks",
            1e-6,
        )
        primary_observations.append(
            {"slot": list(key), "computed": computed, "saved": row["test"], "cross_entropy_absolute_difference": ce_difference}
        )
    seeds = sorted({row["seed"] for row in primary["results"]})
    check("three paired training seeds", len(seeds), 3, "coverage_checks")
    check("comparison rows", len(primary["comparisons"]), 24, "coverage_checks")
    expected_comparison_keys = {
        (task, regime, comparator, metric)
        for task in test_data
        for regime in protocol["selection_checkpoints"]
        for comparator in ("matched_c1", "sigmoid", "ordinary")
        for metric in ("accuracy", "cross_entropy")
    }
    actual_comparison_keys = {
        (row["task"], row["regime"], row["comparator"], row["metric"])
        for row in primary["comparisons"]
    }
    check("comparison coverage", actual_comparison_keys == expected_comparison_keys, True, "coverage_checks")
    for row in primary["comparisons"]:
        task, regime, comparator, metric = row["task"], row["regime"], row["comparator"], row["metric"]
        label = "/".join((task, regime, comparator, metric))
        left = [indexed[task, "analytic", seed, regime] for seed in seeds]
        right = [indexed[task, comparator, seed, regime] for seed in seeds]
        differences = [
            (a["test"][metric] - b["test"][metric]) * (1 if metric == "accuracy" else -1)
            for a, b in zip(left, right)
        ]
        family = 4 if comparator == "matched_c1" else 8
        critical = float(student_t.ppf(1 - 0.05 / (2 * family), df=2))
        mean = statistics.mean(differences)
        radius = critical * statistics.stdev(differences) / math.sqrt(3)
        interval = [mean - radius, mean + radius]
        quality = all(x["validation"]["accuracy"] >= 0.9 for x in left + right) and all(x["test"]["accuracy"] >= 0.9 for x in left)
        gate = quality and interval[0] > 0 and mean >= protocol["minimum_mean_effect"][metric]
        check(label + "/family", row["family_size"], family, "comparison_contract_checks")
        check(label + "/direction", row["positive_favors_analytic"], True, "comparison_contract_checks")
        check(label + "/quality", row["quality_floor_passed"], quality, "comparison_contract_checks")
        check(label + "/gate", row["metric_improvement_gate"], gate, "comparison_contract_checks")
        for i, value in enumerate(differences):
            near(label + "/paired/" + str(i), row["paired_seed_differences"][i], value, "comparison_numeric_checks")
        near(label + "/mean", row["mean"], mean, "comparison_numeric_checks")
        for i, value in enumerate(interval):
            near(label + "/CI/" + str(i), row["adjusted_ci"][i], value, "comparison_numeric_checks", 1e-9)
        comparison_observations.append(
            {"task": task, "regime": regime, "comparator": comparator, "metric": metric, "family_size_per_metric": family, "student_t_df": 2, "scipy_t_critical": critical, "paired_seed_differences": differences, "mean": mean, "adjusted_ci": interval, "quality_floor_passed": quality, "metric_improvement_gate": gate}
        )
    return primary, indexed


def independent_distribution(values):
    ordered = sorted(float(value) for value in values)
    def quantile(p):
        position = (len(ordered) - 1) * p
        lower, upper = math.floor(position), math.ceil(position)
        return ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)
    return {
        "mean": statistics.mean(ordered),
        "median": statistics.median(ordered),
        "sample_standard_deviation": statistics.stdev(ordered),
        "minimum": ordered[0],
        "maximum": ordered[-1],
        "p25": quantile(0.25),
        "p75": quantile(0.75),
    }


def audit_runtime(primary, indexed):
    protocol = read_json(RUNTIME / "protocol.json")
    plan = read_json(RUNTIME / "execution/plan.json")
    summary = read_json(RUNTIME / "execution/summary.json")
    joined = read_json(RUNTIME / "quality_join.json")
    arrays = read_npz(RUNTIME / "execution/raw_times.npz")
    events = [json.loads(line) for line in read_bytes(RUNTIME / "execution/raw_events.jsonl").decode().splitlines()]
    for field, path in (
        ("execution_plan_sha256", RUNTIME / "execution/plan.json"),
        ("raw_times_sha256", RUNTIME / "execution/raw_times.npz"),
        ("raw_events_sha256", RUNTIME / "execution/raw_events.jsonl"),
    ):
        check(field, summary[field], inputs[str(path)]["sha256"], "binding_checks")
    for field, path in (
        ("primary_results_sha256", FORMAL / "results.json"),
        ("runtime_summary_sha256", RUNTIME / "execution/summary.json"),
        ("registered_protocol_sha256", RUNTIME / "protocol.json"),
    ):
        check("join/" + field, joined[field], inputs[str(path)]["sha256"], "binding_checks")
    check("timing case count", len(summary["cases"]), 40, "coverage_checks")
    check("timing event count", len(events), 440, "coverage_checks")
    check("runtime status", summary["status"], "complete", "coverage_checks")
    check("alias count", summary["alias_count"], 20, "coverage_checks")
    check("case count", summary["case_count"], 40, "coverage_checks")
    check("timed repetitions", summary["timed_repetitions_per_case"], 11, "coverage_checks")
    check("warmup rounds", len(plan["warmup_orders"]), 3, "coverage_checks")
    check("timed rounds", len(plan["timed_orders"]), 11, "coverage_checks")
    check("raw timing keys", sorted(arrays), ["cpu_nanoseconds", "wall_nanoseconds"], "array_contract_checks")
    for name, array in arrays.items():
        check(name + "/shape", list(array.shape), [40, 11], "array_contract_checks")
        check(name + "/dtype", str(array.dtype), "int64", "array_contract_checks")
        check(name + "/positive", bool(np.all(array > 0)), True, "array_contract_checks")
    for category in ("warmup_orders", "timed_orders"):
        for i, order in enumerate(plan[category]):
            check(category + "/" + str(i), sorted(order), list(range(40)), "order_checks")
    cursor = 0
    for repetition, order in enumerate(plan["timed_orders"]):
        for position, index in enumerate(order):
            expected = {
                "case_index": index,
                "case_id": summary["cases"][index]["case_id"],
                "repetition": repetition,
                "position": position,
                "cpu_nanoseconds": int(arrays["cpu_nanoseconds"][index, repetition]),
                "wall_nanoseconds": int(arrays["wall_nanoseconds"][index, repetition]),
            }
            check("raw event/" + str(cursor), events[cursor], expected, "raw_event_checks")
            cursor += 1
    timing = {}
    medians = {}
    max_numeric_difference = 0.0
    for i, case in enumerate(summary["cases"]):
        for field, value in plan["cases"][i].items():
            check(case["case_id"] + "/plan/" + field, case[field], value, "runtime_case_identity_checks")
        recomputed = {}
        for clock in ("cpu", "wall"):
            values = [int(value) * 1e-9 for value in arrays[clock + "_nanoseconds"][i]]
            distribution = independent_distribution(values)
            recomputed[clock] = distribution
            for name, value in distribution.items():
                difference = near(case["case_id"] + "/" + clock + "/" + name, case[clock + "_seconds"][name], value, "runtime_summary_numeric_checks")
                max_numeric_difference = max(max_numeric_difference, difference)
            medians[case["case_id"], clock] = distribution["median"]
        median = recomputed["wall"]["median"]
        derived = {
            "sequences_per_second_from_median_wall": case["batch_size"] / median,
            "external_tokens_per_second_from_median_wall": case["batch_size"] * case["sequence_length"] / median,
            "amortized_wall_seconds_per_sequence": median / case["batch_size"],
        }
        for name, value in derived.items():
            difference = near(case["case_id"] + "/" + name, case[name], value, "runtime_summary_numeric_checks", 1e-9)
            max_numeric_difference = max(max_numeric_difference, difference)
        for alias in case["aliases"]:
            key = slot(alias)
            check(case["case_id"] + "/checkpoint", alias["checkpoint_sha256"], indexed[key]["checkpoint_sha256"], "runtime_case_identity_checks")
            check(case["case_id"] + "/candidate", alias["id"], indexed[key]["id"], "runtime_case_identity_checks")
            timing[key, case["batch_size"]] = case
        runtime_observations.append({"case_id": case["case_id"], "raw_array_row": i, "cpu": recomputed["cpu"], "wall": recomputed["wall"], **derived})
    check("runtime derived statistics count", counts["runtime_summary_numeric_checks"], 680, "coverage_checks")
    rules = protocol["quality_join"]
    check("quality pairs", len(joined["comparisons"]), 16, "coverage_checks")
    expected_keys = {(task, regime, arm) for task in protocol["scope"]["tasks"] for regime in protocol["scope"]["regimes"] for arm in rules["comparators"]}
    actual_keys = {(r["task"], r["regime"], r["comparator"]) for r in joined["comparisons"]}
    check("quality pair coverage", actual_keys == expected_keys, True, "coverage_checks")
    for row in joined["comparisons"]:
        left_key = (row["task"], rules["reference_arm"], rules["timed_seed"], row["regime"])
        right_key = (row["task"], row["comparator"], rules["timed_seed"], row["regime"])
        left, right = indexed[left_key], indexed[right_key]
        gaps = {"test_accuracy": abs(left["test"]["accuracy"] - right["test"]["accuracy"]), "test_cross_entropy": abs(left["test"]["cross_entropy"] - right["test"]["cross_entropy"])}
        checks = {
            "both_validation_floor": min(left["validation"]["accuracy"], right["validation"]["accuracy"]) >= rules["both_validation_accuracy_min"],
            "both_test_floor": min(left["test"]["accuracy"], right["test"]["accuracy"]) >= rules["both_test_accuracy_min"],
            "test_accuracy_band": gaps["test_accuracy"] <= rules["absolute_test_accuracy_gap_max"],
            "test_cross_entropy_band": gaps["test_cross_entropy"] <= rules["absolute_test_cross_entropy_gap_max"],
        }
        eligible = all(checks.values())
        name = "/".join((row["task"], row["regime"], row["comparator"]))
        check(name + "/checks", row["checks"], checks, "quality_join_checks")
        check(name + "/gaps", row["absolute_score_gaps"], gaps, "quality_join_checks")
        check(name + "/eligible", row["empirical_quality_band_eligible"], eligible, "quality_join_checks")
        for label, item in (("analytic", left), ("comparator", right)):
            check(name + "/" + label + " scores", row[label + "_scores"], {field: item[field] for field in ("validation", "test")}, "quality_join_checks")
        ratios = {}
        if eligible:
            for batch in protocol["inputs"]["batch_sizes"]:
                a, b = timing[left_key, batch], timing[right_key, batch]
                observed = row["matched_band_cost_ratios"][str(batch)]
                expected = {"analytic_case": a["case_id"], "comparator_case": b["case_id"]}
                for clock in ("cpu", "wall"):
                    field = "analytic_to_comparator_" + clock + "_median_ratio"
                    expected[field] = medians[a["case_id"], clock] / medians[b["case_id"], clock]
                    near(name + "/" + str(batch) + "/" + field, observed[field], expected[field], "quality_ratio_numeric_checks")
                for field in ("analytic_case", "comparator_case"):
                    check(name + "/" + field, observed[field], expected[field], "quality_join_checks")
                ratios[str(batch)] = expected
        else:
            check(name + "/ineligible ratios absent", row["matched_band_cost_ratios"], {}, "quality_join_checks")
        quality_observations.append({"task": row["task"], "regime": row["regime"], "comparator": row["comparator"], "eligible": eligible, "checks": checks, "ratios": ratios})
    return max_numeric_difference


def main():
    started = datetime.datetime.now(datetime.UTC).isoformat()
    read_bytes(Path(__file__).relative_to(ROOT))
    for path in ("experiments/call_put_stable_flow/study.py", "experiments/call_put_stable_flow_appendix/runtime.py"):
        read_bytes(path)
    error = None
    maximum_runtime_difference = None
    try:
        primary, indexed = audit_primary()
        maximum_runtime_difference = audit_runtime(primary, indexed)
        for path, record in inputs.items():
            check("input unchanged/" + path, hashlib.sha256((ROOT / path).read_bytes()).hexdigest(), record["sha256"], "post_audit_immutability_checks")
    except Exception:
        error = traceback.format_exc()
        mismatches.append({"audit_execution_error": error})
    result = {
        "schema": "hepta-replayed-measurements-independent-audit-v1",
        "started_utc": started,
        "finished_utc": datetime.datetime.now(datetime.UTC).isoformat(),
        "status": "complete" if not mismatches else "failed",
        "artifact_integrity_passed": not mismatches,
        "environment": {"python": sys.version, "numpy": np.__version__, "scipy": scipy.__version__},
        "scope": "Saved primary predictions and comparisons, plus new inference_cost_replay_20261030 raw timings, statistics and descriptive quality join. No model forward, training or new scientific tests executed.",
        "primary_cross_entropy_reference": "Independent SciPy logsumexp in float64 over every scored saved logit. Original Torch FP32 batched CE uses a declared absolute comparison tolerance of 1e-6; accuracy and counts must match exactly.",
        "paired_interval_reference": "Independent scipy.stats.t.ppf with df=2 and Bonferroni family 4 for primary/8 for secondary, separately within each metric. CI numeric tolerance 1e-9.",
        "runtime_statistics_reference": "Independent Python statistics mean/median/stdev and explicit linear quantiles over int64 raw nanoseconds; distribution tolerance 1e-12 seconds, throughput tolerance 1e-9.",
        "raw_timing_array_shape": [40, 11],
        "raw_timing_array_dtype": "int64",
        "new_runtime_clocks_are_not_recovered_original_clocks": True,
        "primary_improvement_gates_passed": sum(row["metric_improvement_gate"] for row in comparison_observations),
        "primary_improvement_gates_total": len(comparison_observations),
        "runtime_quality_eligible_pairs": sum(row["eligible"] for row in quality_observations),
        "runtime_quality_pairs_total": len(quality_observations),
        "maximum_primary_ce_absolute_difference": max((row["cross_entropy_absolute_difference"] for row in primary_observations), default=None),
        "maximum_runtime_summary_absolute_difference": maximum_runtime_difference,
        "check_counts": dict(counts),
        "mismatch_count": len(mismatches),
        "mismatches": mismatches,
        "bound_inputs": [inputs[name] for name in sorted(inputs)],
        "primary_observations": primary_observations,
        "comparison_observations": comparison_observations,
        "runtime_observations": runtime_observations,
        "quality_observations": quality_observations,
    }
    target = ROOT / OUTPUT / "replayed_measurements_audit.json"
    if mismatches:
        index = 1
        while (ROOT / OUTPUT / f"replayed_measurements_audit_attempt{index:03d}.json").exists():
            index += 1
        target = ROOT / OUTPUT / f"replayed_measurements_audit_attempt{index:03d}.json"
    with target.open("x") as stream:
        json.dump(result, stream, indent=2, sort_keys=True, allow_nan=False)
        stream.write("\n")
    print(json.dumps({"output": str(target), "sha256": hashlib.sha256(target.read_bytes()).hexdigest(), "status": result["status"], "mismatches": mismatches, "check_counts": dict(counts), "primary_gates": [result["primary_improvement_gates_passed"], len(comparison_observations)], "runtime_eligible": [result["runtime_quality_eligible_pairs"], len(quality_observations)], "max_ce_error": result["maximum_primary_ce_absolute_difference"], "max_runtime_summary_error": maximum_runtime_difference}))
    if mismatches:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
