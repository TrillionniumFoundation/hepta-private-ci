"""Fail-closed E1/E2/E3 research decision over published retrospective aggregates.

Pure standard-library, source-only diagnostic. Never a production admission.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

PROFILE = "hepta.amcn.ten-original-family-trained-rank-heads.audit.v1"
ARMS = ("bm25", "untyped_equal_budget", "typed_equal_budget",
        "typed_swapped_negative", "train_label_shuffled_negative")
HELDOUT = ("retrospective_heldout_a", "retrospective_heldout_b")


def assess(report: dict) -> dict:
    if report.get("profile") != PROFILE or report.get("production_accepted") is not False:
        raise ValueError("original research-only profile required")
    splits = report.get("per_split")
    if not isinstance(splits, dict) or not set(HELDOUT) <= set(splits):
        raise ValueError("two original heldout partitions required")
    totals = {arm: {"questions": 0, "hit3": 0, "all3": 0} for arm in ARMS}
    for split in HELDOUT:
        group = splits[split]
        if not isinstance(group, dict) or not set(ARMS) <= set(group):
            raise ValueError("all matched experimental arms required")
        size = None
        for arm in ARMS:
            entry = group[arm]
            if not isinstance(entry, dict) or not all(type(entry.get(key)) is int
                       for key in ("questions", "hit3", "all3")):
                raise ValueError("untrusted arm count")
            n, hit, all_hit = (entry[key] for key in ("questions", "hit3", "all3"))
            if not (n > 0 and 0 <= all_hit <= hit <= n):
                raise ValueError("invalid source evidence census")
            if size is not None and n != size:
                raise ValueError("arm denominator drift")
            size = n
            for key in totals[arm]:
                totals[arm][key] += entry[key]
    n = totals["bm25"]["questions"]
    if n != report.get("heldout_question_count"):
        raise ValueError("missing original heldout questions")
    deltas = report.get("retrospective_heldout_delta")
    for arm, v in totals.items():
        recorded = deltas.get(arm) if isinstance(deltas, dict) else None
        if not isinstance(recorded, dict) or (v["hit3"] - totals["bm25"]["hit3"]
            != recorded.get("hit3_vs_bm25")) or (v["all3"] -
            totals["bm25"]["all3"] != recorded.get("all3_vs_bm25")):
            raise ValueError("retrospective delta drift")
    if report.get("heldout_independent_roots") != 2:
        raise ValueError("historic source family census changed")
    required_negative = ("production_accepted", "superiority_claim",
                         "parametric_task_gain_verified",
                         "does_type_specialization_win_at_equal_head_budget",
                         "official_hf_parity_verified",
                         "strong_rag_equal_total_compute_compared")
    if any(report.get(k) is not False for k in required_negative):
        raise ValueError("unverified original authority asserted")
    if (report.get("independent_future_calendar_windows") != 0 or
        report.get("real_reader_answers_this_trial") != 0 or
        report.get("independent_Reader_semantic_judgment") is not None):
        raise ValueError("historical retrieval mislabeled full Reader evidence")
    matched = totals["typed_equal_budget"]["hit3"] == totals["untyped_equal_budget"]["hit3"]
    swapped = totals["typed_equal_budget"]["hit3"] == totals["typed_swapped_negative"]["hit3"]
    improvement = totals["typed_equal_budget"]["hit3"] - totals["bm25"]["hit3"]
    return {
        "profile": "hepta.amcn.three-axis-original-qualification-denial.v1",
        "original_heldout_questions": n,
        "independent_source_roots": 2,
        "original_bm25_hit3": totals["bm25"]["hit3"],
        "typed_hit3": totals["typed_equal_budget"]["hit3"],
        "untyped_hit3": totals["untyped_equal_budget"]["hit3"],
        "typed_gain_over_bm25_proxy_only": improvement,
        "typed_vs_untyped_tie": matched,
        "typed_vs_wrong_route_tie": swapped,
        "parameter_learning_full_task_win_verified": False,
        "type_specialization_task_win_verified": False,
        "network_incremental_task_win_verified": False,
        "independent_future_windows": 0,
        "automatic_fission_fusion_eligible": False,
        "production_accepted": False,
    }


def main():
    p = argparse.ArgumentParser()
    p.add_argument("original_aggregate", type=Path)
    p.add_argument("output", type=Path)
    args = p.parse_args()
    if args.output.exists() or args.output.is_symlink():
        raise ValueError("never overwrite research denial receipt")
    with args.original_aggregate.open("rb") as stream:
        original = json.load(stream)
    verdict = assess(original)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8") as out:
        json.dump(verdict, out, sort_keys=True, indent=2)
        out.write("\n")
    print(json.dumps(verdict, sort_keys=True))


if __name__ == "__main__":
    main()
