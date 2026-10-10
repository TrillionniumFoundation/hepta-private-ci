"""Shadow-only analysis of stem/cell experiments. No production write path.

Input rows are independently obtained evaluation receipts, not model-generated
success labels. Grouped bootstrap uses episode/source clusters, not individual
Cell calls as independent observations.
"""

import argparse
import hashlib
import json
import math
import random
import statistics
from collections import defaultdict
from pathlib import Path

SPLITS = frozenset({"train", "calibration", "held_out", "future_1", "future_2", "ood"})
LANGUAGES = frozenset({"zh", "en", "cross"})
SCORE_SPLITS = frozenset({"held_out", "future_1", "future_2", "ood"})
EVAL_BINS = 15


def load_jsonl(path):
    with Path(path).open(encoding="utf-8") as handle:
        for line_no, line in enumerate(handle, 1):
            if not line.strip():
                continue
            try:
                yield json.loads(line)
            except (ValueError, TypeError) as exc:
                raise ValueError(f"{path}:{line_no}: invalid JSON") from exc


def require_digest(value, name):
    if not isinstance(value, str) or len(value) != 64:
        raise ValueError(f"{name}: required sha256 hex")
    if any(char not in "0123456789abcdef" for char in value):
        raise ValueError(f"{name}: required sha256 hex")


def validate_dataset(rows):
    """Reject source/episode leakage across train, calibration, evaluation, time."""
    by_id, by_group, by_episode = {}, {}, {}
    for row in rows:
        sid = row["sample_id"]
        split = row["split"]
        group = row["source_group"]
        episode = row["episode_id"]
        if split not in SPLITS or row["language"] not in LANGUAGES:
            raise ValueError("unregistered split or language")
        if not all(isinstance(x, str) and x for x in (sid, group, episode)):
            raise ValueError("empty sample/group/episode identifier")
        if sid in by_id:
            raise ValueError(f"duplicate sample_id {sid}")
        if group in by_group and by_group[group] != split:
            raise ValueError(f"source-group leakage {group}")
        if episode in by_episode and by_episode[episode] != split:
            raise ValueError(f"episode leakage {episode}")
        if "label" in row and (not isinstance(row["label"], int) or isinstance(row["label"], bool)):
            raise ValueError("invalid label")
        by_id[sid] = row
        by_group[group] = split
        by_episode[episode] = split
    if not by_id:
        raise ValueError("empty dataset")
    return by_id


def validate_predictions(rows, dataset):
    by_arm = defaultdict(dict)
    for row in rows:
        arm = row["arm"]
        sid = row["sample_id"]
        if not isinstance(arm, str) or not arm or sid not in dataset:
            raise ValueError("unknown arm or sample_id")
        original = dataset[sid]
        if original["split"] not in SCORE_SPLITS:
            raise ValueError("scored train/calibration row is disallowed")
        if sid in by_arm[arm]:
            raise ValueError(f"duplicate prediction: {arm}/{sid}")
        if row["label"] != original.get("label"):
            raise ValueError("mismatching label and frozen dataset")
        probs = row["probabilities"]
        if (not isinstance(probs, list) or len(probs) < 2 or
                not all(isinstance(p, (int, float)) and not isinstance(p, bool)
                        and math.isfinite(p) and 0 <= p <= 1 for p in probs) or
                abs(sum(probs) - 1.0) > 1e-5):
            raise ValueError("invalid probability distribution")
        if not 0 <= row["label"] < len(probs):
            raise ValueError("label outside candidate set")
        if not 0 < row.get("ood_threshold", 0) <= 1:
            raise ValueError("missing frozen calibration threshold")
        if "external_ndu_utility" in row or "observer_digest" in row or "total_cost" in row:
            raise ValueError("model-generated outputs cannot contain independent outcomes")
        for key in ("model_digest", "dataset_digest", "runtime_digest"):
            require_digest(row[key], key)
        if row.get("latency_path") not in {"cold_encoder", "cache_hit_head"}:
            raise ValueError("cold and cached latencies must remain separated")
        if not isinstance(row.get("latency_ms"), (int, float)) or row["latency_ms"] < 0 or not math.isfinite(row["latency_ms"]):
            raise ValueError("invalid latency")
        by_arm[arm][sid] = row
    if not by_arm:
        raise ValueError("missing predictions")
    ids = [set(values) for values in by_arm.values()]
    if any(x != ids[0] for x in ids[1:]):
        raise ValueError("candidate/baseline sample coverage mismatch")
    return by_arm


def validate_outcomes(receipts, predictions):
    """Join independent receipts, refusing unpaired, missing or duplicate outcomes.

    Receipt authentication is performed by the canonical evaluator/owner upstream;
    a digest in JSON alone is NOT a signature or evidence of independence.
    """
    joined = {arm: {} for arm in predictions}
    for receipt in receipts:
        arm, sid = receipt["arm"], receipt["sample_id"]
        if arm not in predictions or sid not in predictions[arm] or sid in joined[arm]:
            raise ValueError("unexpected, duplicate or unpaired outcome receipt")
        for key in ("observer_digest", "snapshot_digest"):
            require_digest(receipt[key], key)
        if receipt["observer_digest"] == predictions[arm][sid]["model_digest"]:
            raise ValueError("model cannot be own outcome observer")
        for key in ("external_ndu_utility", "total_cost"):
            value = receipt.get(key)
            if not isinstance(value, (int, float)) or isinstance(value, bool) or not math.isfinite(value):
                raise ValueError(f"missing finite {key} from independent receipt")
        if receipt["total_cost"] < 0:
            raise ValueError("negative measured total cost")
        joined[arm][sid] = dict(predictions[arm][sid], **{
            key: receipt[key] for key in ("observer_digest", "snapshot_digest",
                                         "external_ndu_utility", "total_cost")})
    if any(set(joined[a]) != set(predictions[a]) for a in predictions):
        raise ValueError("missing independent outcome receipt")
    return joined


def quantile(data, fraction):
    if not data:
        return None
    ordered = sorted(data)
    rank = (len(ordered) - 1) * fraction
    low = int(rank)
    high = min(low + 1, len(ordered) - 1)
    return ordered[low] * (high - rank) + ordered[high] * (rank - low) if high != low else ordered[low]


def classifier_metrics(rows):
    if not rows:
        return {"count": 0}
    n = len(rows)
    brier = sum(sum((prob - int(i == row["label"])) ** 2 for i, prob in enumerate(row["probabilities"])) for row in rows) / n
    accuracy = sum(int(max(range(len(row["probabilities"])), key=row["probabilities"].__getitem__) == row["label"]) for row in rows) / n
    bins = [[] for _ in range(EVAL_BINS)]
    for row in rows:
        p = row["probabilities"]
        conf = max(p)
        correct = int(p.index(conf) == row["label"])
        bins[min(EVAL_BINS - 1, int(conf * EVAL_BINS))].append((conf, correct))
    ece = sum(len(b) / n * abs(statistics.fmean(x[0] for x in b) - statistics.fmean(x[1] for x in b)) for b in bins if b)
    ood = [x for x in rows if x["split"] == "ood"]
    rate = (sum(max(x["probabilities"]) >= x["ood_threshold"] for x in ood) / len(ood)) if ood else None
    return {"count": n, "accuracy": accuracy, "multiclass_brier": brier, "ece_15": ece,
            "ood_false_acceptance": rate, "ood_count": len(ood),
            "external_ndu_utility": statistics.fmean(x["external_ndu_utility"] for x in rows),
            "total_cost": sum(x["total_cost"] for x in rows)}


def summaries(dataset, predictions):
    result = {}
    for arm, observed in predictions.items():
        rows = [{**dataset[sid], **prediction} for sid, prediction in observed.items()]
        partitions = {}
        for language in LANGUAGES:
            partitions[language] = classifier_metrics([r for r in rows if r["language"] == language])
        for split in SCORE_SPLITS:
            partitions[split] = classifier_metrics([r for r in rows if r["split"] == split])
        lat = {}
        for kind in ("cold_encoder", "cache_hit_head"):
            times = [r["latency_ms"] for r in rows if r["latency_path"] == kind]
            lat[kind] = {"count": len(times), "p50_ms": quantile(times, 0.50),
                         "p95_ms": quantile(times, 0.95), "p99_ms": quantile(times, 0.99)}
        result[arm] = {"overall": classifier_metrics(rows), "partitions": partitions, "latency": lat}
    return result


def paired_group_deltas(dataset, predictions, baseline, candidate, partition=None):
    """Each source group contributes once, independent of the number of cell calls."""
    if baseline not in predictions or candidate not in predictions:
        raise ValueError("missing no-change baseline or candidate")
    by_group = defaultdict(lambda: [[], []])
    for sid in predictions[baseline]:
        record = dataset[sid]
        if partition and record["split"] != partition:
            continue
        if record["split"] == "ood":
            continue
        by_group[record["source_group"]][0].append(predictions[baseline][sid]["external_ndu_utility"])
        by_group[record["source_group"]][1].append(predictions[candidate][sid]["external_ndu_utility"])
    return [statistics.fmean(c) - statistics.fmean(b) for b, c in by_group.values()]


def bootstrap_lcb(values, alpha, iterations, seed):
    if not values:
        return None
    rng = random.Random(seed)
    means = []
    n = len(values)
    for _ in range(iterations):
        means.append(sum(values[rng.randrange(n)] for _ in range(n)) / n)
    return quantile(means, alpha)


def admission(protocol, dataset, predictions, *, backend_evidence=None):
    """Propose shadow-only eligibility; NEVER make a production admission decision."""
    cfg = protocol["frozen_admission"]
    baseline = cfg["no_change_arm"]
    candidates = sorted(set(predictions) - {baseline})
    if not candidates or baseline not in predictions:
        raise ValueError("no-change baseline and candidates required")
    result = {}
    for candidate in candidates:
        deltas = paired_group_deltas(dataset, predictions, baseline, candidate)
        alpha = (1 - cfg["confidence_level"]) / max(1, len(candidates))
        lcb = bootstrap_lcb(deltas, alpha, cfg["bootstrap_replicates"], seed=7347)
        rows = [dict(dataset[sid], **r) for sid, r in predictions[candidate].items()]
        base_rows = list(predictions[baseline].values())
        cost_c = sum(r["total_cost"] for r in predictions[candidate].values())
        cost_b = sum(r["total_cost"] for r in base_rows)
        ratio = cost_c / cost_b if cost_b > 0 else math.inf
        future = sum(bool([r for r in rows if r["split"] == w]) for w in ("future_1", "future_2"))
        snapshots = len({r.get("snapshot_digest") for r in rows if r.get("snapshot_digest")})
        ood = classifier_metrics([r for r in rows if r["split"] == "ood"])["ood_false_acceptance"]
        old = [r for r in rows if r["split"] == "held_out"]
        old_base = [dict(dataset[sid], **r) for sid, r in predictions[baseline].items() if dataset[sid]["split"] == "held_out"]
        old_u = statistics.fmean(r["external_ndu_utility"] for r in old) if old else None
        old_b = statistics.fmean(r["external_ndu_utility"] for r in old_base) if old_base else None
        degradation = max(0.0, (old_b - old_u) / max(abs(old_b), 1e-9)) if old_u is not None and old_b is not None else None
        rejection = []
        if len(deltas) < cfg["independent_episode_groups_minimum"]:
            rejection.append("independent_episode_support")
        if lcb is None or lcb <= cfg["minimum_ndu_gain_lcb"]:
            rejection.append("ndu_gain_lcb")
        if future < cfg["future_windows_minimum"]:
            rejection.append("future_windows")
        if snapshots < cfg["independent_snapshots_minimum"]:
            rejection.append("independent_snapshots")
        if ood is None or ood > cfg["max_ood_false_acceptance"]:
            rejection.append("ood_false_acceptance")
        if degradation is None or degradation > cfg["max_old_task_degradation"]:
            rejection.append("old_task_retention")
        if ratio > cfg["maximum_cost_ratio"]:
            rejection.append("total_cost")
        if backend_evidence is None or backend_evidence.get("hepta_native_worker") is not True:
            rejection.append("native_worker_evidence_missing")
        if backend_evidence is None or backend_evidence.get("artifact_and_revocation_verified") is not True:
            rejection.append("artifact_or_revocation_evidence_missing")
        # This analyzer cannot authenticate external observer signatures or
        # consume final-use authority; its statistics are NEVER an admission.
        result[candidate] = {"statistical_precheck_passed": not rejection,
                             "shadow_eligible": False, "production_authorized": False,
                             "independent_receipts_authenticated": False,
                             "rejections": rejection + ["independent_receipt_authentication_not_implemented"],
                             "group_count": len(deltas),
                             "ndu_gain_lcb": lcb, "cost_ratio": ratio,
                             "old_task_degradation": degradation, "ood_false_acceptance": ood,
                             "future_windows": future, "independent_snapshots": snapshots}
    return result


def main():
    parser = argparse.ArgumentParser(description="Read-only Hepta Stem Cell independent analysis")
    parser.add_argument("--protocol", default=str(Path(__file__).with_name("protocol.json")))
    parser.add_argument("--dataset", required=True, help="Immutable JSONL of episodes with held-out labels")
    parser.add_argument("--predictions", required=True, help="Frozen model predictions JSONL without any outcome labels")
    parser.add_argument("--outcomes", required=True, help="Separate independent-owner observation receipts JSONL")
    parser.add_argument("--backend-evidence", help="Optional signed native-worker evidence JSON; never authorizes promotion")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    protocol = json.loads(Path(args.protocol).read_text(encoding="utf-8"))
    if protocol.get("stage") != "shadow_only" or any(protocol["authority"].values()):
        raise ValueError("only shadow/no-authority protocol allowed")
    raw = Path(args.dataset).read_bytes()
    dataset_sha256 = hashlib.sha256(raw).hexdigest()
    dataset = validate_dataset(list(load_jsonl(args.dataset)))
    predictions = validate_predictions(list(load_jsonl(args.predictions)), dataset)
    if any(any(p["dataset_digest"] != dataset_sha256 for p in rows.values()) for rows in predictions.values()):
        raise ValueError("model receipt bound to different dataset contents")
    predictions = validate_outcomes(list(load_jsonl(args.outcomes)), predictions)
    backend = json.loads(Path(args.backend_evidence).read_text(encoding="utf-8")) if args.backend_evidence else None
    result = {"schema": "hepta.stem-cell-shadow-analysis.v1", "dataset_sha256": dataset_sha256,
              "predictions_sha256": hashlib.sha256(Path(args.predictions).read_bytes()).hexdigest(),
              "outcomes_sha256": hashlib.sha256(Path(args.outcomes).read_bytes()).hexdigest(),
              "protocol_sha256": hashlib.sha256(Path(args.protocol).read_bytes()).hexdigest(),
              "model_metrics": summaries(dataset, predictions),
              "admission_diagnostic": admission(protocol, dataset, predictions, backend_evidence=backend),
              "production_authorized": False}
    Path(args.output).write_text(json.dumps(result, indent=2, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")
    print(f"shadow analysis saved: {args.output}; production_authorized=false")


if __name__ == "__main__":
    main()
