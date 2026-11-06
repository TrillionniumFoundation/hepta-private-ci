"""Research-only pairwise-source Head fitting, separate from the six policy arms.

No Reader calls or evaluation labels. Positive documents are weak native-source
support, while all other candidate windows are WEAK distractors, never reviewed
contradictions. This alternative optimizes a positive-versus-negative ranking
margin and never trains the null/abstention output. It is NOT production.
"""

import math
import time

import torch

from stem_cell import MAX_ROOTS, MAX_SEEN, sha256


@torch.enable_grad()
def fit_pairwise_shadow(
    head,
    rows,
    cut,
    *,
    revoked,
    steps=128,
    lr=0.03,
    margin=1.0,
    pair_ceiling=1000000,
):
    """SGD on the hardest labelled-positive against hardest weak-negative.

    The same frozen Encoder features and registered TRAIN Supervisions are
    used by original Heads. No target is read from select/test/transfer.
    Optimizer has no momentum, so exported Head weights plus step counters
    suffice to resume; the objective identity is retained in a separate receipt.
    """
    if (
        torch.is_inference_mode_enabled()
        or head.kind not in ("linear", "gated")
        or head.quarantined
        or not isinstance(rows, (tuple, list))
        or not 1 <= len(rows) <= 256
        or type(steps) is not int
        or not 1 <= steps <= 2048
        or type(pair_ceiling) is not int
        or not 1 <= pair_ceiling <= 10000000
        or type(lr) not in (int, float)
        or not math.isfinite(lr)
        or not 0 < lr <= 0.1
        or type(margin) not in (int, float)
        or not math.isfinite(margin)
        or not 0 <= margin <= 8
        or not isinstance(revoked, set)
        or not cut.admission_digest
        or head.roots.intersection(revoked | cut.forbidden_roots)
    ):
        raise ValueError("unavailable or invalid pairwise shadow TRAIN session")

    seen, all_roots, eligible, omitted = set(), set(head.roots), [], []
    for row in rows:
        f, positives = row.features, row.positive_indices
        f.validate(head.dimension)
        n = len(f.candidate_ids)
        if (
            f.encoder_identity != head.encoder_identity
            or not f.pool_digest
            or f.question_id in seen
            or f.question_id not in cut.question_ids
            or f.family not in cut.families
            or not f.roots.issubset(cut.allowed_roots)
            or f.roots.intersection(revoked | cut.forbidden_roots)
            or not isinstance(positives, (tuple, list))
            or len(set(positives)) != len(positives)
            or any(type(i) is not int or not 0 <= i < n for i in positives)
        ):
            raise ValueError(
                "unregistered, withdrawn or misbound weak TRAIN supervision"
            )
        seen.add(f.question_id)
        all_roots.update(f.roots)
        if 0 < len(positives) < n:
            eligible.append(row)
        else:
            omitted.append(f.question_id)

    if not eligible or len(head.seen | seen) > MAX_SEEN or len(all_roots) > MAX_ROOTS:
        raise ValueError("no contrastive TRAIN pair or bounded lineage exceeded")

    eligible.sort(key=lambda row: (row.features.family, row.features.question_id))
    before_blob = head.export()
    before = {k: v.detach().clone() for k, v in head.state_dict().items()}
    null_weight = head.null.weight.detach().clone()
    null_bias = head.null.bias.detach().clone()
    prior_steps = head.steps
    optimizer = torch.optim.SGD(head.parameters(), lr=lr, momentum=0.0)
    elapsed_start, losses, consumed = time.perf_counter(), [], 0
    try:
        for i in range(steps):
            row = eligible[(prior_steps + i) % len(eligible)]
            f = row.features
            count = len(f.candidate_ids)
            if head.pair_evaluations + count > pair_ceiling:
                break
            positive = tuple(row.positive_indices)
            negative = tuple(j for j in range(count) if j not in positive)
            optimizer.zero_grad(set_to_none=True)
            logits = head(f)[:-1]  # CRITICAL: reject null-only loss improvement.
            good = torch.max(logits[list(positive)])
            wrong = torch.max(logits[list(negative)])
            loss = torch.nn.functional.softplus(margin + wrong - good)
            if not torch.isfinite(loss):
                raise ValueError("nonfinite margin learning objective")
            loss.backward()
            torch.nn.utils.clip_grad_norm_(
                head.parameters(), 1.0, error_if_nonfinite=True
            )
            optimizer.step()
            if any(not torch.isfinite(v).all() for v in head.state_dict().values()):
                raise ValueError("nonfinite pairwise Head tensor")
            head.steps += 1
            head.pair_evaluations += count
            head.seen.add(f.question_id)
            head.roots.update(f.roots)
            consumed += 1
            losses.append(float(loss.detach()))
        if not consumed:
            raise ValueError("no pairwise Head update fits remaining budget")
        if not torch.equal(head.null.weight, null_weight) or not torch.equal(
            head.null.bias, null_bias
        ):
            raise ValueError("pairwise Head optimization mutated null output")
    except Exception:
        head.quarantined = True
        raise

    after_blob = head.export()
    tensor_delta = sum(
        float((v.detach() - before[k]).square().sum())
        for k, v in head.state_dict().items()
    )
    return dict(
        schema="hepta.stem-pairwise-shadow-fit.v1",
        objective="hardest-positive-vs-hardest-weak-negative-softplus-margin",
        strictly_train_source_only=True,
        null_weights_unchanged=True,
        original_six_arms_unchanged=True,
        observed_original_reader_calls=0,
        checkpoint_pre_sha256=sha256(before_blob),
        checkpoint_post_sha256=sha256(after_blob),
        requested_steps=steps,
        consumed_steps=consumed,
        prior_cumulative_steps=prior_steps,
        cumulative_steps=head.steps,
        cumulative_pair_evaluations=head.pair_evaluations,
        admitted_training_rows=len(rows),
        distinct_eligible_contrastive_questions=len(eligible),
        pair_ineligible_weak_label_questions=len(omitted),
        pair_ineligible_question_ids=sorted(omitted),
        lr=lr,
        target_margin=margin,
        first_loss=losses[0],
        last_loss=losses[-1],
        tensor_delta_squared_norm=tensor_delta,
        wall_seconds=time.perf_counter() - elapsed_start,
        weak_distractors_not_verified_hard_negatives=True,
        heldout_annotations_seen=False,
        actual_heldout_task_gain_established=False,
        semantic_citation_precision=None,
        production_accepted=False,
    )
