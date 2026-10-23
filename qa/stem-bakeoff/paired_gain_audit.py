#!/usr/bin/env python3
"""Independent P39-versus-P42 source-pair audit; never authorizes production.

Inputs are original pinned P39 Head predictions and the P42 independently fitted
train-only, calibration-only cosine control. Test was previously inspected:
this can diagnose apparent Head lift but is NOT a prospective semantic trial.
"""
import argparse
from collections import defaultdict
import hashlib
import json
import math
from pathlib import Path
import re

import numpy as np

ORIGINAL_PRIMARY_BLOB_SHA1 = "049ae2a390bb5fbb3d52deb21065af38fcd78bdc"
ARCHIVE_SHA256 = "2a853d6c975b30d98a8c79348f01bb3f5b26f36793f2986826a5deed3ea4454e"
DATA_SHA256 = "4d7eec98a8546f8af64b0a5f2b4f192b30c6c43cb086f73f67bb0793a4509d63"
BANK_SHA256 = "e620c7ac8264979136cf39d992ddd575ab37c71baa6a729269af41bc42ca290d"
THRESHOLD = 0.70
PRIMARY_IDENTITY = {
    "data_sha256": DATA_SHA256,
    "encoder_sha256": "f23c2a1f6efc56f54a4ab96fe637eeef21da42dab6bf084eb90cbc91e6f1f5ce",
    "head_sha256": "72cf10b3a068c534e126bacacd457c167bd1fa775aca5e838dd00a83405dfaa1",
    "plan_sha256": "3c9266e3dead8690ae4b58dfe28bd7c3bf77a404dbcc02f32cc7c13756780499",
    "preprocess_sha256": "5153e1507d5f2af7f193b9e728ba1b8cd2e9d69fa13ad897943b4d622c09064e",
}
HEX64 = re.compile(r"[0-9a-f]{64}\Z")


class AuditError(ValueError):
    pass


def canon(v):
    return json.dumps(v, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"), allow_nan=False).encode()


def bounded_json(path, limit):
    path = Path(path)
    if (path.is_symlink() or not path.is_file() or path.stat().st_size > limit
            or path.stat().st_size == 0):
        raise AuditError("missing, symlink or oversized input")
    return json.loads(path.read_bytes())


def number(v, low=None, high=None):
    if type(v) not in (int, float):
        raise AuditError("numerical field must be an actual finite JSON number")
    try:
        x = float(v)
    except (OverflowError, ValueError) as e:
        raise AuditError("out-of-range numerical field") from e
    if not math.isfinite(x) or (low is not None and x < low) or (high is not None and x > high):
        raise AuditError("nonfinite or out-of-range numerical field")
    return x


def digest(v):
    return isinstance(v, str) and HEX64.fullmatch(v) is not None


def verified_primary(path):
    path = Path(path)
    if (path.is_symlink() or not path.is_file() or not 0 < path.stat().st_size <= 512_000):
        raise AuditError("original P39 prediction source must be a bounded regular file")
    raw = path.read_bytes()
    if hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest() != ORIGINAL_PRIMARY_BLOB_SHA1:
        raise AuditError("original P39 prediction blob differs from pinned source")
    return json.loads(raw)


def check_plan(plan, report):
    if (plan.get("schema") != "hepta.cheap-cosine-control-plan.v1"
            or plan.get("original_archive_sha256") != ARCHIVE_SHA256
            or plan.get("data_sha256") != DATA_SHA256
            or plan.get("feature_bank_sha256") != BANK_SHA256
            or plan.get("trainable_scalar_parameters") != 2
            or plan.get("threshold") != THRESHOLD
            or plan.get("new_blind_trial") is not False
            or plan.get("authority") != "DENY_ALL"
            or plan.get("production_activation_allowed") is not False):
        raise AuditError("unqualified or mutated external baseline plan")
    if (report.get("schema") != "hepta.cheap-cosine-control-result.v1"
            or report.get("plan_sha256") != hashlib.sha256(canon(plan)).hexdigest()
            or report.get("new_blind_trial") is not False
            or report.get("semantic_quality_qualified") is not False
            or report.get("authority") != "DENY_ALL"
            or report.get("production_activation_allowed") is not False):
        raise AuditError("baseline result claims unearned authority or wrong plan")
    if report.get("cohorts", {}).get("test") != {"rows": 256, "pair_blocks": 64}:
        raise AuditError("wrong fixed 256-row, 64-block historical test")
    t = number(report.get("calibration_temperature"), 0.01, 100)
    if t not in plan.get("temperature_candidates", []):
        raise AuditError("temperature was not chosen from fixed calibration grid")


def verified_pairs(rows, primary):
    if type(rows) is not list or type(primary) is not list or len(rows) != 256 or len(primary) != 256:
        raise AuditError("all 256 original test pairs and Head outcomes required")
    origins = {}
    for p in primary:
        if (type(p) is not dict or not digest(p.get("source_id"))
                or p["source_id"] in origins or p.get("schema") != "hepta.prediction-ledger.v1"
                or p.get("split") != "test" or p.get("arm") != "text_image-gated"
                or p.get("intervention") != "paired" or p.get("confidence_threshold") != THRESHOLD
                or any(p.get("identity", {}).get(k) != v for k,v in PRIMARY_IDENTITY.items())
                or p.get("temperature") != 0.25):
            raise AuditError("original Head identity, duplicates or intervention mismatch")
        origins[p["source_id"]] = p
    blocks = defaultdict(list)
    data = []
    for r in rows:
        if (type(r) is not dict or any(not digest(r.get(k)) for k in
                                       ("row_id", "pair_block_id", "image_sha256", "caption_sha256"))
                or any(type(r.get(k)) is not int for k in
                       ("image_id", "caption_id", "label", "cheap_prediction", "learned_prediction"))
                or r["label"] not in (0, 1) or r["cheap_prediction"] not in (0, 1)
                or r["learned_prediction"] not in (0, 1)
                or type(r.get("cheap_accepted")) is not bool
                or type(r.get("learned_correct")) is not bool):
            raise AuditError("malformed source-bound per-row observation")
        number(r.get("frozen_cosine"), -1.000001, 1.000001)
        cp = number(r.get("cheap_probability_positive"), 0, 1)
        if (r["cheap_prediction"] != int(cp >= .5)
                or r["cheap_accepted"] != (max(cp, 1-cp) >= THRESHOLD)
                or r["learned_correct"] != (r["learned_prediction"] == r["label"])):
            raise AuditError("cheap decisions or Head correctness differ from recorded probabilities")
        p = origins.pop(r["row_id"], None)
        if (p is None or p.get("label") != r["label"] or p.get("pair_block_id") != r["pair_block_id"]
                or p.get("image_group_id") != f'coco2017:{r["image_id"]}'
                or type(p.get("prediction")) is not int
                or p["prediction"] != r["learned_prediction"]
                or type(p.get("accepted")) is not bool):
            raise AuditError("learned row not backed by the original pinned Head prediction")
        probs = p.get("probabilities")
        if type(probs) is not list or len(probs) != 2:
            raise AuditError("malformed original calibrated Head probabilities")
        q = [number(v, 0, 1) for v in probs]
        if (abs(sum(q)-1) > 1e-5 or p["prediction"] != int(q[1] >= q[0])
                or p["accepted"] != (max(q) >= THRESHOLD)):
            raise AuditError("original calibrated Head class/coverage mismatch")
        observed = {"label":r["label"], "cheap_prediction":r["cheap_prediction"],
                    "cheap_accepted":r["cheap_accepted"], "cheap_probability":cp,
                    "head_prediction":p["prediction"], "head_accepted":p["accepted"],
                    "block":r["pair_block_id"]}
        blocks[r["pair_block_id"]].append(r)
        data.append(observed)
    if origins or len(blocks) != 64:
        raise AuditError("missing original rows or non-independent pair blocks")
    all_photos, all_captions, all_image_bytes, all_text_bytes = set(), set(), set(), set()
    for group in blocks.values():
        img, cap = {r["image_id"] for r in group}, {r["caption_id"] for r in group}
        if (len(group) != 4 or len(img) != 2 or len(cap) != 2
                or len({(r["image_id"],r["image_sha256"]) for r in group}) != 2
                or len({r["image_sha256"] for r in group}) != 2
                or len({(r["caption_id"],r["caption_sha256"]) for r in group}) != 2
                or len({r["caption_sha256"] for r in group}) != 2
                or len({(r["image_id"], r["caption_id"]) for r in group}) != 4
                or sum(r["label"] for r in group) != 2
                or any(sum(x["label"] for x in group if x["image_id"] == i) != 1 for i in img)
                or any(sum(x["label"] for x in group if x["caption_id"] == i) != 1 for i in cap)
                or img & all_photos or cap & all_captions
                or {r["image_sha256"] for r in group} & all_image_bytes
                or {r["caption_sha256"] for r in group} & all_text_bytes):
            raise AuditError("duplicate, overlapping or malformed source pairing")
        all_photos.update(img);all_captions.update(cap)
        all_image_bytes.update(r["image_sha256"] for r in group)
        all_text_bytes.update(r["caption_sha256"] for r in group)
    return data


def metrics(y, pred, accepted):
    y, pred, accepted = np.asarray(y), np.asarray(pred), np.asarray(accepted, dtype=bool)
    correct = pred == y
    tp, tn = np.sum((pred == 1) & (y == 1)), np.sum((pred == 0) & (y == 0))
    pos, neg = np.sum(y == 1), np.sum(y == 0)
    n = len(y)
    count = int(accepted.sum()); errors = int(np.sum(accepted & ~correct))
    return {"rows":n, "correct":int(correct.sum()), "accuracy":float(correct.mean()),
            "balanced_accuracy":float((tp / pos + tn / neg) / 2),
            "positive_recall":float(tp / pos), "negative_recall":float(tn / neg),
            "accepted":count, "coverage":count / n, "accepted_errors":errors,
            "selective_risk":errors / count if count else None}


def recompute(report, data):
    y = np.array([r["label"] for r in data])
    cheap = metrics(y, [r["cheap_prediction"] for r in data],
                    [r["cheap_accepted"] for r in data])
    head = metrics(y, [r["head_prediction"] for r in data],
                   [r["head_accepted"] for r in data])
    recorded = report.get("split_metrics", {}).get("test", {})
    for key in ("rows", "accuracy", "balanced_accuracy", "positive_recall",
                "coverage", "accepted", "accepted_errors"):
        if key not in recorded or number(recorded[key]) != cheap[key]:
            raise AuditError(f"independent cosine measure contradicts report: {key}")
    if recorded.get("selective_risk") != cheap["selective_risk"]:
        raise AuditError("cosine selective risk contradicts original report")
    probs = np.array([r["cheap_probability"] for r in data])
    nll_from_probs = None
    # P42's stable-logit NLL cannot be reconstructed exactly from rounded
    # probabilities at 0 or 1. Audit the reported NLL only when identifiable.
    if np.all((probs > 1e-12) & (probs < 1 - 1e-12)):
        nll_from_probs = -float(np.mean(y * np.log(probs) +
                                         (1-y) * np.log1p(-probs)))
        if abs(nll_from_probs - number(recorded.get("nll"))) > 1e-7:
            raise AuditError("reported cosine NLL contradicts reconstructible row probabilities")
    else:
        number(recorded.get("nll"), 0)
    if report.get("original_trained_head_correct") != head["correct"]:
        raise AuditError("reported Head quality differs from original source")
    gains = defaultdict(list)
    for d in data:
        gains[d["block"]].append(int(d["head_prediction"]==d["label"]) -
                                 int(d["cheap_prediction"]==d["label"]))
    values = np.asarray([np.mean(gains[k]) for k in sorted(gains)])
    rng = np.random.default_rng(20261023)
    boot = values[rng.integers(0, len(values), size=(2000, len(values)))].mean(axis=1)
    pair = {"learned_minus_cheap_accuracy":float(values.mean()),
            "lower_one_sided_95":float(np.quantile(boot, .05)),
            "upper_one_sided_95":float(np.quantile(boot, .95)),
            "pair_blocks":len(values)}
    # Sorting affects the bootstrap permutation. Compare only the deterministic
    # point estimate; rerunning a separate independent order is intentional.
    recorded_pair = report.get("paired_learned_head_vs_cheap_cosine", {})
    if (recorded_pair.get("pair_blocks") != 64
            or recorded_pair.get("new_independent_trial") is not False
            or abs(number(recorded_pair.get("learned_minus_cheap_accuracy")) - pair["learned_minus_cheap_accuracy"]) > 1e-12):
        raise AuditError("reported paired accuracy gain contradicts source rows")
    screen = {"declared_before_original_P39_test":False,
              "historical_source_pair_incremental_gain": pair["learned_minus_cheap_accuracy"],
              "independently_resampled_lower_95":pair["lower_one_sided_95"],
              "required_gain":0.02, "required_lower_95_greater_than":0.0,
              "required_head_positive_recall":0.90,
              "required_head_coverage":0.80,
              "maximum_head_selective_risk":0.05}
    meets = (pair["learned_minus_cheap_accuracy"] >= .02
             and pair["lower_one_sided_95"] > 0
             and head["positive_recall"] >= .9
             and head["coverage"] >= .8
             and head["selective_risk"] is not None
             and head["selective_risk"] <= .05)
    return {"schema":"hepta.p43-joint-vs-frozen-cosine-independent-audit.v1",
            "observed":{"cheap_cosine":cheap,"trained_head":head,"paired":pair,
                        "cosine_nll_from_rows_if_identifiable":nll_from_probs},
            "research_screen":{"historical_posthoc_criteria_met":bool(meets),**screen},
            "original_blind_test_previously_inspected":True,
            "new_independent_semantic_holdout":False,
            "pretraining_contamination_excluded":False,
            "target_device_energy_measured":False,
            "complete_policy_state_action_value_trained":False,
            "eligible_for_production":False,
            "authority":"DENY_ALL","mode":"SHADOW_ONLY",
            "admission":"HOLD_NO_GO"}


def run(plan, report, baseline_rows, primary, output):
    output=Path(output)
    if output.exists() or output.parent.is_symlink():
        raise AuditError("audit must create a new output file")
    frozen_plan=bounded_json(plan, 100_000)
    frozen_report=bounded_json(report, 100_000)
    rows=bounded_json(baseline_rows, 512_000)
    head=verified_primary(primary)
    check_plan(frozen_plan, frozen_report)
    observations=verified_pairs(rows, head)
    audited=recompute(frozen_report, observations)
    audited["source"]={"historical_archive_sha256":ARCHIVE_SHA256,
                       "frozen_bank_manifest_sha256":BANK_SHA256,
                       "original_head_prediction_git_blob":ORIGINAL_PRIMARY_BLOB_SHA1,
                       "cheap_report_sha256":hashlib.sha256(Path(report).read_bytes()).hexdigest(),
                       "cheap_rows_sha256":hashlib.sha256(Path(baseline_rows).read_bytes()).hexdigest()}
    output.write_bytes(canon(audited)+b"\n")
    return audited


if __name__=="__main__":
    ap=argparse.ArgumentParser(description=__doc__)
    for name in ("plan","report","baseline-rows","primary","output"):
        ap.add_argument("--"+name,required=True)
    args=ap.parse_args()
    result=run(args.plan,args.report,args.baseline_rows,args.primary,args.output)
    print(json.dumps({"mode":result["mode"],"admission":result["admission"],
                      "historical_posthoc_screen":result["research_screen"]["historical_posthoc_criteria_met"],
                      "observed":result["observed"]},sort_keys=True))
