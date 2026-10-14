"""Separate source/metric re-computation for NEW snapshot replay, never FinalUse.

Consumes public val2 parquet plus original source, exact Head snapshot and the
independent model-process raw predictions. Does not import the model runner or
Head training routine. Does not authenticate model origin or historical Head.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path

from public_agnews_panel import canonical, sha, load_parquet
from public_agnews_confirmatory import create_panel, check_new_source_file
from sealed_cell_checkpoint import load_checkpoint


class NumericReviewError(ValueError):
    """Raw source, source label, tensor identity or prediction tampering."""


def require(ok, why):
    if not ok:
        raise NumericReviewError(why)


def _metrics(rows, truth):
    p = [(x["prob_sports"], truth[x["case_id"]]) for x in rows]
    n = len(p)
    require(n == 128, "missing full new-source sample")
    ece = 0.0
    for i in range(8):
        g = [(v, y) for v, y in p if min(7, int(max(v, 1-v)*8)) == i]
        if g:
            ece += (len(g)/n)*abs(sum((v>=0.5)==y for v,y in g)/len(g) -
                                  sum(max(v,1-v) for v,_ in g)/len(g))
    return {"cases": n, "accuracy": sum((v>=0.5)==y for v,y in p)/n,
            "brier": sum((v-y)**2 for v,y in p)/n,
            "descriptive_ece_8_equal_width": ece}


def review(*, original: dict, val2: dict, raw_source_rows: list, report: dict,
           bundle: Path, runtime_receipt: dict) -> dict:
    from agnews_paired_shadow import check_panel
    old_digest, _ = check_panel(original)
    # Recompute selection from *all* source rows; wrong labels on an apparently
    # balanced val2 panel must never be silently accepted.
    independently_selected = create_panel(original, raw_source_rows)
    require(canonical(independently_selected) == canonical(val2),
            "val2 source sample cannot be reproduced from full underlying rows")
    source_sha = val2.get("dataset_file_sha256")
    require(isinstance(source_sha, str) and len(source_sha)==64,
            "val2 source identity missing")
    sealed = load_checkpoint(
        bundle, source_panel_digest=old_digest,
        model_revision=report.get("physical_model_revision"),
        pipeline_digest=report.get("feature_pipeline_digest"),
        scope_id="public.agnews", purpose_id="capability.noeffects",
        generation=1, authority_epoch=1)
    record = sealed["receipt"]
    require(record == runtime_receipt, "snapshot's independent source receipt differs")
    require(isinstance(report, dict) and report.get("schema") ==
            "hepta.stem.val2-sealed-head-shadow-replay.v1" and
            report.get("original_source_panel_digest") == old_digest and
            report.get("val2_panel_digest") == sha(canonical(val2)) and
            report.get("new_file_source_sha256") == source_sha and
            report.get("snapshot_file_sha256") == record["snapshot_file_sha256"] and
            report.get("snapshot_payload_sha256") == record["snapshot_payload_sha256"] and
            report.get("checkpoint_q24_head_digests_checked_after_reload") is True and
            report.get("full_float64_head_bytes_unchanged_during_replay") is True and
            report.get("head_optimizer_steps_during_val2_evaluation") == 0 and
            report.get("case_count") == 128 and
            report.get("production_promotion") == "DENY_ALL" and
            report.get("historical_20261014_head_byte_identity_claimed") is False and
            report.get("independent_model_origin_authenticated") is False and
            report.get("three_chronological_future_windows") is False and
            report.get("equal_full_lifecycle_cost_authenticated") is False,
            "snapshot/authority/longitudinal claims not supported")
    arms = report.get("arms")
    require(isinstance(arms, dict) and set(arms) == {
        "gemma2_frozen_head", "gemma2_trained_head", "gemma2_trained_head_scaled_1024"},
        "wrong number/type of immutable replay arms")
    cases = {x["case_id"]:x for x in val2["cases"]}
    truth = {cid: case["label"] for cid,case in cases.items()}
    observations = {}
    scores = {}
    for name, arm in arms.items():
        expected_digest = record["frozen_head_digest" if name == "gemma2_frozen_head"
                                 else "trained_head_digest"]
        require(isinstance(arm, dict) and arm.get("head_digest") == expected_digest,
                "unexpected Head tensor digest or forged extra arm")
        rows = arm.get("rows")
        require(isinstance(rows, list) and len(rows) == len(cases),
                "missing complete 128-case model result")
        indexed = {}
        for row in rows:
            require(isinstance(row, dict) and set(row) == {
                "case_id","source_digest","joint_input_digest","prob_sports",
                "production_promotion"}, "unknown model prediction fields")
            case=cases.get(row["case_id"])
            val=row["prob_sports"]
            require(case is not None and row["case_id"] not in indexed and
                    row["source_digest"]==case["source_digest"] and
                    row["joint_input_digest"]==case["joint_input_digest"] and
                    row["production_promotion"]=="DENY_ALL" and
                    type(val) in (int,float) and math.isfinite(val) and 0<val<1,
                    "replayed output not matched to exact labelled source")
            indexed[row["case_id"]]=row
        observations[name]=indexed
        recomputed=_metrics([indexed[cid] for cid in sorted(cases)], truth)
        claimed=arm.get("metrics")
        require(isinstance(claimed, dict) and set(claimed)==set(recomputed) and
                all(type(claimed[k]) in (int,float) and math.isfinite(claimed[k])
                    and math.isclose(claimed[k],v,rel_tol=1e-10,abs_tol=1e-12)
                    for k,v in recomputed.items()),
                "self-reported frozen Head accuracy/Brier/ECE altered")
        scores[name]=recomputed
    for cid in cases:
        raw=observations["gemma2_trained_head"][cid]["prob_sports"]
        scaled=observations["gemma2_trained_head_scaled_1024"][cid]["prob_sports"]
        logodds=math.log(raw)-math.log1p(-raw)
        expected=1/(1+math.exp(-max(-50,min(50,1024*logodds))))
        expected=min(1-1e-12,max(1e-12,expected))
        require(math.isclose(scaled,expected,rel_tol=0,abs_tol=1e-12),
                "locked calibration was silently re-fit on new labels")
    return {
        "schema":"hepta.stem.val2-sealed-head-independent-numeric-review.v1",
        "source_panel_sha256":old_digest,
        "val2_panel_sha256":sha(canonical(val2)),
        "snapshot_sha256":record["snapshot_file_sha256"],
        "model_output_sha256":sha(canonical(report)),
        "val2_labels_reselected_from_full_source_rows":True,
        "all_case_probability_metrics_independently_recomputed":True,
        "historical_old_head_exact_replay_claimed":False,
        "new_snapshot_exact_float64_reloaded":True,
        "calibration_multiplier_fixed_before_new_results":True,
        "metrics":scores,
        "model_origin_independently_attested":False,
        "future_time_window_independently_attested":False,
        "pretraining_overlap_excluded":False,
        "full_lifecycle_cost_matched":False,
        "production_promotion":"DENY_ALL",
    }


if __name__ == "__main__":
    args=argparse.ArgumentParser(description="Independent public label and Head replay audit")
    for key in ("original", "val2", "val2-parquet", "report", "bundle", "receipt", "out"):
        args.add_argument("--"+key, required=True, type=Path)
    a=args.parse_args()
    check_new_source_file(a.val2_parquet)
    result=review(original=json.loads(a.original.read_text()),
                  val2=json.loads(a.val2.read_text()),
                  raw_source_rows=load_parquet(a.val2_parquet),
                  report=json.loads(a.report.read_text()),
                  bundle=a.bundle, runtime_receipt=json.loads(a.receipt.read_text()))
    if a.out.exists():
        raise NumericReviewError("do not overwrite previous evidence")
    a.out.write_bytes(canonical(result))
    print(json.dumps({"report_sha256":sha(canonical(result)),
                      "production_promotion":"DENY_ALL"},sort_keys=True))
