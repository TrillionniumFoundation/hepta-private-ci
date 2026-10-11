"""Bind source-recall diagnostics to facts actually visited by the writer.

Training on one scope does not prove every derived question in that scope was
shown to the optimizer. This module rederives both the authorized examples and
full token schedule, without opening a downstream test plan or executing a model.
"""

import math

from native import digest


def verified_visits(documents, tokenizer, training):
    """Return {source-question-id: integer visits}, verifying full write exposure.

    Zero is not a failed answer, an independent holdout, or an unseen source:
    it means this source-derived training target had no optimizer updates.
    """
    from experience_memory import STEPS, TOKEN_CEILING, source_examples
    from source_write_coverage import audit_coverage
    from source_write_schedule import prepare

    if not isinstance(training, dict) or training.get("curriculum") not in (
        "single_hop", "source_two_hop"
    ):
        raise ValueError("registered source-written curriculum required")
    if (
        not documents
        or len({doc.identity for doc in documents}) != len(documents)
        or training.get("roots") != sorted({doc.root for doc in documents})
        or not set(training.get("scopes", ())) <= {doc.scope for doc in documents}
    ):
        raise ValueError("source training view or ancestry drift")
    revision = training.get("revision")
    if type(revision) is not int or not 0 <= revision <= 10000:
        raise ValueError("invalid source-written logical revision")
    args = dict(
        revision=revision,
        allowed_roots={doc.root for doc in documents},
        revoked=set(),
    )
    if training["curriculum"] == "source_two_hop":
        from source_composition_curriculum import combine_source_examples

        examples, dispositions, curriculum_receipt = combine_source_examples(
            documents, **args
        )
    else:
        examples, dispositions = source_examples(documents, **args)
        curriculum_receipt = None
    if (
        digest(examples) != digest(training.get("source_supervision"))
        or training.get("dispositions") != dispositions
        or training.get("curriculum_receipt") != curriculum_receipt
    ):
        raise ValueError("source-only target or curriculum changed after writing")
    existing = training.get("write_schedule")
    if not isinstance(existing, dict):
        raise ValueError("source training schedule is missing")
    maximum, ceiling = existing.get("maximum_steps"), existing.get("token_ceiling")
    if (
        type(maximum) is not int or not 1 <= maximum <= STEPS
        or type(ceiling) is not int or not 1 <= ceiling <= TOKEN_CEILING
    ):
        raise ValueError("source exposure exceeds the registered write bounds")
    prepared, expected = prepare(
        tokenizer, examples, maximum_steps=maximum, token_ceiling=ceiling
    )
    if (
        existing != expected
        or training.get("scopes") != expected["scopes"]
        or training.get("training_digest") != digest((examples, prepared))
    ):
        raise ValueError("writer schedule or exact token exposure changed")
    coverage = audit_coverage(
        examples, prepared, existing, curriculum=training["curriculum"]
    )
    if (
        training.get("write_curriculum_coverage") != coverage
        or type(training.get("steps")) is not int
        or training["steps"] != existing["planned_steps"]
        or training.get("input_tokens") != existing["planned_input_tokens"]
        or training.get("supervised_tokens") != existing["planned_supervised_tokens"]
        or not isinstance(training.get("losses"), list)
        or len(training["losses"]) != training["steps"]
        or any(
            type(x) not in (int, float) or not math.isfinite(x)
            for x in training["losses"]
        )
    ):
        raise ValueError("completed training does not match the claimed source visits")
    identities = [item["query"]["identity"] for item in examples]
    if len(set(identities)) != len(identities):
        raise ValueError("duplicate source-only supervision identity")
    return dict(zip(identities, existing["visits_per_example"], strict=True)), digest(
        existing
    )
