"""Predeclared, paired source-group comparisons of two completed Cell studies.

All targets, seeds and budgets are retained. Bootstrap draws resample heldout
source groups jointly across tasks, seeds, arms and Encoders. These descriptive
intervals condition on this corpus, target definitions and fitted models; they do
not establish independent task families, repair success or deployment quality.
"""

import argparse
import csv
import hashlib
import json
from pathlib import Path
import platform
import time

import numpy as np

from cell_learning_metrics import task_metrics


SEEDS, BUDGETS = (7, 17, 29), (8, 32, 128)
ARMS = ("exact", "bm25", "dense_nearest", "prototype", "linear", "gated", "residual")
PRIMARY = ("balanced_accuracy", "nll", "positive_recall", "coverage", "overall_success")
SECONDARY = ("forced_accuracy", "brier_multiclass_sum", "ece10_equal_width")
CANDIDATES = ("granite97m", "embeddinggemma2_740m")
DRAWS, BOOTSTRAP_SEED = 2000, 20261023
PLANNED_KEYS = ((128, "gated", "trained"), (128, "linear", "trained"),
                (128, "prototype", "trained"), (128, "gated", "parameters_off"),
                (128, "gated", "shuffled_parameters"), (8, "gated", "trained"))


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def sha_file(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def inventory_digest(root):
    files = []
    for path in sorted(root.rglob("*")):
        if path.is_symlink():
            raise ValueError("linked study artifacts are unsupported")
        if path.is_file():
            files.append([str(path.relative_to(root)), path.stat().st_size, sha_file(path)])
    return hashlib.sha256(canonical(files)).hexdigest()


def fixed_contrasts():
    contrasts = []
    for candidate in CANDIDATES:
        for right in PLANNED_KEYS[1:]:
            contrasts.append({"id": f"{candidate}_gated128_minus_{right[1]}{right[0]}_{right[2]}",
                "left": (candidate, *PLANNED_KEYS[0]), "right": (candidate, *right)})
    contrasts.append({"id": "embeddinggemma2_gated128_minus_granite97m_gated128",
        "left": (CANDIDATES[1], *PLANNED_KEYS[0]), "right": (CANDIDATES[0], *PLANNED_KEYS[0])})
    return contrasts


def event_state(probability, labels, eligible, threshold=0.7):
    """Per-seed scores: average NLLs and decisions, never ensemble probabilities."""
    p, y = np.asarray(probability, dtype=np.float64), np.asarray(labels)
    metric = task_metrics(p, y, threshold=threshold, eligible=eligible)
    if p.shape[1] != 2:
        raise ValueError("this predeclared comparison requires binary tasks")
    correct = p.argmax(axis=1) == y
    accepted = np.asarray(eligible) & (p.max(axis=1) >= threshold)
    nll = -np.log(np.clip(p[np.arange(len(y)), y], 1e-15, 1))
    return np.stack((correct, nll, accepted, correct & accepted)).astype(np.float64), metric


def bootstrap_counts(source_groups, draws=DRAWS, seed=BOOTSTRAP_SEED):
    if (not isinstance(source_groups, (list, tuple)) or not 2 <= len(source_groups) <= 16384
            or len(set(source_groups)) != len(source_groups)
            or any(type(group) is not str or not group for group in source_groups)
            or type(draws) is not int or not 1 <= draws <= 10000 or type(seed) is not int or seed < 0):
        raise ValueError("distinct source groups and bounded bootstrap plan required")
    count = len(source_groups)
    return np.random.default_rng(seed).multinomial(count, np.full(count, 1 / count), size=draws).astype(np.uint16)


def resampled_metrics(state, labels, counts):
    """State is already averaged across seeds: [correct,nll,accepted,success],T,N."""
    values, y, weights = np.asarray(state), np.asarray(labels), np.asarray(counts)
    if (values.ndim != 3 or values.shape[0] != 4 or y.shape != values.shape[1:]
            or y.dtype.kind not in "iu" or not np.isin(y, [0, 1]).all()
            or not np.isfinite(values).all() or np.any(values < 0)
            or np.any(values[[0, 2, 3]] > 1) or np.any(values[3] > values[0])
            or np.any(values[3] > values[2]) or weights.ndim != 2
            or weights.shape[1] != y.shape[1] or weights.dtype.kind not in "iu"
            or np.any(weights < 0) or np.any(weights.sum(axis=1) == 0)):
        raise ValueError("invalid source-group bootstrap state, targets or weights")
    w = weights.astype(np.float64).T
    positive, negative = y @ w, (1 - y) @ w
    pos_correct, neg_correct = (values[0] * y) @ w, (values[0] * (1 - y)) @ w
    pos_recall = np.divide(pos_correct, positive, out=np.full_like(positive, np.nan), where=positive > 0)
    neg_recall = np.divide(neg_correct, negative, out=np.full_like(negative, np.nan), where=negative > 0)
    total = weights.sum(axis=1)
    return {"balanced_accuracy": ((pos_recall + neg_recall) / 2).mean(axis=0),
        "positive_recall": pos_recall.mean(axis=0),
        "nll": values[1].mean(axis=0) @ w / total,
        "coverage": values[2].mean(axis=0) @ w / total,
        "overall_success": values[3].mean(axis=0) @ w / total}


def paired_interval(left, right):
    a, b = np.asarray(left, dtype=np.float64), np.asarray(right, dtype=np.float64)
    if a.shape != b.shape or a.ndim != 1 or len(a) == 0:
        raise ValueError("equal nonempty paired draw arrays required")
    difference = a - b
    valid = np.isfinite(difference)
    interval = np.quantile(difference[valid], [0.025, 0.975]).tolist() if valid.any() else None
    return {"ci95_percentile": interval, "valid_draws": int(valid.sum()),
            "undefined_missing_class_draws": int((~valid).sum())}, difference


def collect_study(directory, dataset, dataset_sha, candidate, labels, heldout_ids):
    root = Path(directory)
    plan = json.loads((root / "study-plan.json").read_bytes())
    summary = json.loads((root / "summary.json").read_bytes())
    feature_path = root.parent / "features" / "report.json"
    feature = json.loads(feature_path.read_bytes())
    if (plan["dataset_sha256"] != dataset_sha or plan["selected_tasks"] != dataset["selected_tasks"]
            or plan["budgets"] != list(BUDGETS) or plan["seeds"] != list(SEEDS) or plan["steps"] != 200
            or plan["threshold"] != 0.7 or plan["task_family_count"] != 1
            or summary["plan"] != plan or summary["task_count"] != len(labels)
            or sha_file(feature_path) != plan["feature_receipt_sha256"]
            or feature["plan"]["candidate"] != candidate or feature["feature_identity"] != plan["feature_identity"]):
        raise ValueError("completed study, feature candidate or fixed analysis plan differs")
    binding = hashlib.sha256(canonical(plan)).hexdigest()
    states = {key: np.zeros((4, *labels.shape)) for key in PLANNED_KEYS}
    records, receipts = [], []
    for task_index, task in enumerate(dataset["selected_tasks"]):
        curve_dir = root / "curves" / task
        seal = json.loads((root / "completed" / (task + ".json")).read_bytes())
        inventory = inventory_digest(curve_dir)
        if seal["task"] != task or seal["plan_sha256"] != binding or seal["inventory_sha256"] != inventory:
            raise ValueError("completed task inventory or plan binding changed")
        report_path = curve_dir / "report.json"
        report = json.loads(report_path.read_bytes())
        if (report["status"] != "complete" or report["unavailable"]
                or report["holdout_source_ids"] != heldout_ids
                or len(report["runs"]) != len(SEEDS) * len(BUDGETS)):
            raise ValueError("incomplete task or inconsistent paired holdout order")
        seen = set()
        for run in report["runs"]:
            run_key = (run["seed"], run["budget"])
            if run_key in seen or run_key not in {(s, n) for s in SEEDS for n in BUDGETS} or set(run["arms"]) != set(ARMS):
                raise ValueError("duplicate or missing seed, budget or arm")
            seen.add(run_key)
            for arm, output in run["arms"].items():
                expected = {"parameters_off", "shuffled_parameters"} if arm in ARMS[4:] else set()
                if set(output.get("controls", {})) != expected:
                    raise ValueError("parameter controls missing or unexpected")
                for control, scored in [("trained", output), *output.get("controls", {}).items()]:
                    state, metric = event_state(scored["probabilities"], labels[task_index], scored["eligible"])
                    for name in PRIMARY + SECONDARY:
                        if not np.isclose(metric[name], scored["semantic"][name], rtol=1e-10, atol=1e-12):
                            raise ValueError("stored semantic metric differs from frozen predictions")
                    key = (run["budget"], arm, control)
                    if key in states:
                        states[key][:, task_index] += state / len(SEEDS)
                    records.append({"candidate": candidate, "task": task, "seed": run["seed"],
                        "budget": run["budget"], "arm": arm, "control": control,
                        **{name: metric[name] for name in PRIMARY + SECONDARY}})
        receipts.append({"task": task, "inventory_sha256": inventory, "report_sha256": sha_file(report_path)})
    return states, records, {"directory": str(root.resolve()), "study_plan_sha256": sha_file(root / "study-plan.json"),
                             "feature_receipt_sha256": sha_file(feature_path), "task_receipts": receipts}


def aggregate_records(records):
    groups = {}
    for row in records:
        groups.setdefault((row["candidate"], row["budget"], row["arm"], row["control"]), []).append(row)
    result = []
    for (candidate, budget, arm, control), items in sorted(groups.items()):
        result.append({"candidate": candidate, "budget": budget, "arm": arm, "control": control,
            "task_count": len({item["task"] for item in items}), "task_seed_observations": len(items),
            "metrics": {name: {"macro_mean": float(np.mean([item[name] for item in items])),
                "seed_macro_means": {str(seed): float(np.mean([item[name] for item in items if item["seed"] == seed]))
                                     for seed in SEEDS}} for name in PRIMARY + SECONDARY}})
    return result


def summarize(dataset, granite_study, eg2_study, output):
    dataset_path, root = Path(dataset), Path(output)
    dataset_sha = sha_file(dataset_path)
    data = json.loads(dataset_path.read_bytes())
    tasks = data["selected_tasks"]
    heldout = [row for row in data["rows"] if row["split"] == "holdout"]
    if len(tasks) != 32 or len(set(tasks)) != 32 or len(heldout) != 456:
        raise ValueError("fixed analysis requires all32 declared tasks and456 heldout groups")
    labels = np.array([[row["labels"][task] for row in heldout] for task in tasks], dtype=np.int64)
    if any(type(row["labels"][task]) is not int for row in heldout for task in tasks):
        raise ValueError("binary evaluation targets must be exact integers")
    if not np.isin(labels, [0, 1]).all() or np.any(labels.sum(axis=1) == 0) or np.any(labels.sum(axis=1) == len(heldout)):
        raise ValueError("both classes required in every declared evaluation target")
    groups = [row["group_id"] for row in heldout]
    counts = bootstrap_counts(groups)
    for directory in (granite_study, eg2_study):
        if not (Path(directory) / "summary.json").is_file():
            raise ValueError("wait for both complete study summaries before analysis")
    root.mkdir(parents=True, exist_ok=False)
    began = time.perf_counter_ns()
    plan = {"schema": "hepta.paired-cell-study-comparison.v1", "dataset_sha256": dataset_sha,
        "tasks": tasks, "task_families": 1, "budgets": BUDGETS, "seeds": SEEDS,
        "bootstrap_draws": DRAWS, "bootstrap_seed": BOOTSTRAP_SEED, "generator": "NumPy PCG64 multinomial",
        "source_groups": groups, "contrasts": fixed_contrasts(), "primary_metrics": PRIMARY,
        "sampling": "one heldout-group count vector jointly applied to every target, seed, arm and Encoder",
        "seed_averaging": "average per-event losses and decisions across seeds before each shared resample",
        "interval": "paired percentile 2.5/97.5; descriptive, no multiplicity correction",
        "missing_class_policy": "a metric draw is undefined if any required task class has zero resampled support",
        "selection": "all32 fixed tasks, all3 seeds, all3 budgets; no heldout-based winner selection",
        "source_sha256": sha_file(__file__), "numpy": np.__version__, "python": platform.python_version()}
    (root / "analysis-plan.json").write_bytes(canonical(plan) + b"\n")
    states, records, receipts = {}, [], {}
    for candidate, directory in zip(CANDIDATES, (granite_study, eg2_study), strict=True):
        current, rows, receipt = collect_study(directory, data, dataset_sha, candidate, labels,
                                               [row["source_id"] for row in heldout])
        states.update({(candidate, *key): value for key, value in current.items()})
        records.extend(rows)
        receipts[candidate] = receipt
    point_counts = np.ones((1, len(heldout)), dtype=np.uint16)
    points = {key: resampled_metrics(state, labels, point_counts) for key, state in states.items()}
    draws = {key: resampled_metrics(state, labels, counts) for key, state in states.items()}
    contrasts, arrays = [], {"source_group_counts": counts}
    for contrast in fixed_contrasts():
        left, right = tuple(contrast["left"]), tuple(contrast["right"])
        metrics = {}
        for name in PRIMARY:
            interval, difference = paired_interval(draws[left][name], draws[right][name])
            metrics[name] = {"left": float(points[left][name][0]), "right": float(points[right][name][0]),
                "difference_left_minus_right": float(points[left][name][0] - points[right][name][0]),
                "preferred_direction": "lower" if name == "nll" else "higher", **interval}
            arrays[contrast["id"] + "__" + name] = difference
        contrasts.append({**contrast, "metrics": metrics})
    with (root / "bootstrap-draws.npz").open("xb") as stream:
        np.savez_compressed(stream, **arrays)
    with (root / "task-metrics.csv").open("x", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(records[0]))
        writer.writeheader()
        writer.writerows(records)
    result = {"plan": plan, "inputs": receipts, "aggregate": aggregate_records(records), "contrasts": contrasts,
        "inference_scope": "fixed heldout source groups conditional on these targets, training sets and fitted models",
        "task_seed_rows_are_independent_trials": False, "human_validated_repair_success_measured": False,
        "causal_or_general_foundation_winner_established": False, "wall_ns": time.perf_counter_ns() - began}
    if sha_file(dataset_path) != dataset_sha or sha_file(__file__) != plan["source_sha256"]:
        raise ValueError("analysis source or target corpus changed")
    for candidate, receipt in receipts.items():
        current_root = Path(receipt["directory"])
        for task_receipt in receipt["task_receipts"]:
            if inventory_digest(current_root / "curves" / task_receipt["task"]) != task_receipt["inventory_sha256"]:
                raise ValueError("paired study artifacts changed during analysis")
    (root / "comparison.json").write_bytes(canonical(result) + b"\n")
    manifest = {path.name: {"sha256": sha_file(path), "bytes": path.stat().st_size} for path in sorted(root.iterdir())}
    (root / "manifest.json").write_bytes(canonical(manifest) + b"\n")
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("dataset", "granite-study", "eg2-study", "output"):
        parser.add_argument("--" + name, required=True)
    result = summarize(**vars(parser.parse_args()))
    print(json.dumps({"tasks": len(result["plan"]["tasks"]), "contrasts": len(result["contrasts"]),
                      "bootstrap_draws": DRAWS, "output": "comparison.json"}))


if __name__ == "__main__":
    main()
