#!/usr/bin/env python3
"""Fail-closed NEU-1 evidence scorer. This is NOT an independent acceptor.

Inputs are read-only attestable observations. This script cannot validate origin
of labels, weights, observed hardware counters, or native Hepta authorizations.
"""
import argparse
import collections
import hashlib
import json
import math
from pathlib import Path
import re
import statistics
import sys

HEX64 = re.compile(r"^[0-9a-f]{64}$")
HEX40 = re.compile(r"^[0-9a-f]{40}$")
REQUIRED_MODELS = ("laya_english", "laya_typed", "laya_multilingual", "arctic", "harrier")


class EvidenceError(ValueError):
    pass


def require(condition, message):
    if not condition:
        raise EvidenceError(message)


def rows(path):
    if not path:
        return []
    with open(path, encoding="utf-8") as stream:
        return [json.loads(line) for line in stream if line.strip()]


def sha256(path):
    digest = hashlib.sha256()
    with open(path, "rb") as stream:
        for part in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(part)
    return digest.hexdigest()


def validate_plan(plan):
    require(plan.get("schema") == "hepta.neuron.model-bakeoff.plan.v1", "wrong plan schema")
    require(HEX40.fullmatch(str(plan.get("source_sha"))), "source SHA missing")
    require(set(REQUIRED_MODELS) == set(plan["models"]), "must name exactly five candidate models")
    require(plan["logical_cell_scales"] == [64, 256, 1024, 4096], "scale coverage not frozen")
    require(1 <= plan["calibration_bins"] <= 50, "invalid ECE bin count")
    require(0.0 < plan["confidence_gate"] < 1.0, "invalid confidence gate")
    params = plan["head_training"]
    for key in ("seed", "dimension", "epochs", "batch_size"):
        require(type(params[key]) is int and params[key] > 0, f"invalid head budget: {key}")
    for name, model in plan["models"].items():
        require(model["kind"] == ("laya" if name.startswith("laya_") else "embedding"), f"wrong family {name}")
        require(isinstance(model["repo"], str) and "/" in model["repo"], f"repo missing: {name}")
    return plan


def validate_dataset(dataset):
    require(dataset, "empty dataset")
    unique = set()
    groups = {}
    content_groups = {}
    splits = collections.Counter()
    for row in dataset:
        for key in ("id", "group_id", "split", "task", "language", "state", "instructions", "criteria", "ood"):
            require(key in row, f"dataset row missing {key}")
        require(isinstance(row["id"], str) and row["id"] and row["id"] not in unique, "duplicate or empty row id")
        unique.add(row["id"])
        require(row["split"] in ("train", "calibration", "test", "ood", "retention"), "unknown split")
        require(isinstance(row["group_id"], str) and bool(row["group_id"]), "missing correlated group")
        prior = groups.setdefault(row["group_id"], row["split"])
        require(prior == row["split"], f"cross-split correlated group: {row['group_id']}")
        signature = json.dumps({"state": row["state"], "instructions": row["instructions"], "criteria": row["criteria"]}, sort_keys=True, ensure_ascii=False)
        prior_content_split = content_groups.setdefault(signature, row["split"])
        require(prior_content_split == row["split"], "duplicate content crosses frozen split")
        require(type(row["ood"]) is bool and (row["split"] == "ood") == row["ood"], "OOD split mismatch")
        require(isinstance(row["state"], dict) and row["state"], "empty state")
        require(isinstance(row["criteria"], dict) and 2 <= len(row["criteria"]) <= 20, "invalid options")
        require(all(isinstance(k, str) and k for k in row["criteria"]), "non-string option")
        require(isinstance(row["instructions"], str) and row["instructions"], "empty instructions")
        if not row["ood"]:
            require(row.get("gold") in row["criteria"], "gold absent from options")
        splits[row["split"]] += 1
    return {"rows": len(dataset), "split_counts": dict(splits), "independent_groups": len(groups)}


def normalized_probabilities(pred, sample):
    p = pred.get("probabilities")
    require(isinstance(p, dict) and set(p) == set(sample["criteria"]), "probability labels mismatch")
    require(all(type(v) in (int, float) and math.isfinite(v) and 0 <= v <= 1 for v in p.values()), "invalid probabilities")
    require(abs(sum(p.values()) - 1.0) <= 1e-4, "probabilities not normalized")
    return p


def fit_temperature(records):
    require(len(records) >= 30, "calibration requires >=30 independent observations")
    grid = [math.exp(math.log(0.5) + i * (math.log(5.0) - math.log(0.5)) / 80) for i in range(81)]
    return min(grid, key=lambda t: sum(-math.log(max(1e-12, scale(p, t)[gold])) for p, gold in records))


def scale(probs, temp):
    # Probability temperature avoids access to private logits, equivalent up to additive constant.
    a = {key: max(value, 1e-15) ** (1 / temp) for key, value in probs.items()}
    s = sum(a.values())
    return {key: value / s for key, value in a.items()}


def classification(records, bins):
    """records: (probs, label). ECE is top-label expected calibration error."""
    if not records:
        return None
    hits = []
    by_class = collections.defaultdict(list)
    briers = []
    by_bin = [list() for _ in range(bins)]
    for p, gold in records:
        guess = max(p, key=p.__getitem__)
        conf = p[guess]
        correct = float(guess == gold)
        hits.append(correct)
        by_class[gold].append(correct)
        briers.append(sum((v - float(k == gold)) ** 2 for k, v in p.items()))
        by_bin[min(bins - 1, int(conf * bins))].append((conf, correct))
    ece = sum(len(items) / len(records) * abs(statistics.mean(x for x, y in items) - statistics.mean(y for x, y in items)) for items in by_bin if items)
    return {"n": len(records), "accuracy": statistics.mean(hits), "macro_recall": statistics.mean(statistics.mean(a) for a in by_class.values()), "class_support": {k: len(v) for k, v in by_class.items()}, "class_recall": {k: statistics.mean(v) for k, v in by_class.items()}, "brier_multiclass": statistics.mean(briers), "ece_top_label": ece}


def evaluate_decisions(plan, dataset, predictions):
    sample_by_id = {d["id"]: d for d in dataset}
    tests = [s for s in dataset if s["split"] in ("calibration", "test", "ood", "retention")]
    require(all(any(s["split"] == stage for s in tests) for stage in plan["required_decision_splits"]), "required dataset split missing")
    grouped = collections.defaultdict(dict)
    for p in predictions:
        model, identity = p.get("model"), p.get("id")
        require(model in plan["models"] and identity in sample_by_id, "unknown model or row")
        require(identity not in grouped[model], "duplicate prediction identity")
        sample = sample_by_id[identity]
        require(sample["split"] != "train", "evaluation predictions contain training rows")
        require(p.get("status") in ("ok", "abstain"), "prediction terminal status missing")
        if p["status"] == "ok":
            normalized_probabilities(p, sample)
        else:
            require(p.get("probabilities") is None, "abstain must not fabricate probabilities")
        grouped[model][identity] = p
    summaries = {}
    for model in REQUIRED_MODELS:
        own = grouped[model]
        require(set(own) == {s["id"] for s in tests}, f"missing predictions for {model}")
        calibration = [(own[s["id"]]["probabilities"], s["gold"]) for s in tests if s["split"] == "calibration" and own[s["id"]]["status"] == "ok"]
        require(len({s["group_id"] for s in tests if s["split"] == "calibration" and own[s["id"]]["status"] == "ok"}) >= 30, f"insufficient calibration groups for {model}")
        temperature = fit_temperature(calibration)
        groups = collections.defaultdict(list)
        raw_groups = collections.defaultdict(list)
        per_split = collections.defaultdict(lambda: {"count": 0, "correct": 0, "abstained": 0})
        per_language = collections.defaultdict(lambda: {"count": 0, "correct": 0})
        ood_total = ood_accepted = 0
        for sample in tests:
            p = own[sample["id"]]
            if sample["ood"]:
                ood_total += 1
                if p["status"] == "ok" and max(scale(p["probabilities"], temperature).values()) >= plan["confidence_gate"]:
                    ood_accepted += 1
            elif sample["split"] in ("test", "retention"):
                key = sample["split"]
                per_split[key]["count"] += 1
                if key == "test":
                    per_language[sample["language"]]["count"] += 1
                if p["status"] == "abstain":
                    per_split[key]["abstained"] += 1
                    continue
                predicted = max(p["probabilities"], key=p["probabilities"].__getitem__)
                if predicted == sample["gold"]:
                    per_split[key]["correct"] += 1
                    if key == "test":
                        per_language[sample["language"]]["correct"] += 1
                groups[key].append((scale(p["probabilities"], temperature), sample["gold"]))
                raw_groups[key].append((p["probabilities"], sample["gold"]))
                if key == "test":
                    groups[f"lang:{sample['language']}"].append((scale(p["probabilities"], temperature), sample["gold"]))
        require(groups["test"] and groups["retention"] and ood_total, "missing successful test/retention or OOD")
        summaries[model] = {
            "temperature_from_calibration_only": round(temperature, 6),
            "test": classification(groups["test"], plan["calibration_bins"]),
            "test_raw": classification(raw_groups["test"], plan["calibration_bins"]),
            "retention": classification(groups["retention"], plan["calibration_bins"]),
            "test_full_set_accuracy": per_split["test"]["correct"] / per_split["test"]["count"],
            "retention_full_set_accuracy": per_split["retention"]["correct"] / per_split["retention"]["count"],
            "test_abstention_rate": per_split["test"]["abstained"] / per_split["test"]["count"],
            "language_full_set_accuracy": {lang: v["correct"] / v["count"] for lang, v in per_language.items()},
            "languages": {k.removeprefix("lang:"): classification(v, plan["calibration_bins"]) for k, v in groups.items() if k.startswith("lang:")},
            "ood_false_acceptance": ood_accepted / ood_total,
            "ood_n": ood_total,
            "abstention_count": sum(p["status"] == "abstain" for p in own.values()),
            "coverage": sum(p["status"] == "ok" for p in own.values()) / len(own),
        }
    # Retention measured against frozen no-change English reference, not a
    # fabricated utility. This is diagnostic until an independent evaluator signs.
    reference = summaries["laya_english"]["retention_full_set_accuracy"]
    for model in REQUIRED_MODELS:
        summaries[model]["retention_accuracy_delta_vs_laya_english"] = summaries[model]["retention_full_set_accuracy"] - reference
    return summaries


def decision_quality_gaps(plan, scores):
    if not scores:
        return ["DECISION_MODEL_PREDICTIONS_MISSING"]
    thresholds = plan["pre_registered_gates"]
    missing = [key for key, v in thresholds.items() if type(v) not in (int, float) or not math.isfinite(v)]
    if missing:
        return ["QUALITY_GATE_UNREGISTERED:" + key for key in missing]
    problems = []
    for name, row in scores.items():
        if row["test"]["ece_top_label"] > thresholds["max_ece"]:
            problems.append(f"CALIBRATION_FAILED:{name}")
        if row["ood_false_acceptance"] > thresholds["max_ood_false_acceptance"]:
            problems.append(f"OOD_FALSE_ACCEPT_FAILED:{name}")
        if any(lang < thresholds["min_language_accuracy"] for lang in row["language_full_set_accuracy"].values()):
            problems.append(f"LANGUAGE_QUALITY_FAILED:{name}")
        if row["retention_accuracy_delta_vs_laya_english"] < -thresholds["max_old_task_accuracy_drop"]:
            problems.append(f"NEGATIVE_TRANSFER_FAILED:{name}")
    return problems


def evidence_gaps(plan, dataset_path, run_manifest, resource_rows, lifecycle_rows, retrieval_rows=()):
    gaps = []
    if not isinstance(plan.get("dataset_sha256"), str) or not HEX64.fullmatch(plan["dataset_sha256"]):
        gaps.append("DATASET_SHA_UNPINNED")
    elif sha256(dataset_path) != plan["dataset_sha256"]:
        gaps.append("DATASET_SHA_MISMATCH")
    if not plan.get("independent_evaluator") or not plan.get("holdout_frozen_at"):
        gaps.append("INDEPENDENT_HOLDOUT_UNPROVED")
    for m, info in plan["models"].items():
        if not isinstance(info.get("revision"), str) or not HEX40.fullmatch(info["revision"]):
            gaps.append(f"MODEL_REVISION_UNPINNED:{m}")
        files = info.get("file_sha256")
        if not isinstance(files, dict) or not files or not all(isinstance(k, str) and HEX64.fullmatch(str(v)) for k, v in files.items()):
            gaps.append(f"MODEL_BYTES_UNPINNED:{m}")
        run = run_manifest.get(m, {})
        if run.get("revision") != info.get("revision") or run.get("file_sha256") != files or run.get("execution_kind") != "real":
            gaps.append(f"REAL_MODEL_EXECUTION_UNPROVED:{m}")
        if m in ("arctic", "harrier") and run.get("head_budget") != plan["head_training"]:
            gaps.append(f"EQUAL_HEAD_BUDGET_UNPROVED:{m}")
    for name in ("arctic", "harrier"):
        r = [row for row in retrieval_rows if row.get("model") == name and row.get("execution_kind") == "real"]
        if not r or not any(row.get("query_sha256") == plan.get("retrieval_query_sha256") and row.get("corpus_sha256") == plan.get("retrieval_corpus_sha256") and row.get("revision") == plan["models"][name]["revision"] and row.get("file_sha256") == plan["models"][name]["file_sha256"] and all(isinstance(row.get(k), (int, float)) and math.isfinite(row[k]) and 0 <= row[k] <= 1 for k in ("recall_at_10", "mrr_at_10", "ndcg_at_10")) for row in r):
            gaps.append(f"RETRIEVAL_EVIDENCE_MISSING:{name}")
    for key in ("retrieval_query_sha256", "retrieval_corpus_sha256"):
        if not isinstance(plan.get(key), str) or not HEX64.fullmatch(plan[key]):
            gaps.append(f"RETRIEVAL_DATASET_UNPINNED:{key}")
    for key, bound in plan["pre_registered_gates"].items():
        if type(bound) not in (int, float) or not math.isfinite(bound):
            gaps.append(f"THRESHOLD_NOT_PREREGISTERED:{key}")
    for model in REQUIRED_MODELS:
        for scale_n in plan["logical_cell_scales"]:
            matched = [r for r in resource_rows if r.get("model") == model and r.get("logical_cells") == scale_n and r.get("execution_kind") == "target_host"]
            metrics = ("active_cells", "cpu_p95_pct", "rss_peak_bytes", "gpu_peak_bytes", "throughput_rps", "p95_ms", "p99_ms", "load_ms")
            if not matched or not any(all(isinstance(r.get(key), (int, float)) and math.isfinite(r[key]) and r[key] >= 0 for key in metrics) and r["active_cells"] <= scale_n and r.get("host_digest") and r.get("observer") for r in matched):
                gaps.append(f"TARGET_HOST_RESOURCE_MISSING:{model}:{scale_n}")
        for case in plan["lifecycle_cases"]:
            matches = [r for r in lifecycle_rows if r.get("model") == model and r.get("case") == case and r.get("result") == "pass" and r.get("execution_kind") == "target_host" and r.get("independent_observer") and r.get("native_receipt_digest") and r.get("generation")]
            if not matches:
                gaps.append(f"NATIVE_LIFECYCLE_RECEIPT_MISSING:{model}:{case}")
    # These are not cryptographic verifications. The native CAS/fence/signature issuer
    # and external evaluator must verify receipts independently before promotion.
    gaps.append("INDEPENDENT_NATIVE_AND_STATISTICAL_ACCEPTANCE_REQUIRED")
    return sorted(set(gaps))


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--plan", required=True)
    ap.add_argument("--dataset", required=True)
    ap.add_argument("--predictions")
    ap.add_argument("--runs")
    ap.add_argument("--resources")
    ap.add_argument("--retrieval")
    ap.add_argument("--lifecycle")
    ap.add_argument("--output", required=True)
    ap.add_argument("--allow-blocked", action="store_true", help="inspection only; never authorizes admission")
    args = ap.parse_args(argv)
    try:
        plan = validate_plan(json.loads(Path(args.plan).read_text(encoding="utf-8")))
        dataset = rows(args.dataset)
        ds_info = validate_dataset(dataset)
        predictions = rows(args.predictions)
        metrics = evaluate_decisions(plan, dataset, predictions) if predictions else {}
        run_manifest = json.loads(Path(args.runs).read_text(encoding="utf-8")) if args.runs else {}
        blockers = evidence_gaps(plan, args.dataset, run_manifest, rows(args.resources), rows(args.lifecycle), rows(args.retrieval))
        blockers.extend(decision_quality_gaps(plan, metrics))
        report = {"schema": "hepta.neuron.model-bakeoff.report.v1", "source_sha": plan["source_sha"], "dataset": ds_info, "dataset_sha256_actual": sha256(args.dataset), "model_scores": metrics, "status": "BLOCKED", "blockers": sorted(set(blockers)), "scope": "source_evidence_only_no_runtime_or_promotion_authority"}
    except (ValueError, KeyError, OSError, TypeError, json.JSONDecodeError) as exc:
        report = {"schema": "hepta.neuron.model-bakeoff.report.v1", "status": "INVALID", "blockers": [f"INPUT_INVALID:{exc}"], "model_scores": {}}
    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    Path(args.output).write_text(json.dumps(report, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps({"status": report["status"], "blockers": len(report["blockers"]), "output": args.output}, sort_keys=True))
    if report["status"] == "INVALID":
        return 2
    return 0 if args.allow_blocked else 3


if __name__ == "__main__":
    sys.exit(main())