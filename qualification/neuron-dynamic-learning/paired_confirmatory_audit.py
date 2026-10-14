"""Independent read-only numerical audit of a NEW nonoverlapping public source.

The original 224-case AG News panel and its physical reports were reviewed
before choosing the fixed 1024 logit scale. This experiment locks that scale
BEFORE evaluating 128 different cases from val2. This is cross-sectional,
not a temporally later outcome, provider-origin attestation or promotion.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import random
from pathlib import Path

from paired_independent_audit import verify as verify_original
from public_agnews_confirmatory import (check_panel as check_new_panel,
                                      check_new_source_file, create_panel)
from exploratory_temperature_probe import scale_probability
from public_agnews_panel import canonical, sha

GEMMA_REV = "914f7f89142e33e77833254d9c9b90c3cef7303b"
LAYA_REV = "55cf4c4ebb4ebe31b2550e8bdf3bd21b99753851"
ARMS = (
    "gemma2_frozen_head", "gemma2_trained_head",
    "gemma2_trained_head_scaled_1024", "laya421_frozen",
)
SCALED_MULTIPLIER = 1024


class AuditError(ValueError):
    """Unbound, missing, tampered, or artificially promoted public evidence."""


def ensure(flag: bool, reason: str):
    if not flag:
        raise AuditError(reason)


def _digest(value: object):
    return isinstance(value,str) and len(value)==64 and all(x in "0123456789abcdef" for x in value)


def _check_arm(report: dict, expected_arm: str, new_digest: str,
               original_digest: str, source_cases: dict[str,dict]):
    ensure(isinstance(report,dict) and set(report)=={
        "schema", "panel_digest", "original_train_panel_digest", "arm_id",
        "rows", "metadata", "raw_source_and_model_origin_independently_attested",
        "cross_sectional_new_source_not_temporal_future",
        "foundation_pretraining_overlap_ruled_out", "matched_full_lifecycle_cost",
        "production_promotion",
    }, "bad confirmatory report schema")
    ensure(report["schema"] == "hepta.stem.agnews-confirmatory-physical-arm.v1"
           and report["panel_digest"] == new_digest
           and report["original_train_panel_digest"] == original_digest
           and report["arm_id"] == expected_arm
           and report["raw_source_and_model_origin_independently_attested"] is False
           and report["cross_sectional_new_source_not_temporal_future"] is True
           and report["foundation_pretraining_overlap_ruled_out"] is False
           and report["matched_full_lifecycle_cost"] is False
           and report["production_promotion"] == "DENY_ALL",
           "unqualified authority or reused old panel")
    m = report["metadata"]
    ensure(isinstance(m,dict), "missing frozen model/Head identity")
    if expected_arm == "laya421_frozen":
        ensure(m.get("backend") == "convaiinnovations/laya"
               and m.get("revision") == LAYA_REV
               and m.get("pretrained_checkpoint_verified_by_loader") is True
               and m.get("trainable_parameters") == 0
               and m.get("predetermined_logit_multiplier") == 1
               and m.get("shared_batch_wall_time_allocation") == "not_shared_singleton_calls",
               "unbound frozen Laya model")
    else:
        expected_train_steps = 0 if expected_arm == "gemma2_frozen_head" else 40
        alpha = SCALED_MULTIPLIER if expected_arm.endswith("scaled_1024") else 1
        ensure(m.get("backend") == "google/embeddinggemma-2"
               and m.get("revision") == GEMMA_REV
               and _digest(m.get("stem_digest"))
               and _digest(m.get("frozen_head_digest"))
               and _digest(m.get("trained_head_digest"))
               and m["frozen_head_digest"] != m["trained_head_digest"]
               and m.get("reported_head_digest") == m[
                   "frozen_head_digest" if expected_train_steps == 0 else "trained_head_digest"]
               and type(m.get("trainable_head_parameters")) is int
               and 0 < m["trainable_head_parameters"] <= 2048
               and m.get("head_training_steps") == expected_train_steps
               and m.get("predetermined_logit_multiplier") == alpha
               and m.get("shared_batch_wall_time_allocation") ==
                   "equal_amortization_not_individual_latency"
               and m.get("pretrained_model_tokenization_identity_only") ==
                   "not_independently_attested",
               "unregistered frozen/trained Head or post-hoc temperature")
    rows = report.get("rows")
    ensure(isinstance(rows,list) and len(rows)==len(source_cases),
           "incomplete fresh-cohort predictions")
    seen={}
    for row in rows:
        ensure(isinstance(row,dict) and set(row)=={
            "case_id", "source_digest", "joint_input_digest", "split",
            "prob_sports", "measured_serving_micros",
        }, "wrong raw result tuple")
        case = source_cases.get(row["case_id"])
        ensure(case is not None and row["case_id"] not in seen
               and all(row[k]==case[k] for k in (
                   "case_id", "source_digest", "joint_input_digest", "split"))
               and type(row["prob_sports"]) in (float,int)
               and math.isfinite(row["prob_sports"])
               and 0<=row["prob_sports"]<=1
               and type(row["measured_serving_micros"]) is int
               and row["measured_serving_micros"]>0,
               "missing, duplicated, misaligned or nonfinite case")
        seen[row["case_id"]]=row
    return seen,m


def _metrics(rows: dict, cases: dict):
    ordered=sorted(cases)
    pairs=[(rows[cid]["prob_sports"],cases[cid]["label"]) for cid in ordered]
    acc=sum((p>=.5)==label for p,label in pairs)/len(pairs)
    brier=sum((p-label)**2 for p,label in pairs)/len(pairs)
    ece=0.
    for bucket in range(8):
        assigned=[(p,y) for p,y in pairs if min(7,int(max(p,1-p)*8))==bucket]
        if assigned:
            accuracy=sum((p>=.5)==y for p,y in assigned)/len(assigned)
            confidence=sum(max(p,1-p) for p,y in assigned)/len(assigned)
            ece+=len(assigned)/len(pairs)*abs(accuracy-confidence)
    return {"cases":len(pairs), "accuracy":acc, "brier":brier,
            "descriptive_ece_8bin":ece,
            "allocated_serving_time_micros":sum(rows[cid]["measured_serving_micros"]
                                               for cid in ordered)}


def _paired_bootstrap(a: dict,b: dict,cases: dict,seed:int):
    # Fixed deterministic 1000-resample paired Brier difference uncertainty.
    # Cluster independence isn't asserted; 1 case=1 claimed source-group.
    deltas=[(a[cid]["prob_sports"]-cases[cid]["label"])**2-
            (b[cid]["prob_sports"]-cases[cid]["label"])**2
            for cid in sorted(cases)]
    rng=random.Random(seed)
    distribution=sorted(sum(deltas[rng.randrange(len(deltas))] for _ in deltas)/len(deltas)
                        for _ in range(1000))
    return {"mean_brier_reduction":sum(deltas)/len(deltas),
            "paired_bootstrap_95ci_descriptive": [distribution[25],distribution[974]],
            "nominal_not_corrected_for_multiple_arms":True}


def verify(original, source_receipt, original_gemma, original_laya,
           original_comparison, confirmatory, gemma, laya, raw_new_source_rows):
    old=verify_original(original,source_receipt,original_gemma,original_laya,
                        original_comparison)
    old_digest=old["panel_digest"]
    from historical_head_anchor import check_reports as require_previous_reports
    # Independent evaluator must not trust the runner's claim that the Head
    # used on val2 is identical to the historical executed Q24 artifact.
    historical_lock = require_previous_reports(
        original_panel_digest=old_digest,
        original_gemma=original_gemma,
        original_laya=original_laya,
    )
    # Rebuild from the independently SHA-256 checked *entire* val2 parquet:
    # a correctly shaped, balanced panel with forged labels is not sufficient.
    expected=create_panel(original,raw_new_source_rows)
    ensure(canonical(expected)==canonical(confirmatory),
           "replication panel does not reproduce immutable source rows and labels")
    confirm_digest,cases_list=check_new_panel(confirmatory,original)
    cases={case["case_id"]:case for case in cases_list}
    ensure(isinstance(gemma,list) and len(gemma)==3,
           "new Gemma frozen/trained/calibrated reports incomplete")
    reports=[*gemma,laya]
    ensure(sorted(report.get("arm_id","") for report in reports if isinstance(report,dict))
           ==sorted(ARMS), "wrong or duplicated new-model arm")
    observed={}; identities={}
    for report in reports:
        a=report["arm_id"]
        observed[a],identities[a]=_check_arm(report,a,confirm_digest,old_digest,cases)
    # Link to previous actual frozen/trained physical Head artifact identities.
    old_map={r["arm_id"]:r for r in original_gemma}
    ensure(set(old_map)=={"gemma2_frozen_head","gemma2_trained_head"},
           "missing original head lineage")
    common_stem=old_map["gemma2_trained_head"]["metadata"]["stem_digest"]
    frozen_digest=old_map["gemma2_frozen_head"]["metadata"]["head_artifact_digest"]
    trained_digest=old_map["gemma2_trained_head"]["metadata"]["head_artifact_digest"]
    for a in ARMS[:3]:
        m=identities[a]
        ensure(m["stem_digest"]==common_stem and
               m["frozen_head_digest"]==frozen_digest and
               m["trained_head_digest"]==trained_digest and
               m["trainable_head_parameters"]==old_map["gemma2_trained_head"]["metadata"]["head_parameters"],
               "new confirmatory input re-trained or altered the old Stem/Head")
    ensure(identities["laya421_frozen"]["revision"]==
           original_laya["metadata"]["revision"],
           "Laya model version not stable across cohorts")
    for cid in cases:
        raw=observed["gemma2_trained_head"][cid]["prob_sports"]
        scaled=observed["gemma2_trained_head_scaled_1024"][cid]["prob_sports"]
        ensure(0 < raw < 1 and math.isclose(scaled,
               scale_probability(raw,SCALED_MULTIPLIER),rel_tol=0,abs_tol=1e-12),
               "calibration multiplier fitted or changed on new holdout")
    measures={arm:_metrics(observed[arm],cases) for arm in ARMS}
    seed=int(confirm_digest[:14],16)
    comparisons={
        "trained_vs_frozen":_paired_bootstrap(observed["gemma2_frozen_head"],
                                               observed["gemma2_trained_head"],cases,seed),
        "calibrated_vs_raw":_paired_bootstrap(observed["gemma2_trained_head"],
                                                observed["gemma2_trained_head_scaled_1024"],cases,seed),
        "calibrated_vs_laya":_paired_bootstrap(observed["laya421_frozen"],
                                                 observed["gemma2_trained_head_scaled_1024"],cases,seed),
    }
    return {
        "schema":"hepta.stem.agnews-new-file-replication-review.v1",
        "original_panel_digest":old_digest,
        "replication_panel_digest":confirm_digest,
        "replication_source_file_sha256":confirmatory["dataset_file_sha256"],
        "source_and_report_digests": {r["arm_id"]:sha(canonical(r)) for r in reports},
        "source_case_selection_recomputed_from_full_val2_parquet":True,
        "extra_panel_rows":len(cases),"source_disjoint_from_original":True,
        "fixed_logit_multiplier_from_prior_exploration": SCALED_MULTIPLIER,
        "metric_definitions":"binary_05_threshold_brier_8_equal_width_ece",
        "metrics":measures,
        "descriptive_pairwise_uncertainty":comparisons,
        "historical_pre_val2_head_identity_locked": historical_lock["reference_local_tensor_lineage_matched"],
        "historical_reference_run": historical_lock["executed_reference_run"],
        "model_reported_feature_lineage_bound":True,
        "model_forward_origin_independently_authenticated":False,
        "model_parameter_learning_on_new_holdout":False,
        "calibration_fit_on_new_holdout":False,
        "new_source_file_but_same_public_dataset_family":True,
        "new_window_is_chronologically_future":False,
        "foundation_pretraining_contamination_excluded":False,
        "equal_total_lifecycle_cost_proven":False,
        "selection_or_final_use_authority":"DENY_ALL",
        "production_promotion":"DENY_ALL",
    }


def main():
    parser=argparse.ArgumentParser(description="Read-only frozen new-file replication")
    for name in ("original","source","original-gemma","original-laya",
                 "original-comparison","confirmatory","new-gemma","new-laya","out"):
        parser.add_argument("--"+name,type=Path,required=True)
    parser.add_argument("--raw-val2-parquet",type=Path,required=True)
    args=parser.parse_args()
    check_new_source_file(args.raw_val2_parquet)
    from public_agnews_panel import load_parquet
    fields=("original","source","original_gemma","original_laya",
            "original_comparison","confirmatory","new_gemma","new_laya")
    data=[json.loads(getattr(args,field).read_text(encoding="utf-8")) for field in fields]
    result=verify(*data,load_parquet(args.raw_val2_parquet))
    args.out.write_bytes(canonical(result))
    print(json.dumps({"report_sha256":sha(canonical(result)),
                      "replication_rows":result["extra_panel_rows"],
                      "production_promotion":"DENY_ALL"},sort_keys=True))


if __name__=="__main__":
    main()
