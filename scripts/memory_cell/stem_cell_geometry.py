"""Bounded label-free rank geometry with separate Encoder and Head effects.

The original frozen Encoder, post-adaptation Encoder, and saved Head must score
the same ordered candidate pool. This module never selects evidence or trains.
Rank changes are not semantic correctness, citation entailment or admission.
"""

import math
import statistics
from collections import defaultdict

from native import digest
from stem_rank_scale import minimum_residual_flip_scale


def _rank(scores, ids):
    return sorted(range(len(ids)), key=lambda i: (-scores[i], ids[i]))


def _gap(scores, order):
    return scores[order[0]] - scores[order[1]] if len(order) > 1 else None


def _max_difference(before, after):
    return max((abs(y - x) for x, y in zip(before, after, strict=True)), default=0.0)


def inspect_selection(
    encoder_scores,
    head_scores,
    candidate_ids,
    selected,
    *,
    original_frozen_scores=None,
    encoder_adapted=False,
):
    """Observe actual forced-top1 rank changes without labels or policy tuning.

    The first vector belongs to the candidate Encoder used by this arm,
    which for LoRA is NOT the original frozen Encoder. The optional third
    original-score vector is mandatory for an adapted Encoder.
    """
    original = (
        encoder_scores if original_frozen_scores is None else original_frozen_scores
    )
    if (
        not isinstance(candidate_ids, (list, tuple))
        or type(encoder_adapted) is not bool
        or not 0 <= len(candidate_ids) <= 64
        or any(not isinstance(i, str) or not i for i in candidate_ids)
        or len(set(candidate_ids)) != len(candidate_ids)
        or len(original) != len(candidate_ids)
        or len(encoder_scores) != len(candidate_ids)
        or len(head_scores) != len(candidate_ids)
        or any(
            type(x) not in (int, float) or not math.isfinite(x)
            for x in (*original, *encoder_scores, *head_scores)
        )
        or (encoder_adapted and original_frozen_scores is None)
        or (not encoder_adapted and list(original) != list(encoder_scores))
    ):
        raise ValueError("invalid or unbound three-way score geometry")

    frozen_rank = _rank(original, candidate_ids)
    encoder_rank = _rank(encoder_scores, candidate_ids)
    head_rank = _rank(head_scores, candidate_ids)
    frozen_winner = frozen_rank[0] if frozen_rank else None
    encoder_winner = encoder_rank[0] if encoder_rank else None
    head_winner = head_rank[0] if head_rank else None
    if selected != head_winner:
        raise ValueError("recorded policy selection differs from Head ranking")

    delta_encoder = _max_difference(original, encoder_scores)
    delta_head = _max_difference(encoder_scores, head_scores)
    delta_joint = _max_difference(original, head_scores)
    frozen_gap = _gap(original, frozen_rank)
    # No task labels or calibrating optimization enter these diagnostics.
    encoder_scale = minimum_residual_flip_scale(original, encoder_scores, candidate_ids)
    head_scale = minimum_residual_flip_scale(encoder_scores, head_scores, candidate_ids)
    joint_scale = minimum_residual_flip_scale(original, head_scores, candidate_ids)
    return dict(
        schema="hepta.stem-selection-geometry.v2",
        candidate_count=len(candidate_ids),
        has_ranking_competition=len(candidate_ids) >= 2,
        forced_top1=len(candidate_ids) == 1,
        empty_pool=not candidate_ids,
        encoder_adapted=encoder_adapted,
        baseline_top_id=(
            candidate_ids[frozen_winner] if frozen_winner is not None else None
        ),
        encoder_only_top_id=(
            candidate_ids[encoder_winner] if encoder_winner is not None else None
        ),
        learned_top_id=(
            candidate_ids[head_winner] if head_winner is not None else None
        ),
        selected_index=selected,
        encoder_only_changed_selected_candidate=(encoder_winner != frozen_winner),
        head_changed_selected_candidate=(head_winner != encoder_winner),
        changed_selected_candidate=head_winner != frozen_winner,
        encoder_only_flip_scale_infimum=encoder_scale,
        head_conditional_flip_scale_infimum=head_scale,
        joint_flip_scale_infimum=joint_scale,
        residual_scaling_is_not_a_validated_policy=True,
        frozen_top1_gap=frozen_gap,
        encoder_only_top1_gap=_gap(encoder_scores, encoder_rank),
        learned_top1_gap=_gap(head_scores, head_rank),
        encoder_only_max_abs_score_delta=delta_encoder,
        head_conditional_max_abs_score_delta=delta_head,
        max_abs_score_delta=delta_joint,
        mean_abs_score_delta=(
            math.fsum(abs(y - x) for x, y in zip(original, head_scores, strict=True))
            / len(candidate_ids)
            if candidate_ids
            else 0.0
        ),
        # A gap bound is a sufficient condition, not a calibrated confidence.
        gap_exceeds_twice_max_residual=(
            frozen_gap > 2 * delta_joint if frozen_gap is not None else None
        ),
        raw_scores_sha256=digest(
            (
                tuple(candidate_ids),
                original,
                encoder_scores,
                head_scores,
            )
        ),
        evidence_entailment_evaluated=False,
        no_answer_policy_calibrated=False,
        label_free=True,
    )


def summarize_geometry(attempts):
    """Failed Reader calls retain already observed rankings; no imputation."""
    grouped = defaultdict(list)
    for row in attempts:
        if "selection_geometry" in row:
            grouped[(row["stage"], row["phase"], row["arm"])].append(
                row["selection_geometry"]
            )
    report = {}
    for key, rows in sorted(grouped.items()):
        rankable = [r for r in rows if r["has_ranking_competition"]]
        report["/".join(map(str, key))] = dict(
            observed_pre_reader_decisions=len(rows),
            empty_pools=sum(r["empty_pool"] for r in rows),
            single_candidate_pools=sum(r["forced_top1"] for r in rows),
            competing_pools=len(rankable),
            changed_top1_count=sum(r["changed_selected_candidate"] for r in rows),
            encoder_only_changed_top1_count=sum(
                r["encoder_only_changed_selected_candidate"] for r in rows
            ),
            head_conditional_changed_top1_count=sum(
                r["head_changed_selected_candidate"] for r in rows
            ),
            # Two opposing changes can cancel; do not sum them as net gain.
            cancelled_rank_changes=sum(
                r["encoder_only_changed_selected_candidate"]
                and r["head_changed_selected_candidate"]
                and not r["changed_selected_candidate"]
                for r in rows
            ),
            nonflipped_dominated_margins=sum(
                r["gap_exceeds_twice_max_residual"] is True for r in rankable
            ),
            joint_direction_can_flip_count=sum(
                r["joint_flip_scale_infimum"] is not None for r in rankable
            ),
            joint_direction_cannot_flip_count=sum(
                r["joint_flip_scale_infimum"] is None for r in rankable
            ),
            joint_requires_scale_above_one_count=sum(
                r["joint_flip_scale_infimum"] is not None
                and r["joint_flip_scale_infimum"] > 1
                for r in rankable
            ),
            median_max_abs_score_delta=(
                statistics.median(r["max_abs_score_delta"] for r in rows)
                if rows
                else None
            ),
            median_encoder_only_max_abs_score_delta=(
                statistics.median(r["encoder_only_max_abs_score_delta"] for r in rows)
                if rows
                else None
            ),
            median_head_conditional_max_abs_score_delta=(
                statistics.median(
                    r["head_conditional_max_abs_score_delta"] for r in rows
                )
                if rows
                else None
            ),
            verified_new_correct_evidence_gain=False,
            semantic_citation_precision=None,
        )
    return report
