#!/usr/bin/env python3
"""Independent *stdlib-only* replay of actual Top-1 dispatch claims.

Uses original signed-by-nobody FP32 bytes and source labels, but never imports
Torch, the Top-1 producer, its scorer, or a model. Numeric agreement and
workload conservation are NOT signed Worker/host execution authentication.
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
import sys
from typing import Any

from qualification.cell_meta_execution_af import physical_router_audit as base

SCHEMA = "hepta.cell-meta-top1-physical-research.v1"
PARTS = ("old_retention", "future_1", "future_2", "ood")
ARMS = ("no_change", "fixed_router", "learned_router", "adaptive_split")


class Top1AuditError(ValueError):
    """Reported sparse Head dispatch cannot be independently replayed."""


def require(ok: bool, reason: str) -> None:
    if not ok:
        raise Top1AuditError(reason)


def guarded_float(value: Any, name: str) -> float:
    require(type(value) in (int, float) and math.isfinite(value) and value >= 0,
            f"{name}: finite, nonnegative numeric receipt")
    return float(value)


def replay(panel: dict[str, Any], soft: dict[str, Any], sparse: dict[str, Any]) -> dict[str, Any]:
    base.validate(panel, soft)  # Complete source/weights/soft predictions verified first.
    require(type(sparse) is dict and set(sparse) == {
        "schema", "source_panel_sha256", "predecessor_report_sha256", "method",
        "training_weights_updated", "reported_real_cpu_tensor_dispatch",
        "compute_matched_training", "independent_pretrained_encoder_attested",
        "real_ood_verified", "future_window_prospective", "independent_outcome_verified",
        "production_admission", "model_selection_permitted", "physical_cell_split_permitted",
        "authority_posture", "results",
    }, "unregistered Top-1 report fields")
    require(sparse["schema"] == SCHEMA and
            sparse["source_panel_sha256"] == base.digest(panel) and
            sparse["predecessor_report_sha256"] == base.digest(soft) and
            sparse["method"] == "post-training-frozen-head-soft-versus-hard-top1",
            "source, original model, or technique changed")
    expected_flags = {
        "training_weights_updated": False,
        "reported_real_cpu_tensor_dispatch": True,
        "compute_matched_training": False,
        "independent_pretrained_encoder_attested": False,
        "real_ood_verified": False,
        "future_window_prospective": False,
        "independent_outcome_verified": False,
        "production_admission": "BLOCKED",
        "model_selection_permitted": False,
        "physical_cell_split_permitted": False,
        "authority_posture": "DENY_ALL",
    }
    for key, value in expected_flags.items():
        require(type(sparse[key]) is type(value) and sparse[key] == value,
                f"{key}: false research/production authority claim")
    results = sparse["results"]
    require(type(results) is list and len(results) == 4 and
            [row.get("arm") for row in results if type(row) is dict] == list(ARMS),
            "incomplete or reordered Top-1 expert arms")
    width = panel["source"]["dim"]
    fixed_index = panel["source"]["router_feature_index"]
    counts = {p: len(panel["partitions"][p]) for p in PARTS}
    total = sum(counts.values())
    contrasts = []
    for candidate, old in zip(results, soft["results"], strict=True):
        require(type(candidate) is dict and set(candidate) == {
            "arm", "weights_sha256", "predecessor_prediction_sha256", "split_proposed",
            "top1_prediction_sha256", "top1_predictions", "metrics", "retrospective_evaluation",
        }, "unexpected Top-1 arm fields")
        arm = old["arm"]
        split = old["split_proposed"]
        require(candidate["arm"] == arm and
                candidate["weights_sha256"] == old["weights_sha256"] and
                candidate["predecessor_prediction_sha256"] == old["prediction_sha256"] and
                type(candidate["split_proposed"]) is bool and
                candidate["split_proposed"] == split,
                "frozen trained weights/split changed before Top-1")
        heads, gate = base.decode_fp32_weights(old, width)
        predictions = candidate["top1_predictions"]
        require(type(predictions) is dict and set(predictions) == set(PARTS) and
                candidate["top1_prediction_sha256"] == base.digest(predictions),
                "unsealed or missing Top-1 predictions")
        evaluations = candidate["retrospective_evaluation"]
        require(type(evaluations) is dict and set(evaluations) == set(PARTS),
                "incomplete independent Top-1 scoring")
        head_rows = [0, 0]
        router_rows = 0
        head_batches = 0
        score_deltas: dict[str, float] = {}
        for part in PARTS:
            source_rows = panel["partitions"][part]
            entries = predictions[part]
            require(type(entries) is list and len(entries) == counts[part],
                    "missing/mismatched Top-1 prediction rows")
            selected_in_part = set()
            ps = []
            for case, result in zip(source_rows, entries, strict=True):
                require(type(result) is dict and set(result) == {
                    "id", "selected_head", "probability"}, "Top-1 row contract")
                x = case["features"] + [1.0]
                require(result["id"] == case["id"], "Top-1 row/source mapping drift")
                if not split:
                    selected = 0
                elif arm == "fixed_router":
                    selected = int(x[fixed_index] >= 0.0)
                else:
                    selected = int(sum(a*b for a, b in zip(x, gate, strict=True)) >= 0.0)
                    router_rows += 1
                require(type(result["selected_head"]) is int and
                        result["selected_head"] == selected,
                        "Top-1 expert selection disagrees with frozen router")
                start = selected * (width + 1)
                p = base.sigmoid(sum(x[j]*heads[start+j] for j in range(width+1)))
                p = min(1-base.EPS, max(base.EPS, p))
                stated = result["probability"]
                require(type(stated) is float and math.isfinite(stated) and
                        base.EPS <= stated <= 1-base.EPS and abs(stated-p) < 3e-6,
                        "one-expert FP32 logits do not reproduce the emitted prediction")
                ps.append(stated)
                selected_in_part.add(selected)
                head_rows[selected] += 1
            head_batches += len(selected_in_part)
            count = len(ps)
            labels = [row["label"] for row in source_rows]
            expected = {
                "count": count,
                "accuracy": round(sum(int((p>=0.5) == bool(y))
                                      for p, y in zip(ps, labels, strict=True))/count, 7),
                "brier": round(sum((p-y)**2 for p, y in zip(ps, labels, strict=True))/count, 7),
                "nll": round(-sum(y*math.log(p) + (1-y)*math.log1p(-p)
                                  for p, y in zip(ps, labels, strict=True))/count, 7),
            }
            stated_metric = evaluations[part]
            require(type(stated_metric) is dict and set(stated_metric) == set(expected) and
                    type(stated_metric["count"]) is int and
                    stated_metric["count"] == count and
                    all(type(stated_metric[k]) in (float, int) and
                        math.isfinite(stated_metric[k]) and
                        abs(stated_metric[k]-expected[k]) <= 1e-7
                        for k in ("accuracy", "brier", "nll")),
                    "Top-1 metric does not replay from frozen source labels")
            score_deltas[part] = round(expected["brier"] - old["evaluation"][part]["brier"], 7)
        met = candidate["metrics"]
        require(type(met) is dict and set(met) == {
            "executed_head_rows", "head_0_rows", "head_1_rows", "head_batch_matmuls",
            "router_rows", "cpu_seconds"}, "Top-1 resource accounting incomplete")
        require(all(type(met[key]) is int and met[key] >= 0 for key in
                    ("executed_head_rows", "head_0_rows", "head_1_rows", "head_batch_matmuls", "router_rows")),
                "forged Top-1 resource types")
        require(met["executed_head_rows"] == total and
                met["head_0_rows"] == head_rows[0] and
                met["head_1_rows"] == head_rows[1] and
                met["head_batch_matmuls"] == head_batches and
                met["router_rows"] == router_rows and
                math.isfinite(guarded_float(met["cpu_seconds"], "cpu_seconds")),
                "Top-1 resource rows do not conserve one executed Head per input")
        if not split:
            require(head_rows[1] == 0 and router_rows == 0,
                    "unsplit Cell secretly invokes an expert/router")
        elif arm == "fixed_router":
            require(router_rows == 0, "fixed router hides learned gate work")
        contrasts.append({"arm": arm, "top1_executed_head_rows": total,
                          "soft_original_eval_head_rows": total * (2 if split else 1),
                          "retrospective_brier_delta_top1_minus_soft": score_deltas})
    return {
        "outcome": "NUMERIC_TOP1_REPLAY_NO_AUTHORITY",
        "contrasts": contrasts, "all_four_arms_verified": True,
        "actual_cpu_execution_independently_attested": False,
        "prospective_gain_or_ood_established": False,
        "compute_matched_training": False,
        "production_selection_authorized": False,
        "authority_posture": "DENY_ALL",
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--panel", type=Path, required=True)
    parser.add_argument("--soft-report", type=Path, required=True)
    parser.add_argument("--top1-report", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        result = replay(base.load(args.panel), base.load(args.soft_report),
                        base.load(args.top1_report))
        print(json.dumps(result, sort_keys=True))
        return 0
    except (Top1AuditError, base.AuditError, KeyError, IndexError,
            OSError, ValueError, TypeError, RecursionError, OverflowError) as exc:
        print(f"TOP1 REPLAY BLOCKED: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
