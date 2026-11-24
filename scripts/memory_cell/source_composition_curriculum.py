"""Optional source-only two-hop writing, not task-conditioned knowledge transfer.

An example exists only when every prerequisite is present in the admitted
source scope, effective at the logical revision, and unambiguous. This is
controlled authored supervision, not independent semantic adjudication.
"""

from dataclasses import asdict
from datetime import datetime

from event_projection import EventProjection, Lookup
from event_revision_closure import select_current
from native import Question, digest

PROFILE = "hepta.source-only.two-hop-curriculum.v1"
MAX_COMPOSITIONS = 128


def compositions(
    documents, *, revision, allowed_roots, revoked, limit=MAX_COMPOSITIONS
):
    """Derive bounded, two-hop QA without reading any downstream task plan.

    Reject overflowing opportunities rather than selecting an answer-biased
    subset. The inherited source-only writer validates exact roots and dates.
    """
    from experience_memory import source_examples

    if type(limit) is not int or not 1 <= limit <= MAX_COMPOSITIONS:
        raise ValueError("bounded source-only composition count required")
    direct, _ = source_examples(
        documents, revision=revision, allowed_roots=allowed_roots, revoked=revoked
    )
    examples, unknown = [], []
    for scope in sorted({x["query"]["scope"] for x in direct}):
        docs = tuple(
            sorted(
                (d for d in documents if d.scope == scope),
                key=lambda d: d.identity,
            )
        )
        projection = EventProjection(docs)
        candidates = tuple(sorted(projection.facts))
        visible = {
            key: row
            for key, row in projection.facts.items()
            if row["revision"] <= revision
        }
        first_keys = sorted(
            {(row["entity"], row["attribute"]) for row in visible.values()}
        )
        observed = max(datetime.fromisoformat(d.observed_at) for d in docs).isoformat()
        for entity, first_attr in first_keys:
            first_ids, state = select_current(
                projection,
                Lookup(entity, (first_attr,), revision),
                candidates,
                revoked=revoked,
                limit=8,
            )
            first_values = {projection.facts[key]["value"] for key in first_ids}
            if state["incomplete"] or state["conflicts"] or len(first_values) != 1:
                continue
            successor = next(iter(first_values))
            second_attrs = sorted(
                {
                    row["attribute"]
                    for row in visible.values()
                    if row["entity"] == successor
                }
            )
            for second_attr in second_attrs:
                selected, outcome = select_current(
                    projection,
                    Lookup(entity, (first_attr, second_attr), revision),
                    candidates,
                    revoked=revoked,
                    limit=8,
                )
                terminal = {
                    projection.facts[k]["value"]
                    for k in selected
                    if (
                        projection.facts[k]["entity"],
                        projection.facts[k]["attribute"],
                    )
                    == (successor, second_attr)
                }
                if outcome["incomplete"] or outcome["conflicts"] or len(terminal) != 1:
                    unknown.append(
                        dict(
                            scope=scope,
                            entity=entity,
                            path=[first_attr, second_attr],
                            status="ambiguous_or_incomplete",
                        )
                    )
                    continue
                if len(selected) < 2 or not set(first_ids).issubset(selected):
                    raise ValueError("two-hop supervision lost the first premise")
                question = Question(
                    "source_path_"
                    + digest(
                        (
                            PROFILE,
                            scope,
                            entity,
                            first_attr,
                            second_attr,
                            revision,
                        )
                    ),
                    scope,
                    scope,
                    f"At logical revision {revision}, follow {first_attr} "
                    f"then {second_attr} from entity {entity}. "
                    "Return only the final recorded identifier.",
                    observed,
                )
                examples.append(
                    dict(
                        query=asdict(question),
                        target=next(iter(terminal)),
                        sources=list(selected),
                        source_digest=digest(
                            [asdict(projection.originals[k]) for k in selected]
                        ),
                        curriculum=PROFILE,
                        source_only=True,
                        independent_review=False,
                    )
                )
                if len(examples) > limit:
                    raise ValueError("source composition opportunity cap exceeded")
    return tuple(examples), tuple(unknown)


def combine_source_examples(documents, *, revision, allowed_roots, revoked):
    """Prepend each scope's compositional examples within the SAME step budget."""
    from experience_memory import source_examples

    direct, unknown = source_examples(
        documents, revision=revision, allowed_roots=allowed_roots, revoked=revoked
    )
    composite, unresolved = compositions(
        documents, revision=revision, allowed_roots=allowed_roots, revoked=revoked
    )
    scopes = sorted({item["query"]["scope"] for item in direct})
    combined = tuple(
        example
        for scope in scopes
        for example in (
            *(x for x in composite if x["query"]["scope"] == scope),
            *(x for x in direct if x["query"]["scope"] == scope),
        )
    )
    if len(combined) > 2048 or len({x["query"]["identity"] for x in combined}) != len(
        combined
    ):
        raise ValueError("duplicate or unbounded source-writing examples")
    receipt = dict(
        curriculum=PROFILE,
        direct_examples=len(direct),
        composition_examples=len(composite),
        question_plan_digest=digest([x["query"] for x in combined]),
        independent_task_labels_seen=False,
        model_calls=0,
        production_accepted=False,
    )
    return combined, list(unknown) + list(unresolved), receipt
