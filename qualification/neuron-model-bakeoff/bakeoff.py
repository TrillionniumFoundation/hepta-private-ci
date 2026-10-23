#!/usr/bin/env python3
"""Read-only Hepta DecisionCell model bakeoff. Never issues model authority."""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import random
import re
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

SCHEMA = "hepta.neuron.bakeoff.v1"
CANDIDATES = (
    "laya-english-421m", "laya-typed-421m", "laya-multilingual-322m",
    "arctic-embed-305m", "harrier-270m",
)
MODEL_REPOS = {
    "laya-english-421m": "convaiinnovations/laya",
    "laya-typed-421m": "convaiinnovations/laya-typed-decisions",
    "laya-multilingual-322m": "convaiinnovations/laya-multilingual",
    "arctic-embed-305m": "Snowflake/snowflake-arctic-embed-m-v2.0",
    "harrier-270m": "microsoft/harrier-oss-v1-270m",
}
EMBEDDING_MODELS = CANDIDATES[-2:]
HEAD_BUDGET_FIELDS = (
    "head_trainable_parameters", "head_epochs", "head_training_steps",
    "head_learning_rate", "head_l2", "head_seed", "projection",
)
SPLITS = ("train", "validation", "calibration", "future_test")
SHA256 = re.compile(r"[0-9a-f]{64}\Z")
REVISION = re.compile(r"[0-9a-f]{40}\Z")
REQUIRED_DIGESTS = ("weights", "tokenizer", "preprocessor", "head", "quantization", "runtime", "device")


class EvidenceError(ValueError):
    """Missing or malformed inputs cannot become positive evidence."""


def require(condition: bool, reason: str) -> None:
    if not condition:
        raise EvidenceError(reason)


def file_hash(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as reader:
        for chunk in iter(lambda: reader.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    require(isinstance(value, dict), f"{path}: expected object")
    return value


def load_jsonl(path: Path, *, max_records: int = 1_000_000) -> list[dict[str, Any]]:
    require(path.is_file(), f"missing file: {path}")
    require(path.stat().st_size <= 512 * 1024 * 1024, "input exceeds 512 MiB")
    rows: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as reader:
        for n, line in enumerate(reader, 1):
            if not line.strip():
                continue
            require(len(rows) < max_records, "record cap exceeded")
            row = json.loads(line)
            require(isinstance(row, dict), f"invalid row {n}")
            rows.append(row)
    require(bool(rows), f"empty input: {path}")
    return rows


def parse_time(value: Any) -> datetime:
    require(isinstance(value, str), "missing event timestamp")
    time = datetime.fromisoformat(value.replace("Z", "+00:00"))
    require(time.tzinfo is not None, "event timestamp must contain timezone")
    return time


def validate_dataset(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    by_id: dict[str, dict[str, Any]] = {}
    cluster_split: dict[str, str] = {}
    windows: dict[str, list[datetime]] = defaultdict(list)
    for row in rows:
        rid, cluster, split = row.get("id"), row.get("cluster"), row.get("split")
        require(isinstance(rid, str) and rid and rid not in by_id, "duplicate/invalid example id")
        require(isinstance(cluster, str) and cluster, f"{rid}: missing cluster")
        require(split in SPLITS, f"{rid}: unknown split")
        require(cluster_split.setdefault(cluster, split) == split, f"{rid}: cluster crosses split")
        options = row.get("options")
        require(isinstance(options, list) and 2 <= len(options) <= 128, f"{rid}: option count")
        require(all(isinstance(x, str) and x for x in options), f"{rid}: invalid option")
        require(len(set(options)) == len(options), f"{rid}: duplicate option")
        require(row.get("gold") in options, f"{rid}: gold label not in options")
        for name in ("language", "slice"):
            require(isinstance(row.get(name), str) and row[name], f"{rid}: missing {name}")
        require(type(row.get("ood")) is bool, f"{rid}: missing OOD label")
        windows[split].append(parse_time(row.get("event_time")))
        by_id[rid] = row
    require(all(windows[name] for name in SPLITS), "train/validation/calibration/future_test required")
    for earlier, later in zip(SPLITS, SPLITS[1:]):
        require(max(windows[earlier]) < min(windows[later]), f"split time leakage: {earlier} -> {later}")
    return by_id


def validate_run(
    run: dict[str, Any], model: str, dataset_hash: str, prediction_hash: str,
    source_commit: str, frozen_threshold: float,
) -> None:
    require(run.get("schema") == SCHEMA and run.get("model") == model, "run schema/model mismatch")
    require(run.get("dataset_sha256") == dataset_hash, "dataset identity mismatch")
    require(run.get("predictions_sha256") == prediction_hash, "prediction identity mismatch")
    require(run.get("execution") == "real_weights", "mock/digest-only inference is not model evidence")
    require(run.get("repository") == MODEL_REPOS[model], "model repository mismatch")
    rev, source = run.get("revision"), run.get("source_commit")
    require(isinstance(rev, str) and REVISION.fullmatch(rev) is not None, "exact checkpoint revision required")
    require(isinstance(source, str) and REVISION.fullmatch(source) is not None, "exact source commit required")
    require(source == source_commit, "mixed or unregistered source commits")
    calibration = run.get("calibration")
    require(isinstance(calibration, dict), "missing calibration receipt")
    temperature = calibration.get("temperature")
    threshold = calibration.get("abstention_threshold")
    require(type(temperature) in (float, int) and math.isfinite(temperature) and temperature > 0,
            "invalid calibration temperature")
    require(type(threshold) in (float, int) and math.isfinite(threshold)
            and threshold == frozen_threshold, "unregistered abstention threshold")
    digests = run.get("digests")
    require(isinstance(digests, dict), "artifact digests missing")
    for name in REQUIRED_DIGESTS:
        value = digests.get(name)
        require(isinstance(value, str) and SHA256.fullmatch(value) is not None, f"missing/invalid {name} digest")
    require(run.get("role") == "model_runner", "run role mismatch")
    if model in EMBEDDING_MODELS:
        profile = run.get("profile")
        require(isinstance(profile, dict), "missing encoder training profile")
        require(all(k in profile for k in HEAD_BUDGET_FIELDS), "incomplete equal-budget head training")
        require(profile["head_trainable_parameters"] == 256, "unapproved head parameter budget")
        d = profile.get("projection_sha256")
        require(isinstance(d, str) and SHA256.fullmatch(d) is not None, "missing feature projection digest")


def validate_predictions(
    rows: list[dict[str, Any]], dataset: dict[str, dict[str, Any]], model: str,
    frozen_threshold: float,
) -> dict[str, dict[str, Any]]:
    predicted: dict[str, dict[str, Any]] = {}
    holdout = {rid: item for rid, item in dataset.items() if item["split"] == "future_test"}
    for prediction in rows:
        rid = prediction.get("id")
        require(isinstance(rid, str) and rid in holdout and rid not in predicted, "extra/duplicate or nonholdout prediction")
        require(prediction.get("model") == model, f"{rid}: wrong model")
        probs = prediction.get("probabilities")
        require(isinstance(probs, dict) and set(probs) == set(holdout[rid]["options"]), f"{rid}: option drift")
        values = list(probs.values())
        require(all(type(v) in (float, int) and math.isfinite(v) and 0 <= v <= 1 for v in values), f"{rid}: invalid probability")
        require(abs(sum(values) - 1.0) <= 1e-5, f"{rid}: mass does not sum to 1")
        require(type(prediction.get("abstained")) is bool, f"{rid}: missing abstention")
        require(prediction["abstained"] == (max(values) < frozen_threshold),
                f"{rid}: abstention flag inconsistent with frozen threshold")
        predicted[rid] = prediction
    require(set(predicted) == set(holdout), "predictions must cover exact holdout once")
    return predicted


def metrics(dataset: dict[str, dict[str, Any]], predicted: dict[str, dict[str, Any]], bins: int = 15) -> dict[str, Any]:
    ids = sorted(predicted)
    in_domain = [x for x in ids if not dataset[x]["ood"]]
    ood = [x for x in ids if dataset[x]["ood"]]
    require(bool(in_domain) and bool(ood), "in-domain and OOD holdouts required")
    groups: list[list[tuple[float, float]]] = [[] for _ in range(bins)]
    correct = accepted_correct = answered = 0
    brier = 0.0
    class_counts: dict[str, dict[str, int]] = defaultdict(lambda: {"tp": 0, "fp": 0, "fn": 0})
    true_labels: set[str] = set()
    for rid in in_domain:
        row, pred = dataset[rid], predicted[rid]
        probs = pred["probabilities"]
        guess = max(row["options"], key=lambda x: probs[x])
        ok = guess == row["gold"]
        true_labels.add(row["gold"])
        if ok:
            class_counts[guess]["tp"] += 1
        else:
            class_counts[guess]["fp"] += 1
            class_counts[row["gold"]]["fn"] += 1
        correct += int(ok)
        accepted_correct += int(ok and not pred["abstained"])
        answered += int(not pred["abstained"])
        brier += sum((probs[x] - float(x == row["gold"])) ** 2 for x in row["options"]) / len(row["options"])
        confidence = probs[guess]
        groups[min(bins - 1, int(confidence * bins))].append((confidence, float(ok)))
    ece = sum(len(b) * abs(sum(x for x, _ in b) / len(b) - sum(y for _, y in b) / len(b)) for b in groups if b) / len(in_domain)
    # Unlike overall accuracy, balanced accuracy exposes failures on rare
    # ground-truth classes. Do not let abstentions re-label the true class.
    recall_by_class = {
        label: class_counts[label]["tp"] /
        (class_counts[label]["tp"] + class_counts[label]["fn"])
        for label in sorted(true_labels)
    }
    macro_f1_by_class = {
        label: 2 * stat["tp"] / (2 * stat["tp"] + stat["fp"] + stat["fn"])
        if 2 * stat["tp"] + stat["fp"] + stat["fn"] else 0.0
        for label, stat in sorted(class_counts.items())
    }
    return {
        "n_in_domain": len(in_domain), "n_ood": len(ood),
        "coverage": answered / len(in_domain), "accuracy": correct / len(in_domain),
        "effective_correct_rate": accepted_correct / len(in_domain),
        "selective_accuracy": accepted_correct / answered if answered else None,
        "brier": brier / len(in_domain), "ece": ece,
        "balanced_accuracy": sum(recall_by_class.values()) / len(recall_by_class),
        "per_class_recall": recall_by_class,
        "macro_f1": sum(macro_f1_by_class.values()) / len(macro_f1_by_class),
        "ood_false_acceptance": sum(not predicted[x]["abstained"] for x in ood) / len(ood),
    }


def slice_accuracy(dataset: dict[str, dict[str, Any]], predicted: dict[str, dict[str, Any]], by: str, minimum: int) -> dict[str, float]:
    samples: dict[str, list[str]] = defaultdict(list)
    for rid in predicted:
        if not dataset[rid]["ood"]:
            samples[dataset[rid][by]].append(rid)
    require(all(len(v) >= minimum for v in samples.values()), f"{by}: insufficient holdout samples")
    return {
        name: sum(
            not predicted[rid]["abstained"]
            and max(dataset[rid]["options"], key=lambda x: predicted[rid]["probabilities"][x]) == dataset[rid]["gold"]
            for rid in members
        ) / len(members)
        for name, members in sorted(samples.items())
    }


def paired_cluster_accuracy_ci(
    dataset: dict[str, dict[str, Any]],
    baseline: dict[str, dict[str, Any]],
    candidate: dict[str, dict[str, Any]],
    *, repetitions: int = 2000,
) -> dict[str, Any]:
    """Deterministic paired *cluster*-bootstrap diagnostic, not a promotion CI."""
    groups: dict[str, list[str]] = defaultdict(list)
    for rid in sorted(baseline):
        if not dataset[rid]["ood"]:
            groups[dataset[rid]["cluster"]].append(rid)
    require(len(groups) >= 2, "paired bootstrap requires >=2 independent holdout clusters")

    def correct(rid: str, rows: dict[str, dict[str, Any]]) -> int:
        opts = dataset[rid]["options"]
        return int(max(opts, key=lambda label: rows[rid]["probabilities"][label]) == dataset[rid]["gold"])

    stats = [
        (
            sum(correct(rid, baseline) for rid in group),
            sum(correct(rid, candidate) for rid in group),
            len(group),
        )
        for _, group in sorted(groups.items())
    ]
    rng = random.Random(1729)
    samples = []
    for _ in range(repetitions):
        draw = [stats[rng.randrange(len(stats))] for _ in stats]
        total = sum(size for _, _, size in draw)
        samples.append(sum(c - b for b, c, _ in draw) / total)
    samples.sort()
    return {
        "lower": samples[int(0.025 * repetitions)],
        "upper": samples[min(repetitions - 1, int(0.975 * repetitions))],
        "independent_clusters": len(stats),
        "resamples": repetitions,
        "posture": "diagnostic_only_not_a_preregistered_statistical_acceptance",
    }


def analyse(plan: dict[str, Any], dataset_path: Path, run_dir: Path) -> dict[str, Any]:
    require(plan.get("schema") == SCHEMA, "unknown plan schema")
    require(plan.get("kind") == "frozen_experiment_plan", "unfrozen/template experiment plan")
    source_commit = plan.get("source_commit")
    require(isinstance(source_commit, str) and REVISION.fullmatch(source_commit) is not None,
            "unregistered exact source commit")
    parse_time(plan.get("registered_before_utc"))
    frozen_threshold = plan.get("abstention_threshold")
    require(type(frozen_threshold) in (float, int) and math.isfinite(frozen_threshold)
            and 0 < frozen_threshold < 1, "missing/invalid frozen abstention threshold")
    require(plan.get("candidates") == list(CANDIDATES), "candidate list/order not frozen")
    require(plan.get("baseline") == CANDIDATES[0], "baseline drift")
    roles = plan.get("independent_roles")
    keys = ("dataset_owner", "evaluator", "selector", "executor")
    require(isinstance(roles, dict) and all(roles.get(k) for k in keys), "independent roles not bound")
    require(len({roles[k] for k in keys}) == 4, "evaluator/selector/executor roles collide")
    limits = plan.get("thresholds")
    require(isinstance(limits, dict), "missing thresholds")
    for key in ("max_ece", "max_brier", "max_ood_false_acceptance", "max_slice_regression", "min_accuracy_gain"):
        require(type(limits.get(key)) in (float, int) and 0 <= limits[key] <= 1, f"invalid threshold {key}")
    minimum = plan.get("minimum_slice_size")
    require(type(minimum) is int and minimum >= 1, "minimum_slice_size invalid")
    dataset_hash = file_hash(dataset_path)
    require(plan.get("dataset_sha256") == dataset_hash, "preregistered dataset hash mismatch")
    dataset = validate_dataset(load_jsonl(dataset_path))
    results: dict[str, Any] = {}
    predictions_by_model: dict[str, dict[str, dict[str, Any]]] = {}
    for model in CANDIDATES:
        predictions_path = run_dir / model / "predictions.jsonl"
        run_path = run_dir / model / "run.json"
        require(predictions_path.is_file() and run_path.is_file(), f"missing measured run for {model}")
        validate_run(load_json(run_path), model, dataset_hash, file_hash(predictions_path),
                     source_commit, frozen_threshold)
        predicted = validate_predictions(load_jsonl(predictions_path), dataset, model,
                                         frozen_threshold)
        predictions_by_model[model] = predicted
        results[model] = {
            "all": metrics(dataset, predicted),
            "languages": slice_accuracy(dataset, predicted, "language", minimum),
            "tasks": slice_accuracy(dataset, predicted, "slice", minimum),
        }
    head_a = load_json(run_dir / EMBEDDING_MODELS[0] / "run.json")["profile"]
    head_b = load_json(run_dir / EMBEDDING_MODELS[1] / "run.json")["profile"]
    require(all(head_a[x] == head_b[x] for x in HEAD_BUDGET_FIELDS), "encoder heads did not use equal training budgets")
    baseline = results[CANDIDATES[0]]
    for model in CANDIDATES:
        result = results[model]
        result["accuracy_gain"] = result["all"]["accuracy"] - baseline["all"]["accuracy"]
        result["paired_cluster_accuracy_gain_95ci"] = paired_cluster_accuracy_ci(
            dataset, predictions_by_model[CANDIDATES[0]], predictions_by_model[model],
        )
        result["maximum_slice_regression"] = max(
            (baseline[k][name] - result[k][name] for k in ("languages", "tasks") for name in baseline[k]),
            default=0.0,
        )
        result["metric_gate"] = (
            result["all"]["ece"] <= limits["max_ece"]
            and result["all"]["brier"] <= limits["max_brier"]
            and result["all"]["ood_false_acceptance"] <= limits["max_ood_false_acceptance"]
            and result["maximum_slice_regression"] <= limits["max_slice_regression"]
            and (model == CANDIDATES[0] or result["accuracy_gain"] >= limits["min_accuracy_gain"])
        )
    return {
        "schema": SCHEMA, "plan_sha256": None, "dataset_sha256": dataset_hash,
        "results": results, "independent_acceptance": False,
        "real_host_resources_qualified": False, "lifecycle_qualified": False,
        "all_blockers_closed": False,
        "claim_ceiling": "offline_metrics_only_not_independent_acceptance_or_deployment",
    }


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    for key in ("plan", "dataset", "runs", "output"):
        p.add_argument("--" + key, type=Path, required=True)
    a = p.parse_args()
    try:
        report = analyse(load_json(a.plan), a.dataset, a.runs)
        report["plan_sha256"] = file_hash(a.plan)
        a.output.parent.mkdir(parents=True, exist_ok=True)
        a.output.write_text(json.dumps(report, sort_keys=True, indent=2) + "\n", encoding="utf-8")
        print(f"Input metrics recorded at {a.output}; no model authority granted")
        return 0
    except (EvidenceError, OSError, ValueError) as exc:
        print(f"BLOCKED: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
