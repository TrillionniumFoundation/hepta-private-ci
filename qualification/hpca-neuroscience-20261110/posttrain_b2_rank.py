#!/usr/bin/env python3
"""Read-only rank diagnostic for the 540 retained, operator-scored B2 forwards.

This is NOT an independent evaluator, training, threshold fit, or adoption gate.
The original result bytes are SHA-256 pinned by posttrain_b2_reaudit.
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

from posttrain_b2_reaudit import (
    EXPECTED_FAMILIES, MANIFEST_SHA256, RESULT_SHA256, audit, load_original,
)


def rank_counts(rows: list[dict]) -> dict:
    """Mann-Whitney ROC AUC from ALL positive/negative pairs; ties score 1/2.

    Integer twice-wins keeps small task families exact and avoids any
    data-dependent threshold selection on the operator test set.
    """
    yes = [row["p_yes"] for row in rows if row["truth"] == "yes"]
    no = [row["p_yes"] for row in rows if row["truth"] == "no"]
    if len(yes) != len(no) or not yes:
        raise ValueError("unbalanced or empty class roster")
    if any(type(p) not in (int, float) or not math.isfinite(p) or
           not 0 < p < 1 for p in yes + no):
        raise ValueError("invalid probability")
    twice_wins = sum(2 * (positive > negative) + (positive == negative)
                     for positive in yes for negative in no)
    pairs = len(yes) * len(no)
    return {
        "yes": len(yes), "no": len(no),
        "twice_wins": twice_wins, "total_pairs": pairs,
        "auc": twice_wins / (2 * pairs),
        "mean_p_yes_true_yes": sum(yes) / len(yes),
        "mean_p_yes_true_no": sum(no) / len(no),
        "max_p_yes": max(yes + no),
    }


def calculate(manifest: dict, original: dict) -> dict:
    """Require the original frozen evaluator roster and arithmetic first."""
    audit(manifest, original)
    runs = []
    for run in original["runs"]:
        rows = run["scores"]["rows"]
        families = {
            family: rank_counts([row for row in rows if row["family"] == family])
            for family in sorted(EXPECTED_FAMILIES)
        }
        if any(v["yes"] != 6 or v["no"] != 6 for v in families.values()):
            raise ValueError("family-level class roster changed")
        all_tasks = rank_counts(rows)
        if all_tasks["yes"] != 30 or all_tasks["no"] != 30:
            raise ValueError("pooled task roster changed")
        runs.append({
            "arm": run["arm"], "seed": run["seed"],
            "pooled": all_tasks, "families": families,
        })
    return {
        "schema": "hpca.b2.retained.rank-diagnostic.v1",
        "authority": "DENY_ALL",
        "qualification": "HOLD_NO_GO",
        "independent_evaluator": False,
        "original_result_sha256": RESULT_SHA256,
        "original_manifest_sha256": MANIFEST_SHA256,
        "model_inference_reexecuted": False,
        "runs": runs,
        "interpretation": (
            "In-sample, operator-constructed B2 threshold-free ranking diagnostic;"
            " no efficacy, external ground truth, calibration, or deployment claim."
        ),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", type=Path, default=Path(__file__).parent)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    manifest, original = load_original(args.directory)
    result = calculate(manifest, original)
    encoded = json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + "\n"
    if args.output is not None:
        args.output.write_text(encoded, encoding="utf-8")
    else:
        print(encoded, end="")


if __name__ == "__main__":
    main()
