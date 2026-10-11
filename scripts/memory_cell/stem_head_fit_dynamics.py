"""Post-update TRAIN-cut Head loss geometry, not held-out generalization.

Compare the SAME admitted Supervision rows and frozen Encoder Features
immediately before versus after one persistent Head fit. No candidate retrieval,
Reader call, label expansion, or policy-selection decision is performed here.
"""

import math
import re
from native import digest

ARMS = frozenset(
    (
        "prototype",
        "linear",
        "gated",
        "lineage_lora_gated",
        "independent_lora_gated",
    )
)
STAGES = (16, 32, 48)
CELLS = ("general", "temporal")


def _lse(x):
    top = max(x)
    return top + math.log(math.fsum(math.exp(v - top) for v in x))


def compare_train_head_before_after(
    rows,
    before_logits,
    after_logits,
    *,
    admitted_ids,
    stage,
    arm,
    cell,
    previous_head_sha256,
    updated_head_sha256,
):
    """An observable within-Head training-set probe on exactly matched rows.

    Training labels may only be the supplied, previously admitted Supervisions.
    Prototype accumulation is NOT cross-entropy optimization; the diagnostic
    loss is therefore reported but explicitly not an actual fit objective.
    """
    if (
        arm not in ARMS
        or stage not in STAGES
        or cell not in CELLS
        or not isinstance(admitted_ids, (frozenset, set))
        or not 1 <= len(rows) <= 256
        or len(rows) != len(before_logits)
        or len(rows) != len(after_logits)
        or not isinstance(previous_head_sha256, str)
        or re.fullmatch(r"[a-f0-9]{64}", previous_head_sha256) is None
        or not isinstance(updated_head_sha256, str)
        or re.fullmatch(r"[a-f0-9]{64}", updated_head_sha256) is None
    ):
        raise ValueError("unbound or incomplete original Head training checkpoint")
    seen, examined = set(), []
    for supervision, original, learned in zip(
        rows, before_logits, after_logits, strict=True
    ):
        features = supervision.features
        qid = features.question_id
        candidate_ids = features.candidate_ids
        positives = supervision.positive_indices
        n = len(candidate_ids)
        if (
            not isinstance(qid, str)
            or not qid
            or qid not in admitted_ids
            or qid in seen
            or not isinstance(features.family, str)
            or not features.family
            or not isinstance(candidate_ids, (tuple, list))
            or not 0 <= n <= 64
            or len(set(candidate_ids)) != n
            or not isinstance(positives, (tuple, list))
            or len(set(positives)) != len(positives)
            or any(type(i) is not int or not 0 <= i < n for i in positives)
            or len(original) != n + 1
            or len(learned) != n + 1
            or any(
                type(v) not in (float, int) or not math.isfinite(v)
                for v in (*original, *learned)
            )
        ):
            raise ValueError("unadmitted or misaligned before/after Head question")
        seen.add(qid)
        support = tuple(positives) if positives else (n,)
        loss_before = _lse(original) - _lse([original[i] for i in support])
        loss_after = _lse(learned) - _lse([learned[i] for i in support])

        def choose(scores):
            return (
                min(range(n), key=lambda i: (-scores[i], candidate_ids[i]))
                if n
                else None
            )

        if not math.isfinite(loss_before) or not math.isfinite(loss_after):
            raise ValueError("nonfinite matched weak-label loss")
        old, new = choose(original), choose(learned)
        has_positive_negative = 0 < len(positives) < n
        positive = set(positives)

        def weak_top1(scores, winner):
            return winner in positive if positives and winner is not None else None

        def candidate_support_gap(scores):
            if not has_positive_negative:
                return None
            return max(scores[i] for i in positives) - max(
                scores[i] for i in range(n) if i not in positive
            )

        def null_vs_best(scores):
            return scores[-1] - max(scores[:n]) if n else None

        weak_before = weak_top1(original, old)
        weak_after = weak_top1(learned, new)
        margin_before = candidate_support_gap(original)
        margin_after = candidate_support_gap(learned)
        null_before, null_after = null_vs_best(original), null_vs_best(learned)
        margin_delta = margin_after - margin_before if has_positive_negative else None
        null_delta = null_after - null_before if n else None
        if any(
            v is not None and not math.isfinite(v)
            for v in (
                margin_before,
                margin_after,
                margin_delta,
                null_before,
                null_after,
                null_delta,
            )
        ):
            raise ValueError("nonfinite matched source ranking margin")
        examined.append(
            dict(
                question_id=qid,
                source_family=features.family,
                feature_identity_sha256=features.seal(),
                candidate_count=n,
                weak_positive_candidate_count=len(positives),
                annotated_null=not positives,
                original_weak_loss=loss_before,
                updated_weak_loss=loss_after,
                loss_delta=loss_after - loss_before,
                improved_on_admitted_training_label=loss_after < loss_before,
                original_top1_index=old,
                updated_top1_index=new,
                selected_source_changed=old != new,
                weak_positive_top1_before=weak_before,
                weak_positive_top1_after=weak_after,
                native_support_moved_into_top1=(
                    bool(weak_before is False and weak_after is True)
                    if has_positive_negative
                    else None
                ),
                native_support_lost_top1=(
                    bool(weak_before is True and weak_after is False)
                    if has_positive_negative
                    else None
                ),
                positive_negative_candidate_margin_before=margin_before,
                positive_negative_candidate_margin_after=margin_after,
                positive_negative_candidate_margin_delta=margin_delta,
                null_over_best_candidate_before=null_before,
                null_over_best_candidate_after=null_after,
                null_over_best_candidate_delta=null_delta,
            )
        )
    pair_rows = [
        x for x in examined if x["positive_negative_candidate_margin_delta"] is not None
    ]
    margin_deltas = [x["positive_negative_candidate_margin_delta"] for x in pair_rows]
    null_rows = [x for x in examined if x["null_over_best_candidate_delta"] is not None]
    null_deltas = [x["null_over_best_candidate_delta"] for x in null_rows]
    pre = math.fsum(q["original_weak_loss"] for q in examined) / len(examined)
    post = math.fsum(q["updated_weak_loss"] for q in examined) / len(examined)
    return dict(
        schema="hepta.stem-head-within-train-fit.v2",
        checkpoint=stage,
        arm=arm,
        cell=cell,
        previous_head_sha256=previous_head_sha256,
        updated_head_sha256=updated_head_sha256,
        admitted_training_ids_digest=digest(sorted(admitted_ids)),
        matched_training_rows=len(examined),
        positive_negative_eligible_rows=sum(
            0 < x["weak_positive_candidate_count"] < x["candidate_count"]
            for x in examined
        ),
        annotated_null_rows=sum(x["annotated_null"] for x in examined),
        mean_weak_loss_before=pre,
        mean_weak_loss_after=post,
        mean_weak_loss_delta=post - pre,
        improved_admitted_rows=sum(
            x["improved_on_admitted_training_label"] for x in examined
        ),
        changed_train_top1_rows=sum(x["selected_source_changed"] for x in examined),
        pair_supervised_rows_with_support_top1_before=sum(
            x["weak_positive_top1_before"] is True for x in pair_rows
        ),
        pair_supervised_rows_with_support_top1_after=sum(
            x["weak_positive_top1_after"] is True for x in pair_rows
        ),
        weak_source_top1_gains=sum(
            x["native_support_moved_into_top1"] is True for x in pair_rows
        ),
        weak_source_top1_losses=sum(
            x["native_support_lost_top1"] is True for x in pair_rows
        ),
        pair_source_margin_improved_count=sum(d > 0 for d in margin_deltas),
        pair_source_margin_worsened_count=sum(d < 0 for d in margin_deltas),
        mean_positive_over_negative_candidate_margin_delta=(
            math.fsum(margin_deltas) / len(margin_deltas) if margin_deltas else None
        ),
        candidate_null_gap_sample_count=len(null_rows),
        mean_null_over_best_candidate_delta=(
            math.fsum(null_deltas) / len(null_deltas) if null_deltas else None
        ),
        weak_source_top1_measured_on_train_only=True,
        raw_training_loss_not_rank_support_gain=True,
        native_weak_support_not_reviewed_entailment=True,
        objective_matches_actual_fit=arm != "prototype",
        trained_model_was_frozen_during_observation=True,
        same_feature_rows_before_and_after=True,
        heldout_annotations_consulted=False,
        independent_generalization_established=False,
        semantic_citation_precision=None,
        production_accepted=False,
        rows=examined,
    )
