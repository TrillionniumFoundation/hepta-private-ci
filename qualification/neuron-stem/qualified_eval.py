#!/usr/bin/env python3
"""Independent, read-only shadow evaluator for Neuron Stem experiments.

No candidate model, trainer, or resource logger is authorized to select or
promote a production artifact. Reported NDU deltas are descriptive only.
"""
import argparse
import hashlib
import json
import math
import statistics
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

SPLITS = {"train", "calibration", "test", "future", "ood"}
LANGUAGES = {"zh", "en", "cross"}
SCALES = {64, 256, 1024, 4096}
MODES = ("joint", "sentence", "landmark", "cross_attention")
HEADS = ("linear", "film", "rank8", "rank16", "mlp", "swiglu")
BUDGETS = (2048, 16384, 65536, 262144)


def canonical(obj):
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def digest(obj):
    return hashlib.sha256(canonical(obj).encode("utf-8")).hexdigest()


def read_jsonl(path):
    result = []
    with Path(path).open(encoding="utf-8") as file:
        for number, line in enumerate(file, 1):
            if line.strip():
                try:
                    value = json.loads(line)
                    if not isinstance(value, dict):
                        raise ValueError("row is not an object")
                    result.append(value)
                except (ValueError, TypeError) as exc:
                    raise ValueError(f"{path}:{number}: {exc}") from exc
    if not result:
        raise ValueError(f"{path}: empty input")
    return result


def write_json(path, data):
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(canonical(data) + "\n", encoding="utf-8")


def audit_dataset(rows):
    ids, group_split, content_split = set(), {}, {}
    counts = Counter()
    timestamps = defaultdict(list)
    task_width = {}
    for row in rows:
        for key in ("case_id", "group_id", "task_id", "scope_id",
                    "split", "language", "state", "question", "options",
                    "label", "event_time"):
            if key not in row:
                raise ValueError(f"missing {key} for case {row.get('case_id')}")
        case_id, group, split = row["case_id"], row["group_id"], row["split"]
        if not all(isinstance(row[k], str) and row[k] for k in
                   ("case_id", "group_id", "task_id", "scope_id", "state", "question", "event_time")):
            raise ValueError(f"empty/invalid identifier or text: {case_id}")
        if case_id in ids:
            raise ValueError(f"duplicate case_id: {case_id}")
        ids.add(case_id)
        if split not in SPLITS or row["language"] not in LANGUAGES:
            raise ValueError(f"invalid split/language: {case_id}")
        opts, label = row["options"], row["label"]
        if not isinstance(opts, list) or len(opts) < 2 or not all(isinstance(v, str) for v in opts):
            raise ValueError(f"invalid options: {case_id}")
        if type(label) is not int or not 0 <= label < len(opts):
            raise ValueError(f"invalid label: {case_id}")
        task = row["task_id"]
        if task in task_width and task_width[task] != len(opts):
            raise ValueError(f"option width changed for task {task}")
        task_width[task] = len(opts)
        key = (row["scope_id"], group)
        if key in group_split and group_split[key] != split:
            raise ValueError(f"group leakage: {group}")
        group_split[key] = split
        fingerprint = digest([row["state"], row["question"], opts])
        if fingerprint in content_split and content_split[fingerprint] != split:
            raise ValueError(f"identical example leaked across splits: {case_id}")
        content_split[fingerprint] = split
        if not isinstance(row["event_time"], str) or "T" not in row["event_time"]:
            raise ValueError(f"event_time must be ISO-8601: {case_id}")
        try:
            timestamp = datetime.fromisoformat(row["event_time"].replace("Z", "+00:00"))
            if timestamp.tzinfo is None:
                raise ValueError("naive timestamp")
            timestamp = timestamp.astimezone(timezone.utc)
        except ValueError as exc:
            raise ValueError(f"invalid UTC-resolvable event_time: {case_id}") from exc
        timestamps[split].append(timestamp)
        counts[(split, row["language"])] += 1
    if any(not timestamps[part] for part in SPLITS):
        raise ValueError("all train, calibration, test, future and ood splits required")
    if max(timestamps["train"] + timestamps["calibration"] + timestamps["test"]) >= min(timestamps["future"]):
        raise ValueError("future window overlaps observed windows")
    return {
        "dataset_digest": digest(rows), "cases": len(rows),
        "split_language_counts": {f"{s}/{l}": n for (s, l), n in sorted(counts.items())},
        "tasks": len(task_width), "source_groups": len(group_split),
    }


def percentile(values, q):
    if not values:
        return None
    values = sorted(values)
    index = (len(values) - 1) * q
    low, high = math.floor(index), math.ceil(index)
    return values[low] + (values[high] - values[low]) * (index - low)


def brier_and_ece(cases, predictions, bins=15):
    """Normalized multiclass Brier (sum of squared class errors / class count)."""
    if not cases:
        return None
    brier = correct = 0
    buckets = [[0, 0.0, 0.0] for _ in range(bins)]
    for case in cases:
        p = predictions[case["case_id"]]["probabilities"]
        label = case["label"]
        brier += sum((value - (index == label)) ** 2 for index, value in enumerate(p)) / len(p)
        best = max(range(len(p)), key=p.__getitem__)
        confidence = p[best]
        hit = float(best == label)
        correct += int(hit)
        bucket = buckets[min(int(confidence * bins), bins - 1)]
        bucket[0] += 1
        bucket[1] += confidence
        bucket[2] += hit
    ece = sum(abs(conf - hits) for count, conf, hits in buckets if count) / len(cases)
    return {"n": len(cases), "accuracy": correct / len(cases),
            "brier": brier / len(cases), "ece_15": ece}


def validate_predictions(rows, dataset):
    relevant = {r["case_id"]: r for r in dataset if r["split"] != "train"}
    observed = {}
    for row in rows:
        ident = row.get("case_id")
        if ident not in relevant or ident in observed:
            raise ValueError(f"missing dataset case or duplicate prediction: {ident}")
        for key in ("model_id", "model_revision", "encoder_digest", "head_digest",
                    "scope_id", "runtime_generation", "status"):
            if not row.get(key) and row.get(key) != 0:
                raise ValueError(f"missing measured identity: {ident}/{key}")
        if row["scope_id"] != relevant[ident]["scope_id"]:
            raise ValueError(f"scope mismatch: {ident}")
        if row["status"] != "Succeeded":
            raise ValueError(f"non-success outcome: {ident}")
        p = row.get("probabilities")
        if not isinstance(p, list) or len(p) != len(relevant[ident]["options"]):
            raise ValueError(f"invalid probability width: {ident}")
        if any(type(v) not in (float, int) or not math.isfinite(v) or not 0 <= v <= 1 for v in p):
            raise ValueError(f"invalid probabilities: {ident}")
        if not math.isclose(sum(p), 1, rel_tol=0, abs_tol=1e-5):
            raise ValueError(f"unnormalized probabilities: {ident}")
        observed[ident] = row
    if set(observed) != set(relevant):
        raise ValueError(f"prediction coverage mismatch: missing={len(set(relevant) - set(observed))}")
    if len({r["model_id"] for r in rows}) != 1 or len({r["model_revision"] for r in rows}) != 1:
        raise ValueError("predictions must describe one exact model revision")
    return observed


def ood_results(dataset, predictions):
    calibration = [max(predictions[r["case_id"]]["probabilities"]) for r in dataset if r["split"] == "calibration"]
    ood = [max(predictions[r["case_id"]]["probabilities"]) for r in dataset if r["split"] == "ood"]
    threshold = percentile(calibration, 0.05)  # target 95% acceptance on calibration ID
    return {"threshold_from_calibration": threshold, "ood_false_accept_rate":
            sum(v >= threshold for v in ood) / len(ood) if ood else None}


def resource_results(rows):
    grouped = defaultdict(list)
    for row in rows:
        stage = row.get("execution_path")
        if stage is None:
            continue
        if stage not in {"cache_hit_head", "encoder_warm", "encoder_cold", "backend_batch"}:
            raise ValueError(f"unrecognized execution_path: {stage}")
        value = row.get("latency_ms")
        if type(value) not in (int, float) or not math.isfinite(value) or value < 0:
            raise ValueError("invalid observed latency")
        grouped[stage].append(row)
    return {
        stage: {
            "n": len(events),
            "p50_ms": percentile([x["latency_ms"] for x in events], .50),
            "p95_ms": percentile([x["latency_ms"] for x in events], .95),
            "p99_ms": percentile([x["latency_ms"] for x in events], .99),
            "peak_reported_rss_bytes": max((x.get("rss_bytes", 0) for x in events), default=0),
            "reported_backend_batch_sizes": sorted({x.get("backend_batch_size", 1) for x in events}),
        }
        for stage, events in sorted(grouped.items())
    }


def evaluate(dataset, baseline, candidate):
    audit = audit_dataset(dataset)
    a = validate_predictions(baseline, dataset)
    b = validate_predictions(candidate, dataset)
    by_split = {}
    for split in ("calibration", "test", "future", "ood"):
        by_split[split] = {}
        for language in sorted(LANGUAGES):
            subset = [r for r in dataset if r["split"] == split and r["language"] == language]
            if subset:
                before = brier_and_ece(subset, a)
                after = brier_and_ece(subset, b)
                by_split[split][language] = {
                    "no_change": before, "candidate": after,
                    "delta_brier": after["brier"] - before["brier"],
                    "delta_ece": after["ece_15"] - before["ece_15"],
                }
    task_results = {}
    regressions = []
    for task in sorted({r["task_id"] for r in dataset}):
        task_results[task] = {}
        for split in ("test", "future"):
            subset = [r for r in dataset if r["task_id"] == task and r["split"] == split]
            if not subset:
                continue
            before, after = brier_and_ece(subset, a), brier_and_ece(subset, b)
            delta = after["brier"] - before["brier"]
            task_results[task][split] = {
                "cases": len(subset), "no_change": before, "candidate": after,
                "delta_brier": delta,
            }
            if delta > 0:
                regressions.append({"task": task, "split": split, "delta_brier": delta})
    ndu = []
    for row in dataset:
        if row["split"] in ("test", "future"):
            x, y = a[row["case_id"]], b[row["case_id"]]
            if all(type(z.get("independent_ndu_utility")) in (int, float)
                   and isinstance(z.get("independent_ndu_receipt_id"), str)
                   and z["independent_ndu_receipt_id"] for z in (x, y)):
                ndu.append(y["independent_ndu_utility"] - x["independent_ndu_utility"])
    return {
        "status": "shadow_only_no_promotion_authority",
        "dataset": audit,
        "baseline_model": baseline[0]["model_id"],
        "baseline_revision": baseline[0]["model_revision"],
        "baseline_predictions_sha256": digest(baseline),
        "candidate_model": candidate[0]["model_id"],
        "candidate_revision": candidate[0]["model_revision"],
        "candidate_predictions_sha256": digest(candidate),
        "metrics": by_split,
        "ood_no_change": ood_results(dataset, a),
        "ood_candidate": ood_results(dataset, b),
        "candidate_resource_paths": resource_results(candidate),
        "baseline_resource_paths": resource_results(baseline),
        "descriptive_ndu_delta": statistics.mean(ndu) if ndu else None,
        "ndu_matched_receipt_count": len(ndu),
        "ndu_independent_signature_verified": False,
        "per_task_results": task_results,
        "negative_transfer_regressions": regressions,
        "future_regression_detected": any(r["split"] == "future" for r in regressions),
        "production_promotion_permitted": False,
    }


def scale_summary(rows):
    groups = defaultdict(list)
    for row in rows:
        scale = row.get("logical_cells")
        if scale not in SCALES:
            raise ValueError(f"invalid scale {scale}")
        if row.get("measurement_origin") != "real_backend":
            raise ValueError("scale evidence requires real_backend, not an estimate")
        for key in ("active_fraction", "input_repeat_fraction", "task_similarity"):
            if key not in row:
                raise ValueError(f"missing {key}")
        if not 0 < row["active_fraction"] <= 1 or not 0 <= row["input_repeat_fraction"] <= 1:
            raise ValueError("invalid scale fractions")
        if not isinstance(row["task_similarity"], str):
            raise ValueError("invalid task similarity")
        groups[(scale, row["active_fraction"], row["input_repeat_fraction"],
                row["task_similarity"])].append(row)
    output = []
    for (scale, active, repeat, similarity), observed in sorted(groups.items()):
        paths = resource_results(observed)
        if not paths:
            raise ValueError("no separately identified measured latency paths")
        output.append({"logical_cells": scale, "active_fraction": active,
                       "input_repeat_fraction": repeat, "task_similarity": similarity,
                       "observed_records": len(observed), "latency_paths": paths,
                       "backend_batch_verified": False, "recovery_verified": False})
    return {"status": "telemetry_descriptive_not_production_qualified",
            "scales": output, "production_promotion_permitted": False}


def matrix(models, shots=(8, 32, 128), active=(.05, .25, 1.),
           repeated=(0., .5, .9), similarities=("low", "medium", "high")):
    """Factorial qualification envelope; planning does not imply execution."""
    entries, scale_arms = [], []
    for model in models:
        for mode in MODES:
            for head in HEADS:
                for budget in BUDGETS:
                    for n in shots:
                        entries.append({"model": model["id"], "mode": mode, "head": head,
                                        "max_head_parameters": budget,
                                        "fewshot_independent_groups": n,
                                        "activation": "shadow"})
        for scale in sorted(SCALES):
            for fraction in active:
                for duplicate_rate in repeated:
                    for similarity in similarities:
                        scale_arms.append({"model": model["id"], "logical_cells": scale,
                                           "active_fraction": fraction,
                                           "input_repeat_fraction": duplicate_rate,
                                           "task_similarity": similarity,
                                           "activation": "shadow"})
    return {"schema": "hepta.neuron-stem-experiment-matrix.v2",
            "arms": entries, "scale_arms": scale_arms,
            "production_promotion_permitted": False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    check = sub.add_parser("audit")
    check.add_argument("--dataset", required=True)
    check.add_argument("--out", required=True)
    score = sub.add_parser("score")
    for opt in ("dataset", "baseline", "candidate", "out"):
        score.add_argument(f"--{opt}", required=True)
    trace = sub.add_parser("scale")
    trace.add_argument("--trace", required=True)
    trace.add_argument("--out", required=True)
    plan = sub.add_parser("matrix")
    plan.add_argument("--models", required=True)
    plan.add_argument("--out", required=True)
    args = parser.parse_args()
    if args.command == "audit":
        result = audit_dataset(read_jsonl(args.dataset))
    elif args.command == "score":
        result = evaluate(read_jsonl(args.dataset), read_jsonl(args.baseline),
                          read_jsonl(args.candidate))
    elif args.command == "scale":
        result = scale_summary(read_jsonl(args.trace))
    else:
        registry = json.loads(Path(args.models).read_text(encoding="utf-8"))
        profile = registry["scaling_factors"]
        result = matrix(registry["models"], shots=registry["few_shot_sizes"],
                        active=profile["active_fraction"],
                        repeated=profile["input_repeat_fraction"],
                        similarities=profile["task_similarity"])
    write_json(args.out, result)
    print(canonical({"status": result.get("status", "audited"),
                     "sha256": digest(result), "out": args.out}))


if __name__ == "__main__":
    main()
