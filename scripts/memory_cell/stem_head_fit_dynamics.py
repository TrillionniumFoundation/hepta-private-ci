"""Post-update TRAIN-cut Head loss geometry, not held-out generalization.

Compare the SAME admitted Supervision rows and frozen Encoder Features
immediately before versus after one persistent Head fit. No candidate retrieval,
Reader call, label expansion, or policy-selection decision is performed here.
"""

import math
import re
from native import digest

ARMS = frozenset((
    "prototype", "linear", "gated", "lineage_lora_gated", "independent_lora_gated",
))
STAGES = (16, 32, 48)
CELLS = ("general", "temporal")


def _lse(x):
    top = max(x)
    return top + math.log(math.fsum(math.exp(v - top) for v in x))


def compare_train_head_before_after(
    rows, before_logits, after_logits, *, admitted_ids,
    stage, arm, cell, previous_head_sha256, updated_head_sha256,
):
    """An observable within-Head training-set probe on exactly matched rows.

    Training labels may only be the supplied, previously admitted Supervisions.
    Prototype accumulation is NOT cross-entropy optimization; the diagnostic
    loss is therefore reported but explicitly not an actual fit objective.
    """
    if (
        arm not in ARMS or stage not in STAGES or cell not in CELLS
        or not isinstance(admitted_ids, (frozenset, set))
        or not 1 <= len(rows) <= 256
        or len(rows) != len(before_logits) or len(rows) != len(after_logits)
        or not isinstance(previous_head_sha256, str)
        or re.fullmatch(r"[a-f0-9]{64}", previous_head_sha256) is None
        or not isinstance(updated_head_sha256, str)
        or re.fullmatch(r"[a-f0-9]{64}", updated_head_sha256) is None
    ):
        raise ValueError("unbound or incomplete original Head training checkpoint")
    seen, examined = set(), []
    for supervision, original, learned in zip(rows, before_logits, after_logits, strict=True):
        features = supervision.features
        qid = features.question_id
        candidate_ids = features.candidate_ids
        positives = supervision.positive_indices
        n = len(candidate_ids)
        if (
            not isinstance(qid, str) or not qid or qid not in admitted_ids
            or qid in seen or not isinstance(features.family, str) or not features.family
            or not isinstance(candidate_ids, (tuple, list)) or not 0 <= n <= 64
            or len(set(candidate_ids)) != n
            or not isinstance(positives, (tuple, list))
            or len(set(positives)) != len(positives)
            or any(type(i) is not int or not 0 <= i < n for i in positives)
            or len(original) != n + 1 or len(learned) != n + 1
            or any(type(v) not in (float, int) or not math.isfinite(v)
                   for v in (*original, *learned))
        ):
            raise ValueError("unadmitted or misaligned before/after Head question")
        seen.add(qid)
        support = tuple(positives) if positives else (n,)
        loss_before = _lse(original) - _lse([original[i] for i in support])
        loss_after = _lse(learned) - _lse([learned[i] for i in support])
        def choose(scores):
            return min(range(n), key=lambda i: (-scores[i], candidate_ids[i])) if n else None
        old, new = choose(original), choose(learned)
        examined.append(dict(
            question_id=qid, source_family=features.family,
            feature_identity_sha256=features.seal(),
            candidate_count=n, weak_positive_candidate_count=len(positives),
            annotated_null=not positives, original_weak_loss=loss_before,
            updated_weak_loss=loss_after, loss_delta=loss_after-loss_before,
            improved_on_admitted_training_label=loss_after < loss_before,
            original_top1_index=old, updated_top1_index=new,
            selected_source_changed=old != new,
        ))
    pre = math.fsum(q["original_weak_loss"] for q in examined) / len(examined)
    post = math.fsum(q["updated_weak_loss"] for q in examined) / len(examined)
    return dict(
        schema="hepta.stem-head-within-train-fit.v1",
        checkpoint=stage, arm=arm, cell=cell,
        previous_head_sha256=previous_head_sha256,
        updated_head_sha256=updated_head_sha256,
        admitted_training_ids_digest=digest(sorted(admitted_ids)),
        matched_training_rows=len(examined),
        positive_negative_eligible_rows=sum(
            0 < x["weak_positive_candidate_count"] < x["candidate_count"]
            for x in examined
        ),
        annotated_null_rows=sum(x["annotated_null"] for x in examined),
        mean_weak_loss_before=pre, mean_weak_loss_after=post,
        mean_weak_loss_delta=post-pre,
        improved_admitted_rows=sum(x["improved_on_admitted_training_label"] for x in examined),
        changed_train_top1_rows=sum(x["selected_source_changed"] for x in examined),
        objective_matches_actual_fit=arm != "prototype",
        trained_model_was_frozen_during_observation=True,
        same_feature_rows_before_and_after=True,
        heldout_annotations_consulted=False,
        independent_generalization_established=False,
        semantic_citation_precision=None,
        production_accepted=False,
        rows=examined,
    )
