"""Source-only same-scope counterfactual value binding: research control.

All values and entity/relationship identities are derived from admitted original
source facts before a downstream task is opened. This module neither fits the
production reader nor treats a source-derived target as external human review.
"""

import torch
import torch.nn.functional as F

from event_projection import EventProjection
from grounded_protocol import completion_ids
from source_completion_loss import completion_loss

MAX_EXAMPLES = 2048
MAX_DOCUMENTS = 2048


def _value_tokens(tokenizer, value):
    if not isinstance(value, str) or not value or len(value.encode()) > 256:
        raise ValueError("bounded source-derived identifier required")
    ids = tokenizer.encode(value, add_special_tokens=False)
    if not ids or len(ids) > 64 or any(type(i) is not int or i < 0 for i in ids):
        raise ValueError("nonempty finite source value tokens required")
    return tuple(ids)


def source_hard_negatives(examples, documents, tokenizer, *, allowed_roots, revoked):
    """Find a same-entity/different-relation or same-relation/different-entity value.

    No missing/ambiguous source is relabelled as a negative. Equal completion
    token lengths prevent a cheap length cue; the prompt never contains either
    target value. The selected value belongs to a different, admitted source.
    """
    if (
        not 1 <= len(examples) <= MAX_EXAMPLES
        or not 1 <= len(documents) <= MAX_DOCUMENTS
        or len({d.identity for d in documents}) != len(documents)
        or {d.root for d in documents} != set(allowed_roots)
        or set(allowed_roots).intersection(revoked)
    ):
        raise ValueError("bounded, authorized original source population required")
    scopes = {}
    for doc in documents:
        scopes.setdefault(doc.scope, []).append(doc)
    projections = {
        scope: EventProjection(tuple(rows)) for scope, rows in scopes.items()
    }
    rows, identities = [], set()
    for idx, ex in enumerate(examples):
        if (
            not isinstance(ex, dict)
            or not isinstance(ex.get("query"), dict)
            or not isinstance(ex.get("sources"), list)
            or not ex["sources"]
        ):
            raise ValueError("complete source-only training example required")
        q = ex["query"]
        identity, scope = q.get("identity"), q.get("scope")
        if (
            not isinstance(identity, str)
            or not identity
            or identity in identities
            or scope not in projections
        ):
            raise ValueError("unique bound source question required")
        identities.add(identity)
        projection = projections[scope]
        try:
            facts = [projection.facts[source] for source in ex["sources"]]
        except KeyError as error:
            raise ValueError("source example references an absent fact") from error
        if len(
            {(f["entity"], f["attribute"], f["value"]) for f in facts}
        ) != 1 or facts[0]["value"] != ex.get("target"):
            raise ValueError("target is not an unambiguous original source value")
        source_roots = tuple(
            sorted(projection.originals[x].root for x in ex["sources"])
        )
        if not set(source_roots) <= set(allowed_roots):
            raise ValueError("source ancestry differs from admission")
        rows.append(
            dict(
                index=idx,
                identity=identity,
                scope=scope,
                entity=facts[0]["entity"],
                attribute=facts[0]["attribute"],
                target=facts[0]["value"],
                tokens=_value_tokens(tokenizer, facts[0]["value"]),
                roots=source_roots,
            )
        )
    chosen, unmatched = {}, []
    for positive in rows:
        options = []
        # A stale value is a negative only when a CURRENT admitted fact
        # explicitly supersedes it, possibly across several original events.
        # An unlinked newer record is a conflict, never a negative by recency.
        projection = projections[positive["scope"]]
        source_ids = examples[positive["index"]]["sources"]
        frontier = list(source_ids)
        inspected = set()
        while frontier:
            current_id = frontier.pop()
            if current_id in inspected:
                continue
            inspected.add(current_id)
            if len(inspected) > MAX_DOCUMENTS:
                raise ValueError("unbounded source correction ancestry")
            current = projection.facts[current_id]
            for parent_id in sorted(current["supersedes"]):
                parent = projection.facts[parent_id]
                # EventProjection already verified source scope, relation,
                # strict revision order and complete ancestor existence.
                if parent["value"] != positive["target"]:
                    tokens = _value_tokens(tokenizer, parent["value"])
                    if len(tokens) == len(positive["tokens"]):
                        previous = projection.originals[parent_id]
                        options.append(
                            (
                                -1,
                                f"{10000 - parent['revision']:05d}:{parent_id}",
                                dict(
                                    identity=parent_id,
                                    target=parent["value"],
                                    roots=(previous.root,),
                                ),
                                "same_entity_relation_superseded",
                            )
                        )
                frontier.append(parent_id)
        for negative in rows:
            if (
                positive["index"] == negative["index"]
                or positive["scope"] != negative["scope"]
                or positive["target"] == negative["target"]
                or len(positive["tokens"]) != len(negative["tokens"])
            ):
                continue
            if (
                positive["entity"] == negative["entity"]
                and positive["attribute"] != negative["attribute"]
            ):
                category = "same_entity_different_relation"
                priority = 0
            elif (
                positive["attribute"] == negative["attribute"]
                and positive["entity"] != negative["entity"]
            ):
                category = "same_relation_different_entity"
                priority = 1
            else:
                continue
            options.append((priority, negative["identity"], negative, category))
        if not options:
            unmatched.append(positive["identity"])
            continue
        _, _, distractor, category = min(options, key=lambda row: row[:2])
        chosen[positive["index"]] = dict(
            positive_question=positive["identity"],
            positive_roots=positive["roots"],
            negative_question=distractor["identity"],
            negative_roots=distractor["roots"],
            negative_value=distractor["target"],
            negative_category=category,
            tokens_per_completion=len(positive["tokens"]),
        )
    return chosen, tuple(unmatched)


def binding_margin_loss(
    model, tokenizer, prompt, target, distractor, *, backend="supervised_positions"
):
    """Use both model forwards in the optimization and charge both full inputs.

    loss = CE(correct) + softplus(0.5 + CE(correct) - CE(distractor)).
    Unlike ordinary source CE, the paired term explicitly punishes a plausible
    wrong value for the *same* source-bound question. This is not answer success.
    """
    if (
        not isinstance(prompt, list)
        or not prompt
        or any(type(i) is not int or i < 0 for i in prompt)
        or target == distractor
    ):
        raise ValueError("distinct source values on one exact prompt required")
    correct = _value_tokens(tokenizer, target)
    wrong = _value_tokens(tokenizer, distractor)
    if len(correct) != len(wrong):
        raise ValueError("counterfactual candidate lengths must match")
    pos_ids, pos_labels = completion_ids(tokenizer, prompt, target, maximum=2112)
    neg_ids, neg_labels = completion_ids(tokenizer, prompt, distractor, maximum=2112)
    if (
        len(pos_ids) != len(neg_ids)
        or pos_ids[: len(prompt)] != neg_ids[: len(prompt)]
        or pos_labels[: len(prompt)] != neg_labels[: len(prompt)]
    ):
        raise ValueError("pair changed the source-only question or supervision budget")
    pos, pos_receipt = completion_loss(model, pos_ids, pos_labels, backend=backend)
    neg, neg_receipt = completion_loss(model, neg_ids, neg_labels, backend=backend)
    loss = pos + F.softplus(0.5 + pos - neg)
    if not torch.isfinite(loss):
        raise ValueError("nonfinite source value-binding objective")
    return loss, dict(
        schema="hepta.source-binding.margin.v1",
        backend=backend,
        actual_model_forwards=2,
        actual_input_tokens=pos_receipt["input_tokens"] + neg_receipt["input_tokens"],
        actual_supervised_tokens=(
            pos_receipt["supervised_tokens"] + neg_receipt["supervised_tokens"]
        ),
        actual_projection_positions=(
            pos_receipt["actual_projection_positions"]
            + neg_receipt["actual_projection_positions"]
        ),
        target_nll=float(pos.detach()),
        negative_nll=float(neg.detach()),
        target_over_negative_logprob_margin=float((neg - pos).detach()),
        source_only_not_test_label=True,
        downstream_task_gain=None,
        production_accepted=False,
    )
