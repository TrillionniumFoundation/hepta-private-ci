#!/usr/bin/env python3
"""Descriptive same-family vs cross-family AUC decomposition of retained B2.

The original CPU score bytes are immutable and validated by the upstream
source-pinned rank audit. This does not execute any model or independent B.
"""
from __future__ import annotations
import argparse
import json
from pathlib import Path
from posttrain_b2_rank import calculate as rank_calculate
from posttrain_b2_reaudit import EXPECTED_FAMILIES, load_original

def decompose_retained_rank(rank_report: dict) -> dict:
    """Partition exactly 900 YES/NO pairs using upstream integer twice-wins."""
    if (rank_report.get("authority"), rank_report.get("qualification")) != ("DENY_ALL", "HOLD_NO_GO"):
        raise ValueError("authority/qualification drift")
    if (rank_report.get("independent_evaluator") is not False
            or rank_report.get("model_inference_reexecuted") is not False):
        raise ValueError("unqualified execution claim")
    runs = rank_report["runs"]
    if len(runs) != 9:
        raise ValueError("nine-run roster drift")
    findings = []
    for run in runs:
        families, pooled = run["families"], run["pooled"]
        if set(families) != EXPECTED_FAMILIES:
            raise ValueError("family roster drift")
        within_pairs = sum(families[f]["total_pairs"] for f in EXPECTED_FAMILIES)
        within_twice = sum(families[f]["twice_wins"] for f in EXPECTED_FAMILIES)
        total_pairs, total_twice = pooled["total_pairs"], pooled["twice_wins"]
        if (within_pairs, total_pairs) != (180, 900):
            raise ValueError("pair-count drift")
        if not 0 <= within_twice <= 2 * within_pairs:
            raise ValueError("invalid within-family wins")
        cross_pairs, cross_twice = total_pairs - within_pairs, total_twice - within_twice
        if cross_pairs != 720 or not 0 <= cross_twice <= 2 * cross_pairs:
            raise ValueError("invalid cross-family wins")
        findings.append({
            "arm": run["arm"], "seed": run["seed"],
            "pooled_auc": total_twice / (2 * total_pairs),
            "within_family": {"pairs": within_pairs, "twice_wins": within_twice,
                              "auc": within_twice / (2 * within_pairs)},
            "cross_family": {"pairs": cross_pairs, "twice_wins": cross_twice,
                             "auc": cross_twice / (2 * cross_pairs)},
        })
    return {
        "schema": "hpca.b2.retained.family-decomposition.v1",
        "authority": "DENY_ALL", "qualification": "HOLD_NO_GO",
        "independent_evaluator": False, "model_inference_reexecuted": False,
        "original_result_sha256": rank_report["original_result_sha256"],
        "original_manifest_sha256": rank_report["original_manifest_sha256"],
        "interpretation": (
            "Descriptive within-family and cross-family rank-pair partition on "
            "the same retained operator-built 60 tasks; nine reused task "
            "rosters are not nine independent evaluation cohorts. No efficacy, "
            "prospective accuracy, statistical significance or production claim."
        ),
        "runs": findings,
    }

def calculate(manifest: dict, original: dict) -> dict:
    return decompose_retained_rank(rank_calculate(manifest, original))

def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", type=Path, default=Path(__file__).parent)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    manifest, original = load_original(args.directory)
    encoded = json.dumps(calculate(manifest, original), indent=2,
                         sort_keys=True, allow_nan=False) + "\n"
    if args.output is not None:
        args.output.write_text(encoded, encoding="utf-8")
    else:
        print(encoded, end="")

if __name__ == "__main__":
    main()
