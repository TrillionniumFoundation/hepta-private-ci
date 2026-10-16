#!/usr/bin/env python3
"""Read-only, label-blind V24 ScienceQA multimodal causal-*limits* audit.

Only an immutable historical artifact is accepted. Published aggregate reviewer
counts are crosschecked, not represented as independently re-scored labels.
No classifier, Encoder, modality ablation, or new material is executed here.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import re
import zipfile

ARCHIVE_SHA256 = "7807b82d6c747b0b13666b330145e3801a8c8a0aadeee3f2ff7ab5f5c8c00a30"
PRED_SHA256 = "c91824b378357c60f6272b785233854eaa762efd8fadc421bf99b996a58dd8e4"
SOURCE_SHA256 = "a561916c7d56b6677c5511c329a49bbeec94879f019d29f159ff59be83359202"
EXPECTED_HEAD = "b8b2f10fe38506972301e77e3836729a90200673"
ARMS = frozenset({"text_only", "image_masked", "calibrated_fusion", "bridge_image_only", "bridge_equal_fusion", "rotated_equal_fusion", "train_gate", "unaligned_equal_fusion"})
PAIR_ARMS = ARMS - {"text_only", "image_masked"}
PRIMARY_THRESHOLD = 0.005  # fixed from the source contract, never tuned against TEST results

class Invalid(ValueError):
    pass


def require(ok: bool, message: str) -> None:
    if not ok:
        raise Invalid(message)


def digest(blob: bytes) -> str:
    return hashlib.sha256(blob).hexdigest()


def h64(value: object) -> bool:
    return isinstance(value, str) and bool(re.fullmatch(r"[0-9a-f]{64}", value))


def integer(value: object, minimum: int, maximum: int) -> int:
    require(type(value) is int and minimum <= value <= maximum, "invalid integer/boolean/census")
    return value


def require_unit_vector(v: object) -> tuple[float, ...]:
    require(type(v) is list and len(v) == 4, "original four-class outputs required")
    require(all(type(t) in (float, int) and math.isfinite(t) and 0.0 <= t <= 1.0 for t in v), "invalid probabilities")
    require(abs(sum(v)-1.0) <= 1e-5, "non-normalized probabilities")
    return tuple(float(t) for t in v)


def top(probs: tuple[float, ...]) -> int:
    return max(range(4), key=lambda i: probs[i])


def exact_p(rescues: int, harms: int) -> float:
    n = rescues + harms
    return min(1.0, 2.0 * sum(math.comb(n, j) for j in range(min(rescues, harms)+1)) / 2**n) if n else 1.0


def primary_interval(text_correct: int, rescues: int, harms: int, different: int, triggered_different: int) -> dict:
    """Tight partial-identification bounds from *pairwise aggregate* truth only.

    On changed-prediction cases there are rescues, harms, and both-wrong cases.
    Selected cases are constrained ONLY by source-observable text margins; their
    per-case correctness remains sealed from this artifact. This is not a score.
    """
    require(0 <= rescues+harms <= different, "pairwise correction exceeds changed predictions")
    require(0 <= triggered_different <= different, "trigger mismatch")
    both_wrong = different-rescues-harms
    s = triggered_different
    harm_first = min(harms, s)
    rescue_last = max(0, s-harm_first-both_wrong)
    rescue_first = min(rescues, s)
    harm_last = max(0, s-rescue_first-both_wrong)
    lo = text_correct + rescue_last - harm_first
    hi = text_correct + rescue_first - harm_last
    require(0 <= lo <= hi <= 64, "invalid identification bounds")
    return {"minimum_consistent_correct": lo, "maximum_consistent_correct": hi,
            "interpretation": "tight_pairwise_aggregate_identification_interval_not_measured_accuracy"}


def verify_archive(path: Path) -> tuple[dict, dict, dict]:
    require(path.is_file(), "missing original archive")
    require(digest(path.read_bytes()) == ARCHIVE_SHA256, "original ZIP byte SHA mismatch")
    with zipfile.ZipFile(path) as z:
        names = z.namelist()
        require(len(names) == len(set(names)) == 11, "noncanonical member roster or duplicate filenames")
        require(set(names) == {"SHA256SUMS", "independent-descriptive-review.json", "offline-tests.txt", "optimized-tests.txt", "predictions-before-labels.sha256", "sealed-source-bound-predictions.json", "source-blobs-SHA256", "source-head.txt", "source-seals.json", "source-tree.txt", "versions.txt"}, "archive member mismatch")
        check = z.read("SHA256SUMS").decode("ascii")
        seen = set()
        for line in check.splitlines():
            m = re.fullmatch(r"([0-9a-f]{64})  \./([A-Za-z0-9._-]+)", line)
            require(m is not None and m[2] not in seen and m[2] in names and m[2] != "SHA256SUMS", "invalid SHA256SUMS roster")
            seen.add(m[2]); require(digest(z.read(m[2])) == m[1], "inner original member mismatch")
        require(seen == set(names)-{"SHA256SUMS"}, "incomplete SHA256SUMS")
        require(z.read("source-head.txt").decode("ascii").strip() == EXPECTED_HEAD, "wrong original research commit")
        require(digest(z.read("sealed-source-bound-predictions.json")) == PRED_SHA256, "wrong historical sealed predictions")
        pred = json.loads(z.read("sealed-source-bound-predictions.json"))
        review = json.loads(z.read("independent-descriptive-review.json"))
        seals = json.loads(z.read("source-seals.json"))
    return pred, review, seals


def analyze(pred: dict, review: dict, seals: dict) -> dict:
    require(type(pred) is type(review) is type(seals) is dict, "invalid archive documents")
    require(pred.get("schema") == "hepta.e3-granite-dinov2-scienceqa.v1.sealed-predictions", "wrong original prediction schema")
    require(review.get("schema") == "hepta.e3-granite-dinov2-scienceqa.v1.independent-heldout-review", "wrong original review schema")
    require(pred.get("source_sha256") == review.get("source_sha256") == seals.get("source_sha256") == SOURCE_SHA256, "source lineage mismatch")
    require(review.get("sealed_predictions_sha256") == PRED_SHA256, "review/prediction source not joined")
    require(review.get("holdout_targets_sha256") == seals.get("private_test_labels_sha256") and pred.get("fit_labels_sha256") == seals.get("fit_labels_sha256"), "held label seal mismatch")
    require(pred.get("arms") is not None and set(pred["arms"]) == ARMS and len(pred["arms"]) == len(ARMS), "missing, duplicate or extra arm")
    require(review.get("authority") == "DENY_ALL", "untrusted authority change")
    require(review.get("visual_necessity_ground_truth_adjudicated") is False and review.get("external_ground_truth_independent_owner") is False, "false observer/necessity claim")
    require(review.get("production_accepted") is False and review.get("stem_winner") is None and review.get("statistical_selection_authorized") is False, "false promotion")
    require(pred.get("production_accepted") is False and pred.get("same_source_public_release_not_future") is True and pred.get("held_labels_visible_to_inference") is False, "false source/time/label boundary")
    fit=pred.get("fit"); require(type(fit) is dict and fit.get("calibration_selected_weight") == 0.0 and type(fit.get("calibration_selected_weight")) in (float, int), "calibration was not text-only")
    integer(fit.get("cell_optimizer_updates"), 0, 1_000_000)
    require(type(pred.get("predictions")) is list and len(pred["predictions"]) == 64, "not 64 original heldout cases")
    require(review.get("original_heldout_cases") == 64, "review denominator drift")
    identities=set(); group_ids=set(); probs_by_arm={a:[] for a in ARMS}
    for case in pred["predictions"]:
        require(type(case) is dict and case.get("split") == "test", "changed split")
        key=case.get("id"); require(h64(key) and key not in identities and h64(case.get("group")) and h64(case.get("source_input_sha256")), "case identity/source missing or repeated")
        identities.add(key); group_ids.add(case["group"])
        vectors=case.get("arms");require(type(vectors) is dict and set(vectors) == ARMS, "arm not applied to the original case")
        for a in ARMS:probs_by_arm[a].append(require_unit_vector(vectors[a]))
        require(vectors["text_only"] == vectors["image_masked"] == vectors["calibrated_fusion"], "historic calibration/mask mismatch")
    require(len(group_ids) <= 64 and len(group_ids) > 1, "source group inventory invalid")
    arm_results={}; baseline=[top(t) for t in probs_by_arm["text_only"]]
    base_total = review.get("arms", {}).get("text_only", {}).get("correct")
    integer(base_total,0,64)
    require(review["arms"]["text_only"].get("accuracy") == base_total/64, "base rate incoherent")
    require(set(review.get("arms", {})) == ARMS and set(review.get("paired_vs_text_only", {})) == PAIR_ARMS, "incomplete original review")
    for arm in sorted(ARMS):
        stats = review["arms"][arm]
        require(type(stats) is dict and stats.get("cases") == 64, "invalid reviewer case census")
        c=integer(stats.get("correct"),0,64)
        require(type(stats.get("accuracy")) in (int,float) and stats.get("accuracy") == c/64, "wrong reviewer accuracy")
        arg=[top(p) for p in probs_by_arm[arm]]
        changed=sum(a!=b for a,b in zip(arg,baseline))
        row={"changed_top1_vs_text":changed,"historical_correct_reported_by_original_reviewer":c}
        if arm in PAIR_ARMS:
            pair=review["paired_vs_text_only"][arm]
            require(type(pair) is dict, "invalid paired reviewer entry")
            r=integer(pair.get("rescued_errors_vs_text"),0,64)
            h=integer(pair.get("new_errors_vs_text"),0,64)
            assert_count=integer(pair.get("discordant_cases"),0,64)
            require(r+h==assert_count and r+h<=changed and c-base_total==r-h, "paired correctness inconsistent with actual predicted labels")
            p=pair.get("mcnemar_unadjusted_exact_p")
            require(type(p) in (int,float) and math.isfinite(p) and abs(exact_p(r,h)-p) < 1e-12, "original paired exact McNemar inconsistent")
            row.update({"historical_rescues_reported":r,"historical_harms_reported":h,"historical_both_wrong_on_changed_predictions_inferred":changed-r-h,
                        "impossible_answer_oracle_pair_correct_ceiling":base_total+r,"unadjusted_exact_mcnemar":p})
        elif arm in {"image_masked", "text_only"}:
            require(c==base_total and changed==0, "frozen text identity control changed")
        arm_results[arm]=row
    text=probs_by_arm["text_only"]; image=probs_by_arm["bridge_image_only"]
    # A text-only margin is known before executing an optional expensive image branch.
    calls=[];changed_triggered=0
    for t,i in zip(text,image):
        margin=sorted(t,reverse=True)[0]-sorted(t,reverse=True)[1]
        use_image=margin<PRIMARY_THRESHOLD
        calls.append(use_image)
        if use_image and top(t)!=top(i): changed_triggered+=1
    pair=review["paired_vs_text_only"]["bridge_image_only"]
    interval=primary_interval(base_total,pair["rescued_errors_vs_text"],pair["new_errors_vs_text"],arm_results["bridge_image_only"]["changed_top1_vs_text"],changed_triggered)
    require(sum(calls) <= 64 and changed_triggered <= sum(calls), "route census contradiction")
    return {"schema":"hepta.stem.v24.historical-modality-identification-limits.v1",
            "original_archive_sha256":ARCHIVE_SHA256,"original_prediction_sha256":PRED_SHA256,"original_source_sha256":SOURCE_SHA256,"original_commit":EXPECTED_HEAD,
            "cases":64,"claimed_source_groups":len(group_ids),"archived_labels_independently_reopened":False,
            "original_model_executed_this_run":False,"new_encoder_forwards":0,"new_model_training_updates":0,
            "model_modality_causal_necessity_established":False,"independent_future_windows":0,
            "arm_diagnostics":arm_results,
            "text_margin_conditional_image_route":{"predeclared_margin_threshold":PRIMARY_THRESHOLD,
                "method":"text-only margin < threshold, then archived image-arm prediction; no label access",
                "text_only_decisions":64,"conditional_image_calls_planned":sum(calls),"changed_top1_after_conditional_route":changed_triggered,
                "counterfactual_encoder_calls_not_physically_executed":True,
                "pairwise_only_bounds_reported_by_original_reviewer":interval,
                "actual_conditional_route_accuracy":None,"energy_joules":None,"physical_rss_bytes":None,"p99_ms":None},
            "decision":"HOLD_LABELS_AND_CAUSAL_NECESSITY_UNOBSERVED",
            "stem_winner_verified":False,"scientific_promotion_authorized":False,"production_authorized":False,"authority_posture":"DENY_ALL"}


def run(archive: Path, output: Path) -> dict:
    p,r,s=verify_archive(archive)
    readout=analyze(p,r,s)
    output.parent.mkdir(parents=True,exist_ok=True)
    with output.open("x",encoding="utf-8") as fh:
        json.dump(readout,fh,sort_keys=True,indent=2,allow_nan=False)
        fh.write("\n")
        fh.flush(); os.fsync(fh.fileno())
    return readout

if __name__=="__main__":
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--archive",required=True,type=Path)
    ap.add_argument("--output",required=True,type=Path)
    args=ap.parse_args()
    doc=run(args.archive,args.output)
    print(json.dumps({"decision":doc["decision"],"cases":doc["cases"],"conditional_image_calls_planned":doc["text_margin_conditional_image_route"]["conditional_image_calls_planned"],"production_authorized":False},sort_keys=True))