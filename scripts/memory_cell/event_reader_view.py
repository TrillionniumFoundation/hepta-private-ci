"""Lossless controlled-event explanation as a separate input intervention.

Every original selected JSON document is still delivered verbatim. The extra
sentences deterministically restate its schema, never select facts, infer an
answer or add a source. This changes INPUT REPRESENTATION, not learned memory.
"""

from dataclasses import asdict
import json

from bundle_reader import SYSTEM, PromptBudgetError, compile_prompt
from event_projection import EventProjection
from native import digest
from reader_reference import ReferenceReader

PROFILE = "hepta.controlled-event.schema-expansion.v1"


def event_prompt(
    tokenizer, query, bundle, originals, *, frontier, revoked, token_limit
):
    # The raw prompt must fit too; no hidden increase to the source budget.
    _, receipt = compile_prompt(
        tokenizer,
        query,
        bundle,
        originals,
        frontier=frontier,
        revoked=revoked,
        token_limit=token_limit,
    )
    scope_sources = tuple(d for d in originals.values() if d.scope == query.scope)
    if any(d.root in revoked for d in scope_sources):
        raise ValueError("withdrawn event projection source")
    projection = EventProjection(scope_sources)
    if projection.frontier != frontier:
        raise ValueError("schema expansion source frontier drift")
    derived = []
    for source in receipt["delivered_evidence"]:
        original = originals[source["original_id"]]
        if source["excerpt"] != original.content:
            raise ValueError("schema expansion requires an entire original event")
        row = projection.facts[original.identity]
        prior = ", ".join(row["supersedes"]) or "none explicitly named"
        text = (
            f"Event {row['id']}: at logical revision {row['revision']}, "
            f"entity {row['entity']} has attribute {row['attribute']} "
            f"with value {row['value']}. Superseded event IDs: {prior}. "
            "This is a logical state revision, not a calendar date."
        )
        derived.append(
            dict(
                label=source["label"],
                original_id=original.identity,
                original_digest=digest(original.content),
                text=text,
                derivation_profile=PROFILE,
            )
        )
    body = dict(
        question=query.content,
        question_time=query.observed_at,
        evidence=[
            dict(label=s["label"], observed_at=s["observed_at"], text=s["excerpt"])
            for s in receipt["delivered_evidence"]
        ],
        controlled_schema_expansions=derived,
    )
    ids = tokenizer.apply_chat_template(
        [
            dict(role="system", content=SYSTEM),
            dict(role="user", content=json.dumps(body, ensure_ascii=False)),
        ],
        tokenize=True,
        add_generation_prompt=True,
    )
    if not ids or len(ids) > token_limit:
        raise PromptBudgetError(len(ids), token_limit)
    return ids, receipt | dict(
        raw_view_input_tokens=receipt["input_tokens"],
        input_ids_digest=digest(ids),
        input_tokens=len(ids),
        view_profile=PROFILE,
        derived_evidence=derived,
        derivation_event_reads=len(scope_sources),
        derived_view_digest=digest(derived),
        query_digest=digest(asdict(query)),
        independent_semantic_review=False,
    )


class EventPresentationReader(ReferenceReader):
    """Same weights, generation and final source checks; explicit input view."""

    def __init__(self, directory, *, expected_inventory):
        super().__init__(directory, expected_inventory=expected_inventory)
        self.profile = digest((self.profile, PROFILE))

    def compile_input(self, query, bundle, originals, *, frontier, revoked, token_limit):
        return event_prompt(
            self.tokenizer,
            query,
            bundle,
            originals,
            frontier=frontier,
            revoked=revoked,
            token_limit=token_limit,
        )
