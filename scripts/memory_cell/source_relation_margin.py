"""Strict source-derived, equal-length relation negatives for opt-in research.

This does not alter the installed writer. Positives and wrong alternatives
come solely from the same admitted source corpus, not future test targets.
A missing alternative is unknown, never a fabricated negative or model gain.
"""

from collections import Counter

import torch
import torch.nn.functional as F

from event_projection import EventProjection
from grounded_protocol import completion_ids
from native import digest
from source_completion_loss import completion_loss

CATEGORIES = (
    "same_scope_same_attribute_other_entity",
    "same_scope_same_entity_other_attribute",
    "other_scope_same_attribute",
)


def source_negatives(documents, examples, prepared, tokenizer):
    if (
        not 1 <= len(documents) <= 2048
        or not 1 <= len(examples) == len(prepared) <= 2048
        or len({d.identity for d in documents}) != len(documents)
    ):
        raise ValueError("bounded unique original source census required")
    scopes = {}
    for doc in documents:
        scopes.setdefault(doc.scope, []).append(doc)
    projection = {s: EventProjection(tuple(ds)) for s, ds in scopes.items()}
    rows, seen = [], set()
    for ex, (ids, labels) in zip(examples, prepared, strict=True):
        qid, scope = ex["query"]["identity"], ex["query"]["scope"]
        if qid in seen or scope not in projection or not ex["sources"]:
            raise ValueError("duplicate or unbound source-only question")
        seen.add(qid)
        facts = [projection[scope].facts[s] for s in ex["sources"]]
        triples = {(f["entity"], f["attribute"], f["value"]) for f in facts}
        if len(triples) != 1 or next(iter(triples))[2] != ex["target"]:
            raise ValueError("positive completion differs from source facts")
        cutoff = next((i for i, x in enumerate(labels) if x != -100), 0)
        if (
            not 0 < cutoff < len(ids) <= 2112
            or len(labels) != len(ids)
            or labels[:cutoff] != [-100] * cutoff
            or labels[cutoff:] != ids[cutoff:]
        ):
            raise ValueError("original source-only masked completion drift")
        entity, attribute, value = next(iter(triples))
        rows.append((qid, scope, entity, attribute, value, ids[:cutoff], len(ids) - cutoff))
    negatives, counts = [], Counter()
    for qid, scope, entity, attribute, value, prefix, length in rows:
        pool = []
        for other, other_scope, other_entity, other_attr, other_value, _, _ in rows:
            if other == qid or other_value == value:
                continue
            if other_scope == scope and other_attr == attribute and other_entity != entity:
                priority = 0
            elif other_scope == scope and other_entity == entity and other_attr != attribute:
                priority = 1
            elif other_scope != scope and other_attr == attribute:
                priority = 2
            else:
                continue
            ids, labels = completion_ids(
                tokenizer, prefix, other_value, maximum=2112
            )
            if len(ids) - len(prefix) == length:
                pool.append((priority, other, ids, labels))
        if not pool:
            negatives.append(None)
            counts["unavailable"] += 1
            continue
        category, _, ids, labels = min(pool, key=lambda x: x[:2])
        negatives.append((ids, labels))
        counts[CATEGORIES[category]] += 1
    report = dict(
        schema="hepta.source-relation-negatives.v1",
        original_source_roots_digest=digest(sorted({d.root for d in documents})),
        source_questions_digest=digest([r[0] for r in rows]),
        negative_completion_digest=digest(negatives),
        eligible_source_questions=sum(n is not None for n in negatives),
        unavailable_source_questions=sum(n is None for n in negatives),
        categories={key: counts[key] for key in (*CATEGORIES, "unavailable")},
        equal_question_and_completion_token_count=True,
        downstream_question_or_answer_inputs_used=False,
        independent_semantic_review=False,
        production_accepted=False,
    )
    return tuple(negatives), report


def relation_loss(model, positive, negative):
    """Cross-entropy plus source-correct-vs-source-wrong margin (no posthoc fit)."""
    pos_ids, pos_labels = positive
    if negative is not None:
        neg_ids, neg_labels = negative
        cutoff = next((i for i, x in enumerate(pos_labels) if x != -100), 0)
        if (
            not 0 < cutoff < len(pos_ids)
            or len(pos_ids) != len(neg_ids)
            or pos_ids[:cutoff] != neg_ids[:cutoff]
            or neg_labels[:cutoff] != [-100] * cutoff
            or pos_labels[cutoff:] == neg_labels[cutoff:]
        ):
            raise ValueError("unpaired source inputs or unequal target lengths")
    pos, p = completion_loss(
        model, pos_ids, pos_labels, backend="supervised_positions"
    )
    if negative is None:
        return pos, dict(input_tokens=len(pos_ids), pair_used=False)
    neg, n = completion_loss(
        model, neg_ids, neg_labels, backend="supervised_positions"
    )
    if p["supervised_tokens"] != n["supervised_tokens"]:
        raise ValueError("unequal supervised completion lengths")
    loss = pos + 0.5 * F.softplus(0.5 + pos - neg)
    if not torch.isfinite(loss):
        raise ValueError("nonfinite relation objective")
    return loss, dict(
        input_tokens=len(pos_ids) + len(neg_ids),
        pair_used=True,
        positive_mean_nll=float(pos.detach()),
        distractor_mean_nll=float(neg.detach()),
    )


def schedule_cost(prepared, plan, negatives, *, ceiling=65536):
    """Count BOTH training forwards before a single update is admitted."""
    if (
        plan.get("schema") != "hepta.source-write.schedule.v1"
        or len(negatives) != len(prepared)
        or type(ceiling) is not int
        or not 1 <= ceiling <= 65536
    ):
        raise ValueError("incomplete source-only optimizer schedule")
    total, negative_tokens, pairs = 0, 0, 0
    for i in plan["entries"]:
        if type(i) is not int or not 0 <= i < len(prepared):
            raise ValueError("invalid planned source example")
        total += len(prepared[i][0])
        if negatives[i] is not None:
            value = len(negatives[i][0])
            total += value
            negative_tokens += value
            pairs += 1
        if total > ceiling:
            raise ValueError("pairwise write exceeds total forward token ceiling")
    if total - negative_tokens != plan["planned_input_tokens"] or pairs == 0:
        raise ValueError("unbound or unvisited source hard negative")
    return dict(
        all_model_forward_input_tokens=total,
        additional_distractor_input_tokens=negative_tokens,
        actual_negative_forward_passes=pairs,
        input_budget_counts_both_forwards=True,
    )
