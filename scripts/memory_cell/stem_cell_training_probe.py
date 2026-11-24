"""Weak source-support diagnostics, without conflating SGD and prototype fitting.

Read-only at each frozen checkpoint, restricted to previously admitted train
annotations. A lower *cross-sectional* probe loss relative to frozen native
logits is NOT a measured within-Head learning curve or a held-out task gain.
"""

from collections import defaultdict
import math


FIT_STRATEGIES = {
    "frozen_rerank": "frozen",
    "prototype": "prototype",
    "linear": "sgd",
    "gated": "sgd",
    "lineage_lora_gated": "sgd",
    "independent_lora_gated": "sgd",
}


def _logsumexp(values):
    if not values:
        raise ValueError("empty weak-label logit set")
    high = max(values)
    return high + math.log(math.fsum(math.exp(v - high) for v in values))


def train_probe(
    encoder_logits,
    checkpoint_logits,
    positive_indices,
    *,
    fit_strategy,
    original_frozen_logits=None,
    encoder_adapted=False,
):
    """Three-way weak-label probe on a single admitted TRAIN candidate pool.

    Native frozen versus adapted Encoder versus adapted Encoder plus Head.
    This is NOT a before/after trajectory for the same Head checkpoint.
    """
    original = (
        encoder_logits if original_frozen_logits is None else original_frozen_logits
    )
    if (
        fit_strategy not in ("sgd", "prototype", "frozen")
        or type(encoder_adapted) is not bool
        or not 1 <= len(encoder_logits) <= 65
        or len(original) != len(encoder_logits)
        or len(checkpoint_logits) != len(encoder_logits)
        or any(
            type(v) not in (int, float) or not math.isfinite(v)
            for v in (*original, *encoder_logits, *checkpoint_logits)
        )
        or len(set(positive_indices)) != len(positive_indices)
        or any(
            type(n) is not int or not 0 <= n < len(encoder_logits) - 1
            for n in positive_indices
        )
        or (
            encoder_adapted
            and (original_frozen_logits is None or fit_strategy != "sgd")
        )
        or (fit_strategy != "sgd" and encoder_adapted)
        or (not encoder_adapted and list(original) != list(encoder_logits))
        or (
            fit_strategy == "frozen" and list(encoder_logits) != list(checkpoint_logits)
        )
    ):
        raise ValueError("invalid or unbound three-way weak-label probe")
    n = len(encoder_logits) - 1
    positives = tuple(positive_indices) or (n,)

    def loss(scores):
        return _logsumexp(scores) - _logsumexp([scores[k] for k in positives])

    competitors = [k for k in range(n + 1) if k not in positives]

    def margin(scores):
        return (
            max(scores[k] for k in positives) - max(scores[k] for k in competitors)
            if competitors
            else None
        )

    original_loss, encoder_loss, learned_loss = (
        loss(original),
        loss(encoder_logits),
        loss(checkpoint_logits),
    )
    return dict(
        schema="hepta.stem-weak-training-probe.v3",
        fit_strategy=fit_strategy,
        encoder_adapted=encoder_adapted,
        candidate_count=n,
        supported_candidate_count=len(positive_indices),
        annotated_unanswerable=not positive_indices,
        has_competing_class=bool(competitors),
        frozen_weak_label_loss=original_loss,
        encoder_only_weak_label_loss=encoder_loss,
        learned_weak_label_loss=learned_loss,
        loss_delta=learned_loss - original_loss,
        encoder_only_loss_delta=encoder_loss - original_loss,
        head_conditional_loss_delta=learned_loss - encoder_loss,
        weak_label_loss_improved=learned_loss < original_loss,
        head_conditional_loss_improved=learned_loss < encoder_loss,
        native_margin=margin(original),
        encoder_only_margin=margin(encoder_logits),
        learned_margin=margin(checkpoint_logits),
        objective_matches_head_fit=(fit_strategy == "sgd" and n > 0),
        no_candidate_sgd_step=n == 0 and fit_strategy == "sgd",
        fit_updates_measured_here=False,
        previous_checkpoint_scores_measured_here=False,
        independent_test_labels_read=False,
        weak_source_support_not_entailment=True,
        usable_as_independent_generalization_evidence=False,
        production_accepted=False,
    )


def summarize_train_probes(records):
    grouped, failures, seen = defaultdict(list), defaultdict(int), set()
    for record in records:
        arm = record["arm"]
        if arm not in FIT_STRATEGIES or record["cell"] not in ("general", "temporal"):
            raise ValueError("unknown training strategy or Cell route")
        key = (record["stage"], arm, record["cell"])
        identity = (*key, record["question_id"])
        if identity in seen:
            raise ValueError("duplicate training probe per question/head/checkpoint")
        seen.add(identity)
        if record["status"] == "succeeded":
            probe = record["probe"]
            if probe["fit_strategy"] != FIT_STRATEGIES[arm]:
                raise ValueError("training strategy changed across probe receipt")
            grouped[key].append(probe)
        elif record["status"] == "failed":
            failures[key] += 1
        else:
            raise ValueError("unknown weak-training probe status")
    out = {}
    for key in sorted(set(grouped) | set(failures)):
        rows = grouped[key]
        objective = [x for x in rows if x["objective_matches_head_fit"]]
        out["/".join(map(str, key))] = dict(
            attempted=len(rows) + failures[key],
            probe_succeeded=len(rows),
            probe_failed=failures[key],
            fit_strategy=FIT_STRATEGIES[key[1]],
            null_labeled_count=sum(x["annotated_unanswerable"] for x in rows),
            no_candidate_sgd_step=sum(x["no_candidate_sgd_step"] for x in rows),
            native_diagnostic_loss_mean=(
                math.fsum(x["frozen_weak_label_loss"] for x in rows) / len(rows)
                if rows
                else None
            ),
            checkpoint_diagnostic_loss_mean=(
                math.fsum(x["learned_weak_label_loss"] for x in rows) / len(rows)
                if rows
                else None
            ),
            encoder_only_diagnostic_loss_mean=(
                math.fsum(x["encoder_only_weak_label_loss"] for x in rows) / len(rows)
                if rows
                else None
            ),
            encoder_adapted_observations=sum(x["encoder_adapted"] for x in rows),
            encoder_only_loss_lower_than_original=sum(
                x["encoder_only_loss_delta"] < 0 for x in rows
            ),
            joint_loss_lower_than_original=sum(
                x["weak_label_loss_improved"] for x in rows
            ),
            head_conditional_loss_lower_than_encoder_only=sum(
                x["head_conditional_loss_improved"] for x in rows
            ),
            objective_aligned_training_examples=len(objective),
            objective_aligned_head_loss_lower_than_encoder_only=sum(
                x["head_conditional_loss_improved"] for x in objective
            ),
            # A within-Head pre/post fit measurement needs a frozen prior state.
            within_head_loss_before_after_measured=False,
            generalization_claim=False,
            independently_verifiable_semantic_support=False,
        )
    return out
