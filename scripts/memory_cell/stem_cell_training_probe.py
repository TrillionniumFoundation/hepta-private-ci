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


def train_probe(frozen_logits, checkpoint_logits, positive_indices, *, fit_strategy):
    """Compare frozen vs saved-checkpoint logits against TRAIN-only weak labels.

    SGD Heads actually optimize this exact multi-positive/null objective when
    a candidate exists. Prototype fitting is a sufficient-statistics update,
    not SGD minimizing this loss. Frozen rerank does not fit at all.
    """
    if (
        fit_strategy not in ("sgd", "prototype", "frozen")
        or len(frozen_logits) != len(checkpoint_logits)
        or not 1 <= len(frozen_logits) <= 65
        or any(type(v) not in (int, float) or not math.isfinite(v)
               for v in (*frozen_logits, *checkpoint_logits))
        or len(set(positive_indices)) != len(positive_indices)
        or any(type(i) is not int or not 0 <= i < len(frozen_logits) - 1
               for i in positive_indices)
        or (fit_strategy == "frozen" and list(frozen_logits) != list(checkpoint_logits))
    ):
        raise ValueError("unbound or invalid saved-checkpoint weak-label probe")
    count = len(frozen_logits) - 1
    support = tuple(positive_indices) or (count,)
    def diagnostic_loss(values):
        return _logsumexp(values) - _logsumexp([values[i] for i in support])

    alternatives = [i for i in range(count + 1) if i not in support]
    def margin(values):
        return (
            max(values[i] for i in support) - max(values[i] for i in alternatives)
            if alternatives else None
        )

    frozen_loss = diagnostic_loss(frozen_logits)
    checkpoint_loss = diagnostic_loss(checkpoint_logits)
    is_fit_objective = fit_strategy == "sgd" and count > 0
    return dict(
        schema="hepta.stem-weak-training-probe.v2",
        fit_strategy=fit_strategy,
        candidate_count=count,
        supported_candidate_count=len(positive_indices),
        annotated_unanswerable=not positive_indices,
        has_competing_class=bool(alternatives),
        frozen_weak_label_loss=frozen_loss,
        learned_weak_label_loss=checkpoint_loss,
        loss_delta=checkpoint_loss - frozen_loss,
        weak_label_loss_improved=checkpoint_loss < frozen_loss,
        native_margin=margin(frozen_logits),
        learned_margin=margin(checkpoint_logits),
        # Distinguish a diagnostic objective from the actual fitting algorithm.
        objective_matches_head_fit=is_fit_objective,
        no_candidate_sgd_step=count == 0 and fit_strategy == "sgd",
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
                if rows else None
            ),
            checkpoint_diagnostic_loss_mean=(
                math.fsum(x["learned_weak_label_loss"] for x in rows) / len(rows)
                if rows else None
            ),
            lower_diagnostic_loss_than_frozen=sum(
                x["weak_label_loss_improved"] for x in rows
            ),
            objective_aligned_training_examples=len(objective),
            objective_aligned_lower_than_frozen=sum(
                x["weak_label_loss_improved"] for x in objective
            ),
            # A within-Head pre/post fit measurement needs a frozen prior state.
            within_head_loss_before_after_measured=False,
            generalization_claim=False,
            independently_verifiable_semantic_support=False,
        )
    return out
