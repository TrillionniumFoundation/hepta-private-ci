"""Independent, read-only E1-E5 scorer: opens future truth after prediction seal.

Never imports the training implementation. Local digests/self-declared signatures do
not authenticate producers, Reader adequacy, NDU, native worker or FinalUse.
"""
from __future__ import annotations

import argparse
from collections import defaultdict
import hashlib
import json
import math
from pathlib import Path
import random

PHASES = ("calibration", "test", "future1", "future2", "future3", "ood")
STEMS = ("granite97", "mmbert_small", "embeddinggemma2_text")
BUDGETS = (2048, 8192, 16384)
VARIANTS = ("anchored", "from_zero")
READER_KINDS = ("none", "retrieved", "reviewed_sufficient", "premise_removed")
MEDIA_ARMS = {"image": ("ocr_only", "unaligned", "bridge", "gemma_native"),
              "audio": ("transcript_only", "unaligned", "bridge", "gemma_native"),
              "video": ("order_blind", "temporal", "reversed")}


class ReviewError(ValueError):
    pass


def _pairs(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise ReviewError("duplicate JSON key")
        value[key] = item
    return value


def _invalid(value):
    raise ReviewError("nonfinite JSON constant: " + value)


def _parse(raw):
    try:
        value = json.loads(raw, object_pairs_hook=_pairs, parse_constant=_invalid)
        json.dumps(value, sort_keys=True, allow_nan=False)
        return value
    except (TypeError, ValueError, UnicodeError, OverflowError) as exc:
        raise ReviewError("noncanonical/unbounded JSON") from exc


def _sha(raw):
    return hashlib.sha256(raw).hexdigest()


def read(path: Path, expected: str, maximum=64 * 1024 * 1024):
    if not isinstance(expected, str) or len(expected) != 64 or any(c not in "0123456789abcdef" for c in expected):
        raise ReviewError("exact pinned SHA required")
    if path.is_symlink() or not path.is_file() or path.stat().st_size > maximum:
        raise ReviewError("unsafe or oversized evidence source")
    raw = path.read_bytes()
    if len(raw) > maximum or _sha(raw) != expected:
        raise ReviewError("evidence digest drift")
    return _parse(raw)


def distribution(values):
    if (not isinstance(values, list) or len(values) != 2 or
            any(type(x) not in (float, int) or not math.isfinite(x) or not 0 <= x <= 1 for x in values)
            or abs(sum(values) - 1) > 1e-6):
        raise ReviewError("invalid prediction probabilities")
    return [float(x) for x in values]


def stats(pairs):
    if not pairs:
        return {"n": 0, "accuracy": None, "brier": None, "ece_10": None}
    accuracy = sum(int(int(p[1] >= p[0]) == y) for p, y in pairs) / len(pairs)
    brier = sum(sum((v - int(i == y))**2 for i, v in enumerate(p)) / 2 for p, y in pairs) / len(pairs)
    ece = 0.0
    for bin_id in range(10):
        bin_rows = [(p, y) for p, y in pairs if min(9, int(max(p) * 10)) == bin_id]
        if bin_rows:
            conf = sum(max(p) for p, _ in bin_rows) / len(bin_rows)
            corr = sum(int(int(p[1] >= p[0]) == y) for p, y in bin_rows) / len(bin_rows)
            ece += len(bin_rows) / len(pairs) * abs(conf - corr)
    return {"n": len(pairs), "accuracy": accuracy, "brier": brier, "ece_10": ece}


def grouped_lower_bound(challenger, control, groups, seed=7712):
    """Conservative deterministic paired source-group bootstrap; not a signed NDU."""
    members = defaultdict(list)
    for a, b, group in zip(challenger, control, groups):
        members[group].append((a, b))
    if len(members) < 30:
        return {"groups": len(members), "accuracy_delta": None,
                "bonferroni_one_sided_95_lcb": None, "underpowered": True}
    original = (sum(a - b for values in members.values() for a, b in values)
                / sum(len(values) for values in members.values()))
    rng = random.Random(seed)
    keys = sorted(members)
    boot = []
    for _ in range(2048):
        selected = [members[keys[rng.randrange(len(keys))]] for _ in keys]
        total = sum(len(values) for values in selected)
        boot.append(sum(a - b for values in selected for a, b in values) / total)
    boot.sort()
    # Six comparisons (three models x two controls), one-sided FWER bound.
    index = max(0, int(len(boot) * (0.05 / 6)))
    return {"groups": len(members), "accuracy_delta": original,
            "bonferroni_one_sided_95_lcb": boot[index], "underpowered": False}


def load_plan_inputs(plan: Path, plan_hash: str):
    cfg = read(plan, plan_hash)
    if cfg.get("schema") != "hepta.stem-e1-e5.trial.v1":
        raise ReviewError("wrong plan")
    files = cfg.get("files")
    if not isinstance(files, dict) or set(files) != {"cases", "features", "train_labels", "nochange"}:
        raise ReviewError("incomplete plan")
    def get(name):
        ref = files[name]
        rel = Path(ref["path"])
        if rel.is_absolute() or ".." in rel.parts:
            raise ReviewError("unsafe path")
        return read(plan.parent / rel, ref["sha256"])
    cases = get("cases")
    if not isinstance(cases, list) or not cases:
        raise ReviewError("missing cases")
    by_id = {r["case_id"]: r for r in cases}
    if len(by_id) != len(cases):
        raise ReviewError("duplicate case")
    baselines = get("nochange")
    by_baseline = {r["case_id"]: r for r in baselines}
    if len(by_baseline) != len(baselines) or set(by_baseline) != set(by_id):
        raise ReviewError("missing independent baseline")
    return cfg, by_id, by_baseline


def score_reader(rows, truth, cases):
    if rows is None:
        return {"status": "MISSING_READER", "independent_sufficient_evidence_verified": False}
    if not isinstance(rows, list):
        raise ReviewError("Reader observations must be a list")
    unique, scored = set(), defaultdict(list)
    reader_models = set()
    for r in rows:
        case = cases.get(r.get("case_id"))
        if (not case or case["case_id"] not in truth or r.get("scenario") not in READER_KINDS
                or r.get("input_sha256") != case["input_sha256"]):
            raise ReviewError("Reader identity or scenario drift")
        key = (case["case_id"], r["scenario"])
        if key in unique:
            raise ReviewError("duplicate Reader arm")
        unique.add(key)
        reader_models.add((r.get("reader_sha256"), r.get("budget_tokens")))
        scored[r["scenario"]].append((distribution(r["probabilities"]), truth[case["case_id"]]))
    expected = {(case_id, mode) for case_id in truth for mode in READER_KINDS}
    if unique != expected or len(reader_models) != 1:
        raise ReviewError("incomplete Reader four-arm parity / changing Reader budget")
    report = {arm: stats(scored[arm]) for arm in READER_KINDS}
    adequacy = report["reviewed_sufficient"]["accuracy"] >= 0.9
    return {"status": "SCORED_UNAUTHENTICATED", "four_arm_metrics": report,
            "sufficient_evidence_capacity_screen": adequacy,
            "stem_retrieval_gain_attributable_to_reader": False if not adequacy else None,
            "independent_sufficient_evidence_verified": False}


def score_media(rows, truth, cases, video_pairs=None):
    if rows is None:
        return {"image": {"status": "MISSING_REAL_MEDIA"},
                "audio": {"status": "MISSING_REAL_MEDIA"},
                "video": {"status": "MISSING_REAL_MEDIA"}}
    if not isinstance(rows, list):
        raise ReviewError("media predictions must be a list")
    seen, matched = set(), defaultdict(list)
    participating = defaultdict(set)
    for r in rows:
        cid = r.get("case_id")
        case = cases.get(cid)
        medium, arm = r.get("modality"), r.get("arm")
        if (case is None or cid not in truth or case["modality"] != medium
                or medium not in MEDIA_ARMS or arm not in MEDIA_ARMS[medium]
                or r.get("input_sha256") != case["input_sha256"]):
            raise ReviewError("media arm identity drift")
        key = (medium, cid, arm)
        if key in seen:
            raise ReviewError("duplicated media prediction")
        seen.add(key)
        participating[medium].add(cid)
        matched[medium, arm].append((distribution(r["probabilities"]), truth[cid]))
    output = {}
    for medium, arms in MEDIA_ARMS.items():
        ids = participating[medium]
        if not ids:
            output[medium] = {"status": "MISSING_REAL_MEDIA"}
            continue
        if {(medium, cid, arm) for cid in ids for arm in arms} != {s for s in seen if s[0] == medium}:
            raise ReviewError("media arm omission/selective dropout")
        report = {arm: stats(matched[medium, arm]) for arm in arms}
        output[medium] = {"status": "FEATURE_ORIGIN_NOT_INDEPENDENTLY_AUTHENTICATED",
                          "arms": report, "causal_task_benefit_proven": False}
    if output["video"].get("arms"):
        if not isinstance(video_pairs, list) or not video_pairs:
            output["video"]["status"] = "MISSING_ORDER_FLIP_TRUTH"
        else:
            used = set()
            flips = 0
            for pair in video_pairs:
                if not isinstance(pair, dict) or set(pair) != {"forward_id", "reversed_id"}:
                    raise ReviewError("video pair schema")
                a, b = pair["forward_id"], pair["reversed_id"]
                if (a == b or a in used or b in used or a not in participating["video"]
                        or b not in participating["video"] or truth[a] == truth[b]
                        or cases[a]["split"] != cases[b]["split"]):
                    raise ReviewError("invalid/reused video time-reversal pair")
                used.update((a, b))
                flips += 1
            output["video"]["true_label_flip_pairs"] = flips
    return output


def score_resources(resource):
    if resource is None:
        return {"status": "MISSING_NATIVE_TARGET_HOST_PROFILES", "completed_profiles": []}
    if resource.get("schema") != "hepta.native-stem-e5-resource-claims.v1":
        raise ReviewError("unknown native resource evidence")
    profiles = resource.get("profiles")
    if not isinstance(profiles, list) or {p.get("cells") for p in profiles} != {64, 256, 1024, 4096} or len(profiles) != 4:
        raise ReviewError("incomplete 64/256/1024/4096 profiles")
    required = {"cells", "active_cells", "unique_inputs", "physical_encoder_forwards",
                "peak_rss_bytes", "cpu_ns", "gpu_peak_bytes", "power_joules",
                "p95_ns", "p99_ns", "queue_p99_ns", "throughput_per_s",
                "worker_receipt_sha256", "crash_reopen_verified", "revocation_test_verified"}
    for profile in profiles:
        if set(profile) != required or any(profile[k] is None for k in required):
            raise ReviewError("missing physical resources; null is not zero")
        for k in ("active_cells", "unique_inputs", "physical_encoder_forwards", "peak_rss_bytes",
                  "cpu_ns", "gpu_peak_bytes", "power_joules", "p95_ns", "p99_ns", "queue_p99_ns", "throughput_per_s"):
            v = profile[k]
            if type(v) not in (int, float) or not math.isfinite(v) or v < 0:
                raise ReviewError("invalid resource measurement")
        if (not 0 < profile["active_cells"] <= profile["cells"] or not 0 < profile["unique_inputs"]
                or profile["p99_ns"] < profile["p95_ns"]
                or profile["crash_reopen_verified"] is not True or profile["revocation_test_verified"] is not True):
            raise ReviewError("failed physical recovery/measurement contract")
        val = profile["worker_receipt_sha256"]
        if not isinstance(val, str) or len(val) != 64 or any(c not in "0123456789abcdef" for c in val):
            raise ReviewError("unbound Worker receipt")
    return {"status": "COMPLETE_SELF_REPORTED_NOT_OWNER_VERIFIED",
            "completed_profiles": profiles, "production_native_receipts_authenticated": False}


def evaluate(plan: Path, plan_hash: str, predictions: Path, predictions_hash: str,
             targets: Path, targets_hash: str, output: Path, *,
             reader=None, reader_hash=None, media=None, media_hash=None,
             video_pairs=None, video_pairs_hash=None,
             resources=None, resources_hash=None):
    config, cases, nochange = load_plan_inputs(plan, plan_hash)
    predicted = read(predictions, predictions_hash)
    if predicted.get("schema") != "hepta.stem-e1-e5.sealed-predictions.v1" or predicted.get("plan_sha256") != plan_hash:
        raise ReviewError("unsealed or wrong-plan predictions")
    if predicted.get("production_promotion_permitted") is not False or predicted.get("feature_forward_in_this_runner") != 0:
        raise ReviewError("forged promotion or run budget")
    for source, spec in config["files"].items():
        if predicted["source_file_sha256s"].get(source) != spec["sha256"]:
            raise ReviewError("dataset or feature identity changed after prediction")
    rows = read(targets, targets_hash)
    if not isinstance(rows, list) or not rows:
        raise ReviewError("empty independent labels")
    truth = {}
    for r in rows:
        if not isinstance(r, dict) or set(r) != {"case_id", "label", "input_sha256", "outcome_owner_receipt_sha256"}:
            raise ReviewError("outcome schema")
        cid = r["case_id"]
        if (cid in truth or cid not in cases or cases[cid]["split"] == "train"
                or r["input_sha256"] != cases[cid]["input_sha256"]
                or type(r["label"]) is not int or r["label"] not in (0, 1)
                or not isinstance(r["outcome_owner_receipt_sha256"], str)
                or len(r["outcome_owner_receipt_sha256"]) != 64):
            raise ReviewError("future/duplicate/unmatched outcome")
        truth[cid] = r["label"]
    expected_ids = {cid for cid, c in cases.items() if c["split"] != "train"}
    if set(truth) != expected_ids:
        raise ReviewError("incomplete independent outcome coverage")
    observations, coverage = defaultdict(list), set()
    for rec in predicted["results"]:
        cid, arm = rec["case_id"], rec["arm"]
        c = cases.get(cid)
        if (cid not in truth or not c or rec["input_sha256"] != c["input_sha256"]
                or rec["scope"] != c["scope"] or rec["cell_id"] != c["cell_id"]
                or rec["split"] != c["split"] or rec["model_id"] not in STEMS
                or arm not in {f"{rec['model_id']}:{budget}:{v}" for budget in BUDGETS for v in VARIANTS}):
            raise ReviewError("prediction identity drift")
        if (arm, cid) in coverage:
            raise ReviewError("duplicate Head arm/case")
        coverage.add((arm, cid))
        for field in ("nochange_probabilities", "frozen_probabilities", "learned_probabilities", "cosine_probabilities"):
            distribution(rec[field])
        if any(abs(a-b) > 1e-6 for a, b in zip(rec["nochange_probabilities"], nochange[cid]["probabilities"])):
            raise ReviewError("baseline changed after training")
        observations[arm, c["split"], c["language"], c["modality"]].append((rec, c, truth[cid]))
    arms = {f"{model}:{budget}:{variant}" for model in STEMS for budget in BUDGETS for variant in VARIANTS}
    if coverage != {(arm, cid) for arm in arms for cid in expected_ids}:
        raise ReviewError("dropped/partial Head arms")
    summary, screens = [], {}
    for arm in sorted(arms):
        for phase in PHASES:
            records = [item for (keyarm, keyphase, _, _), seq in observations.items()
                       if keyarm == arm and keyphase == phase for item in seq]
            if not records:
                continue
            def sample(field):
                return [(distribution(rec[field]), y) for rec, _, y in records]
            values = {field: stats(sample(field)) for field in ("nochange_probabilities", "frozen_probabilities", "learned_probabilities", "cosine_probabilities")}
            correct = lambda field: [int(int(rec[field][1] >= rec[field][0]) == y) for rec, _, y in records]
            groups = [case["group_id"] for _, case, _ in records]
            paired = {base: grouped_lower_bound(correct("learned_probabilities"), correct(base), groups)
                      for base in ("nochange_probabilities", "frozen_probabilities")}
            summary.append({"arm": arm, "phase": phase, "cases": len(records), "metrics": values, "paired": paired,
                            "by_language": {lang: stats([(rec["learned_probabilities"], y)
                                for rec, c, y in records if c["language"] == lang]) for lang in ("en", "zh", "code")}})
        future = [r for r in summary if r["arm"] == arm and r["phase"] in ("future1", "future2", "future3")]
        screens[arm] = {"positive_in_three_future_windows_both_controls": len(future) == 3 and all(
            all(item["bonferroni_one_sided_95_lcb"] is not None and item["bonferroni_one_sided_95_lcb"] > 0
                for item in row["paired"].values()) for row in future),
            "authentic_external_NDU": False, "origin_authenticated": False}
    reader_rows = read(reader, reader_hash) if reader is not None else None
    media_rows = read(media, media_hash) if media is not None else None
    pair_rows = read(video_pairs, video_pairs_hash) if video_pairs is not None else None
    resource_rows = read(resources, resources_hash) if resources is not None else None
    result = {"schema": "hepta.stem-e1-e5.independent-review.v1", "plan_sha256": plan_hash,
              "predictions_sha256": predictions_hash, "external_truth_sha256": targets_hash,
              "e1_e2": {"head_metrics": summary, "paired_screens": screens},
              "reader": score_reader(reader_rows, truth, cases),
              "e3_e4": score_media(media_rows, truth, cases, pair_rows),
              "e5": score_resources(resource_rows),
              "readout": {"head_optimizer_executed": len(predicted["head_receipts"]) > 0,
                          "real_pretrained_feature_origin_independently_verified": False,
                          "real_multimodal_utility_authenticated": False,
                          "target_native_worker_complete": False,
                          "reader_capacity_independently_verified": False,
                          "NDU_independent_future_utility": False,
                          "e1_e5_production_qualified": False,
                          "missing_claims_must_not_be_filled_by_synthetic_or_historic_receipts": True},
              "authority": "DENY_ALL", "production_promotion_permitted": False}
    raw = (json.dumps(result, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n").encode()
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("xb") as stream:
        stream.write(raw)
        stream.flush()
        import os
        os.fsync(stream.fileno())
    return _sha(raw)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for key in ("plan", "predictions", "targets", "reader", "media", "video-pairs", "resources"):
        parser.add_argument("--" + key, type=Path, required=key in ("plan", "predictions", "targets"))
        parser.add_argument("--" + key + "-sha256", required=key in ("plan", "predictions", "targets"))
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    for key in ("reader", "media", "video_pairs", "resources"):
        if (getattr(args, key) is None) != (getattr(args, key + "_sha256") is None):
            parser.error("optional evidence path and SHA must be supplied together")
    print("independent_review_sha256=" + evaluate(args.plan, args.plan_sha256, args.predictions, args.predictions_sha256,
        args.targets, args.targets_sha256, args.output, reader=args.reader, reader_hash=args.reader_sha256,
        media=args.media, media_hash=args.media_sha256, video_pairs=args.video_pairs,
        video_pairs_hash=args.video_pairs_sha256, resources=args.resources, resources_hash=args.resources_sha256))
