"""Label-free, matched-policy score geometry for the six-arm stem experiment.

This module does not train, answer questions, change the allowed evidence pool,
choose calibration offsets or read gold annotations. The actual top-1 decision
must be computed by the experiment's existing, frozen choose() implementation.
"""

import math
import statistics

from native import digest


def _rank(scores, candidate_ids):
    return sorted(
        range(len(candidate_ids)),
        key=lambda i: (-scores[i], candidate_ids[i]),
    )


def inspect_selection(frozen_scores, head_scores, candidate_ids, selected):
    """Describe score magnitudes and ranking opportunity without targets."""
    n = len(candidate_ids)
    if (
        type(n) is not int or not 0 <= n <= 64
        or not isinstance(candidate_ids, (tuple, list))
        or len(set(candidate_ids)) != n
        or any(not isinstance(x, str) or not x for x in candidate_ids)
        or len(frozen_scores) != n
        or len(head_scores) != n
        or any(
            type(x) not in (float, int) or not math.isfinite(x)
            for x in (*frozen_scores, *head_scores)
        )
    ):
        raise ValueError("invalid matched score geometry")
    native, adapted = _rank(frozen_scores, candidate_ids), _rank(
        head_scores, candidate_ids
    )
    original_winner = native[0] if native else None
    learned_winner = adapted[0] if adapted else None
    if selected != learned_winner:
        raise ValueError("recorded policy selection differs from Head ranking")
    baseline_gap = (
        frozen_scores[native[0]] - frozen_scores[native[1]]
        if n > 1 else None
    )
    learned_gap = (
        head_scores[adapted[0]] - head_scores[adapted[1]]
        if n > 1 else None
    )
    residual = [after - before for before, after in zip(
        frozen_scores, head_scores, strict=True
    )]
    return dict(
        schema="hepta.stem-selection-geometry.v1",
        candidate_count=n,
        has_ranking_competition=n >= 2,
        forced_top1=n == 1,
        empty_pool=n == 0,
        baseline_top_id=(
            candidate_ids[original_winner] if original_winner is not None else None
        ),
        learned_top_id=(
            candidate_ids[learned_winner] if learned_winner is not None else None
        ),
        selected_index=selected,
        changed_selected_candidate=original_winner != learned_winner,
        frozen_top1_gap=baseline_gap,
        learned_top1_gap=learned_gap,
        max_abs_score_delta=max(map(abs, residual), default=0.0),
        mean_abs_score_delta=(
            math.fsum(map(abs, residual)) / n if n else 0.0
        ),
        # The absolute gap and residual are units of the same actual model score.
        # They are not probabilities or calibrated confidence.
        gap_exceeds_twice_max_residual=(
            baseline_gap > 2 * max(map(abs, residual), default=0.0)
            if baseline_gap is not None else None
        ),
        raw_scores_sha256=digest((tuple(candidate_ids), frozen_scores, head_scores)),
        evidence_entailment_evaluated=False,
        no_answer_policy_calibrated=False,
        label_free=True,
    )


def summarize_geometry(attempts):
    """Include failed-generation rows if selection already happened."""
    from collections import defaultdict

    grouped = defaultdict(list)
    for row in attempts:
        if "selection_geometry" in row:
            grouped[(row["stage"], row["phase"], row["arm"])].append(
                row["selection_geometry"]
            )
    report = {}
    for key, rows in sorted(grouped.items()):
        changeable = [r for r in rows if r["has_ranking_competition"]]
        changed = sum(r["changed_selected_candidate"] for r in rows)
        report["/".join(map(str, key))] = dict(
            observed_pre_reader_decisions=len(rows),
            empty_pools=sum(r["empty_pool"] for r in rows),
            single_candidate_pools=sum(r["forced_top1"] for r in rows),
            competing_pools=len(changeable),
            changed_top1_count=changed,
            nonflipped_dominated_margins=sum(
                r["gap_exceeds_twice_max_residual"] is True for r in changeable
            ),
            median_max_abs_score_delta=(
                statistics.median(r["max_abs_score_delta"] for r in rows)
                if rows else None
            ),
            verified_new_correct_evidence_gain=False,
            semantic_citation_precision=None,
        )
    return report
