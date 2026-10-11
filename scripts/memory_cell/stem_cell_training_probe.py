"""Native weak-source learning diagnostics, restricted to the admitted TRAIN cut.

The original positive source metadata is not independently adjudicated window
entailment. Loss improvement on training examples cannot qualify held-out QA.
No frozen retrieval policy, Reader, or production writer is changed here.
"""

from collections import defaultdict
import math


def _logsumexp(values):
    if not values:
        raise ValueError("empty training logit set")
    high = max(values)
    return high + math.log(math.fsum(math.exp(v - high) for v in values))


def train_probe(frozen_logits, learned_logits, positive_indices):
    """Return the exact multi-positive-vs-null training objective by snapshot."""
    if (
        len(frozen_logits) != len(learned_logits)
        or not 1 <= len(frozen_logits) <= 65
        or any(type(x) not in (float, int) or not math.isfinite(x)
               for x in (*frozen_logits, *learned_logits))
        or len(set(positive_indices)) != len(positive_indices)
        or any(type(i) is not int or not 0 <= i < len(frozen_logits) - 1
               for i in positive_indices)
    ):
        raise ValueError("training probe must use bounded admitted logits and labels")
    count = len(frozen_logits) - 1
    positives = tuple(positive_indices) or (count,)
    def loss(scores):
        return _logsumexp(scores) - _logsumexp(
            [scores[i] for i in positives]
        )

    # The null class is always one trainable alternative, even under
    # evaluation's separate forced-top1 policy.
    competitors = [i for i in range(count + 1) if i not in positives]
    def margin(scores):
        return (max(scores[i] for i in positives)
                - max(scores[i] for i in competitors)) if competitors else None

    before, after = loss(frozen_logits), loss(learned_logits)
    return dict(
        schema="hepta.stem-weak-training-probe.v1",
        candidate_count=count,
        supported_candidate_count=len(positive_indices),
        annotated_unanswerable=(len(positive_indices) == 0),
        has_competing_class=bool(competitors),
        frozen_weak_label_loss=before,
        learned_weak_label_loss=after,
        loss_delta=after - before,
        weak_label_loss_improved=after < before,
        native_margin=margin(frozen_logits),
        learned_margin=margin(learned_logits),
        weak_source_support_not_entailment=True,
        objective_matches_head_fit=True,
        usable_as_independent_generalization_evidence=False,
        production_accepted=False,
    )


def summarize_train_probes(records):
    by_arm = defaultdict(list)
    failures = defaultdict(int)
    for record in records:
        key = (record["stage"], record["arm"], record["cell"])
        if record["status"] == "succeeded":
            by_arm[key].append(record["probe"])
        elif record["status"] == "failed":
            failures[key] += 1
        else:
            raise ValueError("unknown weak training probe outcome")
    keys = sorted(set(by_arm) | set(failures))
    result = {}
    for key in keys:
        rows = by_arm[key]
        result["/".join(map(str, key))] = dict(
            attempted=len(rows) + failures[key],
            probe_succeeded=len(rows),
            probe_failed=failures[key],
            null_labeled_count=sum(x["annotated_unanswerable"] for x in rows),
            native_loss_mean=(
                math.fsum(x["frozen_weak_label_loss"] for x in rows) / len(rows)
                if rows else None
            ),
            learned_loss_mean=(
                math.fsum(x["learned_weak_label_loss"] for x in rows) / len(rows)
                if rows else None
            ),
            improved_weak_training_examples=sum(x["weak_label_loss_improved"]
                                                for x in rows),
            generalization_claim=False,
            independently_verifiable_semantic_support=False,
        )
    return result
