#!/usr/bin/env python3
"""Torch-free numerical replay of an old-only frozen-Parent Cell baseline.

This is NOT independent source/label authentication or an NDU Selector. The
'reference no_change' in the earlier four-arm trial continues joint training;
it must not be presented as the frozen baseline supplied here.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path
from typing import Any

from qualification.cell_meta_execution_af import physical_router_audit as numeric

SCHEMA = "hepta.cell-meta-frozen-old-parent.v1"
PARTITIONS = ("old_retention", "future_1", "future_2", "ood")
FIELDS = frozenset({
    "schema", "source_panel_sha256", "source_kind", "source_scope", "seed",
    "freeze_point", "trained_new_rows", "split_proposed", "optimizer_steps_old_only",
    "weights_sha256", "weights_fp32", "prediction_sha256", "predictions", "evaluation",
    "meters", "physically_executed_torch_fp32", "real_pretrained_encoder_executed",
    "original_source_authenticated", "independent_outcome_verified", "future_window_prospective",
    "total_compute_matched", "ndu_selection_authorized", "production_admission",
    "authority_posture",
})


def require(ok: bool, why: str) -> None:
    if not ok:
        raise numeric.AuditError(why)


def validate(panel: dict[str, Any], frozen: dict[str, Any],
             continued: dict[str, Any] | None = None) -> dict[str, Any]:
    """Replay frozen weights and identify an unfrozen, continued-SGD control."""
    require(type(panel) is dict and panel.get("schema") == "hepta.cell-meta-router-panel.v1",
            "unknown original panel")
    source = panel.get("source")
    partitions = panel.get("partitions")
    require(type(source) is dict and type(partitions) is dict, "missing original source")
    require(set(partitions) == {"old_train", "new_train", *PARTITIONS},
            "incomplete original cohorts")
    width = source.get("dim")
    index = source.get("router_feature_index")
    require(type(width) is int and 2 <= width <= 64 and type(index) is int
            and 0 <= index < width, "invalid original feature profile")
    require(type(frozen) is dict and set(frozen) == FIELDS, "unknown frozen artifact fields")
    require(frozen["schema"] == SCHEMA, "wrong frozen artifact schema")
    require(frozen["source_panel_sha256"] == numeric.digest(panel) and
            frozen["source_kind"] == source.get("kind") and
            frozen["source_scope"] == source.get("scope") and
            frozen["seed"] == source.get("seed"), "changed frozen source identity")
    for name, expected in {
        "freeze_point": "after_old_train_before_new_train",
        "trained_new_rows": 0, "split_proposed": False,
        "physically_executed_torch_fp32": True,
        "real_pretrained_encoder_executed": False,
        "original_source_authenticated": False,
        "independent_outcome_verified": False,
        "future_window_prospective": False,
        "total_compute_matched": False,
        "ndu_selection_authorized": False,
        "production_admission": "BLOCKED",
        "authority_posture": "DENY_ALL",
    }.items():
        require(type(frozen[name]) is type(expected) and frozen[name] == expected,
                "false frozen baseline or authority claim: " + name)
    steps = frozen["optimizer_steps_old_only"]
    require(type(steps) is int and 2 <= steps <= 100, "invalid frozen train step count")
    heads, gate = numeric.decode_fp32_weights(frozen, width)
    require(all(value == 0.0 for value in heads[width + 1:] + gate),
            "frozen old-parent unexpectedly contains split/router parameters")
    # If training were skipped entirely, this is not the old-trained frozen control.
    require(any(value != 0.0 for value in heads[:width + 1]),
            "no evidence of changed parent weights")
    expected_p = frozen["predictions"]
    expected_e = frozen["evaluation"]
    require(type(expected_p) is dict and set(expected_p) == set(PARTITIONS)
            and numeric.digest(expected_p) == frozen["prediction_sha256"],
            "frozen prescore seal does not bind all partitions")
    require(type(expected_e) is dict and set(expected_e) == set(PARTITIONS),
            "incomplete frozen evaluation")
    total_eval = 0
    for part in PARTITIONS:
        rows = partitions[part]
        preds = expected_p[part]
        require(type(rows) is list and len(rows) >= 16 and type(preds) is list
                and len(preds) == len(rows), "unpaired frozen cohort")
        scores = []
        labels = []
        for row, item in zip(rows, preds, strict=True):
            require(type(row) is dict and type(item) is dict and
                    set(item) == {"id", "probability"} and row.get("id") == item["id"],
                    "frozen case identity drift")
            xs = row.get("features")
            y = row.get("label")
            p = item["probability"]
            require(type(xs) is list and len(xs) == width and
                    all(type(x) in (int, float) and math.isfinite(x) and -32 <= x <= 32
                        for x in xs) and type(y) is int and y in (0, 1) and
                    type(p) is float and math.isfinite(p) and numeric.EPS <= p <= 1 - numeric.EPS,
                    "invalid frozen numerical row")
            replay = numeric.predict(row, heads, gate, width, index,
                                     arm="no_change", split=False)
            require(abs(replay - p) < 3e-6, "frozen fp32 bytes disagree with stored prediction")
            scores.append(p)
            labels.append(y)
        acc = sum(int((p >= 0.5) == bool(y)) for p, y in zip(scores, labels, strict=True)) / len(rows)
        brier = sum((p - y) ** 2 for p, y in zip(scores, labels, strict=True)) / len(rows)
        nll = -sum(y * math.log(p) + (1 - y) * math.log1p(-p)
                   for p, y in zip(scores, labels, strict=True)) / len(rows)
        metrics = expected_e[part]
        require(type(metrics) is dict and set(metrics) == {"count", "accuracy", "brier", "nll"}
                and type(metrics["count"]) is int and metrics["count"] == len(rows)
                and all(type(metrics[k]) is float and math.isfinite(metrics[k])
                        for k in ("accuracy", "brier", "nll")) and
                abs(acc - metrics["accuracy"]) <= 1e-7 and
                abs(brier - metrics["brier"]) <= 1e-7 and
                abs(nll - metrics["nll"]) <= 1e-7,
                "frozen result scoring mismatch")
        total_eval += len(rows)
    meters = frozen["meters"]
    require(type(meters) is dict and set(meters) == {
        "optimizer_steps", "sample_exposures", "head_forward_rows", "router_forward_rows",
        "train_cpu_seconds"}, "missing frozen meters")
    old_count = len(partitions["old_train"])
    require(all(type(meters[k]) is int for k in (
        "optimizer_steps", "sample_exposures", "head_forward_rows", "router_forward_rows"))
            and meters["optimizer_steps"] == steps
            and meters["sample_exposures"] == steps * old_count
            and meters["head_forward_rows"] == steps * old_count + total_eval
            and meters["router_forward_rows"] == 0 and
            type(meters["train_cpu_seconds"]) in (int, float) and
            math.isfinite(meters["train_cpu_seconds"]) and
            meters["train_cpu_seconds"] >= 0, "frozen old-only computation accounting mismatch")

    output: dict[str, Any] = {
        "outcome": "FROZEN_OLD_PARENT_REPLAY_ONLY",
        "baseline_frozen_after_old_train": True,
        "existing_v1_no_change_is_frozen": False,
        "source_panel_sha256": numeric.digest(panel),
        "training_budget_matched": False,
        "original_source_authenticated": False,
        "future_window_prospective": False,
        "authority_posture": "DENY_ALL",
        "ndu_selection_authorized": False,
        "production_admission": "BLOCKED",
    }
    if continued is not None:
        audit = numeric.validate(panel, continued)  # independent 4-arm FP32 replay
        require(audit["outcome"] == "NUMERIC_REPLAY_ONLY", "old comparator not independently replayed")
        existing = continued["results"][0]
        require(existing["arm"] == "no_change" and existing["split_proposed"] is False
                and existing["meters"]["optimizer_steps"] > steps
                and existing["meters"]["sample_exposures"] > steps * old_count,
                "v1 no_change must represent continued training, not frozen baseline")
        output["descriptive_accuracy_delta_continued_minus_frozen"] = {
            part: round(existing["evaluation"][part]["accuracy"] -
                        frozen["evaluation"][part]["accuracy"], 7)
            for part in PARTITIONS
        }
    return output


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--panel", type=Path, required=True)
    parser.add_argument("--frozen", type=Path, required=True)
    parser.add_argument("--continued", type=Path)
    args = parser.parse_args(argv)
    try:
        panel = numeric.load(args.panel)
        frozen = numeric.load(args.frozen)
        continued = numeric.load(args.continued) if args.continued else None
        print(json.dumps(validate(panel, frozen, continued), sort_keys=True, allow_nan=False))
        return 0
    except (numeric.AuditError, KeyError, IndexError, TypeError, OSError,
            ValueError, OverflowError) as exc:
        print(f"BLOCKED: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
