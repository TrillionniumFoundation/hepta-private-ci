"""Torch-free independent numeric review of physical selected-Head P2 probe.

Separately verifies source/route/weights/predictions through the original
NumPy reference equations. It cannot prove OS CPU instrumentation, model
provenance, serving latency, independent utility or actual signed permissions.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import stat
import sys
from pathlib import Path

import numpy as np
import p2_real_cell_split_review as original_math

SCHEMA = "hepta.p2.actual-selected-head-independent-review.v1"
PROBE_SCHEMA = "hepta.p2.actual-selected-head-physical-shadow.v1"
ARMS = ("fixed_two_cell", "adaptive_train_only")
REPEATS = 13
MAX_INPUT_BYTES = 16 * 1024 * 1024


def read_source(path):
    fd = os.open(path, os.O_RDONLY | getattr(os,"O_NOFOLLOW",0) |
                 getattr(os,"O_NONBLOCK",0))
    try:
        start = os.fstat(fd)
        require(stat.S_ISREG(start.st_mode) and 0 < start.st_size <= MAX_INPUT_BYTES,
                "original/probe review requires a bounded regular file")
        with os.fdopen(fd,"rb",closefd=False) as stream:
            raw = stream.read(MAX_INPUT_BYTES+1)
        end = os.fstat(fd)
        require(len(raw)==start.st_size and
                (start.st_dev,start.st_ino,start.st_size,start.st_mtime_ns)==
                (end.st_dev,end.st_ino,end.st_size,end.st_mtime_ns),
                "file changed during independent review")
    finally:
        os.close(fd)
    def unique(pairs):
        out={}
        for k,v in pairs:
            require(k not in out,"duplicate untrusted JSON field")
            out[k]=v
        return out
    return json.loads(raw,object_pairs_hook=unique,
                      parse_constant=lambda v: (_ for _ in ()).throw(ValueError("nonfinite source JSON")))


def require(value, description):
    if not value:
        raise ValueError(description)


def audit(parent, physical, prior):
    require(type(parent) is dict and
            parent.get("schema") == original_math.SCHEMA and
            parent.get("report_sha256") ==
                original_math.digest({k:v for k,v in parent.items() if k != "report_sha256"}) and
            parent.get("authority") == "DENY_ALL" and
            parent.get("selection_authorized") is False and
            parent.get("production_promotion_permitted") is False,
            "original source/no-authorization seal changed")
    require(type(prior) is dict and
            prior.get("schema") == "hepta.p2.equal-cell-independent-review.v1" and
            prior.get("source_panel_sha256") == parent.get("public_panel_sha256") and
            prior.get("authority") == "DENY_ALL" and
            prior.get("all_four_model_arms_replayed") is True and
            prior.get("eligible_model_selection") is False and
            prior.get("production_promotion_permitted") is False,
            "previous original human-source NumPy review not complete")
    require(type(physical) is dict and set(physical) == {
        "schema", "original_p2_report_sha256",
        "original_source_heldout_sha256", "original_source_q24_sha256",
        "original_heldout_rows", "original_train_only_threshold",
        "bench_repetitions_each_mode", "pretrained_encoder_loaded_in_probe",
        "pretrained_encoder_forward_calls_in_probe",
        "actual_local_cpu_selected_head_execution", "full_task_cpu_cost_matched",
        "pretrained_model_origin_independently_authenticated",
        "source_original_labels_seen_by_probe", "future_window_prospective",
        "independent_ndu_selection_authorized", "production_admission",
        "authority_posture", "arms",
    }, "unknown physical probe report fields")
    for key, expected in {
        "schema": PROBE_SCHEMA,
        "original_p2_report_sha256": parent["report_sha256"],
        "original_source_heldout_sha256": original_math.digest(parent["source_heldout_cases"]),
        "original_source_q24_sha256": original_math.digest(parent["source_features_q24"]),
        "original_heldout_rows": 96,
        "original_train_only_threshold": parent["cutoff_feature0_train_median"],
        "bench_repetitions_each_mode": REPEATS,
        "pretrained_encoder_loaded_in_probe": False,
        "pretrained_encoder_forward_calls_in_probe": 0,
        "actual_local_cpu_selected_head_execution": True,
        "full_task_cpu_cost_matched": False,
        "pretrained_model_origin_independently_authenticated": False,
        "source_original_labels_seen_by_probe": False,
        "future_window_prospective": False,
        "independent_ndu_selection_authorized": False,
        "production_admission": "BLOCKED",
        "authority_posture": "DENY_ALL",
    }.items():
        require(type(physical[key]) is type(expected) and physical[key] == expected,
                "missing exact research/safety/source field: " + key)
    arms = physical["arms"]
    require(type(arms) is dict and set(arms) == set(ARMS),
            "exact fixed/adaptive physical comparison required")
    cases = parent["source_heldout_cases"]
    features = parent["source_features_q24"]
    require(type(cases) is list and len(cases) == 96 and
            type(features) is dict and set(features) == {case["case_id"] for case in cases},
            "missing original heldout Q24 source")
    require(all(type(features[c["case_id"]]) is list and
                len(features[c["case_id"]]) == 384 and
                all(type(q) is int and abs(q) <= 8 * (1<<24)
                    for q in features[c["case_id"]]) for c in cases),
            "invalid exact original Q24 rows")
    x = np.asarray([[q/(1<<24) for q in features[c["case_id"]]] for c in cases],
                   dtype=np.float32)
    cutoff = parent["cutoff_feature0_train_median"]
    require(type(cutoff) is float and math.isfinite(cutoff),
            "wrong train-only routing cutoff")
    result = {}
    for arm_name in ARMS:
        original_arm = parent["compared_arms"][arm_name]
        observed = arms[arm_name]
        require(type(observed) is dict and set(observed) == {
            "split_proposed", "source_weights_sha256", "group_selected_row_counts",
            "selected_case_head_indices", "actual_sparse_logits",
            "max_abs_dense_and_original_logit_delta",
            "dense_two_head_forward_rows", "sparse_selected_head_forward_rows",
            "sparse_head_dispatch_groups", "dense_head_compute_skipped_in_sparse",
            "real_cpu_dense_process_ns", "real_cpu_sparse_process_ns",
        }, "unexpected physical probe arm fields")
        split = original_arm["split_proposed"]
        expected_choices = ([0]*96 if arm_name == "adaptive_train_only" and split is False
                            else (x[:,0] >= cutoff).astype(np.int64).tolist())
        require(type(observed["split_proposed"]) is bool and
                observed["split_proposed"] == split and
                observed["source_weights_sha256"] == original_arm["final_weights_sha256"] and
                type(observed["selected_case_head_indices"]) is list and
                all(type(v) is int and v in (0,1)
                    for v in observed["selected_case_head_indices"]) and
                observed["selected_case_head_indices"] == expected_choices,
                "physical selected-head roster not bound to original policy")
        group_counts = [expected_choices.count(i) for i in (0, 1)]
        require(type(observed["group_selected_row_counts"]) is list and
                all(type(v) is int and 0<=v<=96
                    for v in observed["group_selected_row_counts"]) and
                observed["group_selected_row_counts"] == group_counts and
                all(type(observed[key]) is int for key in (
                    "dense_two_head_forward_rows",
                    "sparse_selected_head_forward_rows",
                    "dense_head_compute_skipped_in_sparse",
                    "sparse_head_dispatch_groups")) and
                observed["dense_two_head_forward_rows"] == 192 and
                observed["sparse_selected_head_forward_rows"] == 96 and
                observed["dense_head_compute_skipped_in_sparse"] == 96 and
                observed["sparse_head_dispatch_groups"] == sum(bool(v) for v in group_counts),
                "actual Head dispatch row accounting or roster drift")
        logits = np.asarray(observed["actual_sparse_logits"], dtype=np.float64)
        require(logits.shape == (96,2) and bool(np.isfinite(logits).all()) and
                type(observed["actual_sparse_logits"]) is list and
                all(type(row) is list and len(row) == 2 and
                    all(type(v) is float and math.isfinite(v) for v in row)
                    for row in observed["actual_sparse_logits"]),
                "physical sparse case logits missing or corrupt")
        # This independently reconstructs the original dense HEAD geometry
        # from exact FP32 weights, without calling the Torch sparse producer.
        actual = original_math.np_logits(x, original_arm["weights"],
                                          arm_name, split, cutoff)
        claimed_dense = np.asarray(original_arm["logits"], dtype=np.float64)
        max_diff = float(max(np.max(np.abs(actual-logits)),
                             np.max(np.abs(actual-claimed_dense))))
        require(max_diff <= 4e-5 and
                type(observed["max_abs_dense_and_original_logit_delta"]) is float and
                math.isfinite(observed["max_abs_dense_and_original_logit_delta"]) and
                observed["max_abs_dense_and_original_logit_delta"] >= 0 and
                observed["max_abs_dense_and_original_logit_delta"] <= 4e-5,
                "separately replayed selected-only FP32 output mismatch")
        for key in ("real_cpu_dense_process_ns", "real_cpu_sparse_process_ns"):
            ns = observed[key]
            require(type(ns) is list and len(ns) == REPEATS and
                    all(type(v) is int and 0 < v < 60_000_000_000 for v in ns),
                    "missing actual bounded CPU process samples")
        from statistics import median
        dense = observed["real_cpu_dense_process_ns"]
        sparse = observed["real_cpu_sparse_process_ns"]
        result[arm_name] = {
            "replayed_source_head_rows": 96,
            "dense_two_head_row_work": 192,
            "physical_selected_head_row_work_claim": 96,
            "logical_selection_numerically_reproduced": True,
            "independent_logit_delta_max": max_diff,
            "paired_dense_cpu_p50_process_ns": int(median(dense)),
            "paired_sparse_cpu_p50_process_ns": int(median(sparse)),
            "actual_cpu_speedup_certified": False,
            "target_host_cpu_rss_energy_certified": False,
        }
    return {
        "schema": SCHEMA,
        "outcome": "NUMERIC_SELECTED_HEAD_PARITY_ONLY",
        "original_p2_report_sha256": parent["report_sha256"],
        "private_selected_head_probe_sha256": original_math.digest(physical),
        "independently_replayed_original_human_source_review": True,
        "per_head_forward_row_reduction_observed_in_source": 0.5,
        "source_execution_counters_independently_attested": False,
        "actual_cpu_wall_speedup_certified": False,
        "full_lifecycle_compute_matched": False,
        "future_task_independence_established": False,
        "physical_cell_split_authorized": False,
        "codex_effect_authorized": False,
        "eligible_model_selection": False,
        "production_admission": "BLOCKED",
        "authority_posture": "DENY_ALL",
        "arms": result,
    }


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    for key in ("original-report","physical-probe","original-review","output"):
        ap.add_argument("--"+key, required=True, type=Path)
    args = ap.parse_args(argv)
    try:
        parent = read_source(args.original_report)
        physical = read_source(args.physical_probe)
        prior = read_source(args.original_review)
        verdict = audit(parent, physical, prior)
        data = original_math.canonical(verdict) + b"\n"
        import os
        fd = os.open(args.output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "wb") as out:
            out.write(data)
            out.flush()
            os.fsync(out.fileno())
        print(json.dumps({"result": verdict["outcome"],
                          "production_admission": "BLOCKED"}, sort_keys=True))
        return 0
    except (ValueError, OSError, KeyError, IndexError, TypeError, OverflowError) as err:
        print(f"BLOCKED: {err}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
