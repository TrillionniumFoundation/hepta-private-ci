"""Bind source-recall diagnostics to facts actually visited by the writer.

Training on one scope does not prove every derived question in that scope was
shown to the optimizer. This module rederives both the authorized examples and
full token schedule, without opening a downstream test plan or executing a model.
"""

import math

from native import digest
from source_completion_loss import BACKENDS


def verified_visits(documents, tokenizer, training):
    """Return {source-question-id: integer visits}, verifying full write exposure.

    Zero is not a failed answer, an independent holdout, or an unseen source:
    it means this source-derived training target had no optimizer updates.
    """
    from experience_memory import STEPS, TOKEN_CEILING, source_examples
    from source_write_coverage import audit_coverage
    from source_write_schedule import prepare

    if (
        not isinstance(training, dict)
        or training.get("curriculum") not in ("single_hop", "source_two_hop")
        or training.get("loss_backend") not in BACKENDS
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
    existing = training.get("write_schedule")
    if not isinstance(existing, dict):
        raise ValueError("source training schedule is missing")
    maximum, ceiling = existing.get("maximum_steps"), existing.get("token_ceiling")
    if (
        type(maximum) is not int
        or not 1 <= maximum <= STEPS
        or type(ceiling) is not int
        or not 1 <= ceiling <= TOKEN_CEILING
    ):
        raise ValueError("source exposure exceeds the registered write bounds")

    # Sparse projection is already governed by the pinned writer's Qwen parity
    # admission; this replay checks the actual projection/exposure counters,
    # not whether a model merely claimed to have passed that external proof.
    # Source-margin writing trains a predeclared matching SUBSET with two real
    # forwards per step. Reconstruct the full, pre-subset plan and negative
    # provenance, not just the saved active rows. Absent questions stay zero
    # exposure; a hard negative is NOT a supervised positive question.
    original_examples = examples
    objective = training.get("binding_objective", "completion_ce")
    factor = 1
    expected_binding = None
    if objective == "source_margin":
        from source_binding_margin import source_hard_negatives

        if (
            training["curriculum"] != "single_hop"
            or ceiling != TOKEN_CEILING // 2
        ):
            raise ValueError("unsupported source-margin writer profile")
        pairs, unmatched = source_hard_negatives(
            original_examples,
            documents,
            tokenizer,
            allowed_roots={doc.root for doc in documents},
            revoked=set(),
        )
        if not pairs:
            raise ValueError("source-margin write lacks admitted hard negatives")
        chosen = sorted(pairs)
        before, initial = prepare(
            tokenizer,
            original_examples,
            maximum_steps=maximum,
            token_ceiling=TOKEN_CEILING,
        )
        del before
        examples = tuple(original_examples[index] for index in chosen)
        expected_binding = dict(
            source_only=True,
            training_pairs=[pairs[index] for index in chosen],
            unmatched_source_question_ids=list(unmatched),
            original_schedule_digest=digest(initial),
            forward_token_charge_factor=2,
            known_task_answers_consumed=False,
            independent_review=False,
            production_accepted=False,
        )
        factor = 2
    elif objective != "completion_ce":
        raise ValueError("unregistered source-writing objective")
    if (
        training.get("binding_receipt") != expected_binding
        or digest(examples) != digest(training.get("source_supervision"))
        or training.get("dispositions") != dispositions
        or training.get("curriculum_receipt") != curriculum_receipt
    ):
        raise ValueError("source-only target, binding or curriculum changed")

    prepared, expected = prepare(
        tokenizer, examples, maximum_steps=maximum, token_ceiling=ceiling
    )
    if (
        existing != expected
        or training.get("scopes") != expected["scopes"]
        or training.get("training_digest")
        != (
            digest((examples, prepared, expected_binding))
            if expected_binding is not None
            else digest((examples, prepared))
        )
    ):
        raise ValueError("writer schedule or exact token exposure changed")
    coverage = audit_coverage(
        examples, prepared, existing, curriculum=training["curriculum"]
    )
    # Full projection cost and the actually evaluated vocabulary positions must
    # match the exact writer schedule, for completion CE and source-margin alike.
    projected = factor * (
        existing["planned_input_tokens"]
        if training["loss_backend"] == "full"
        else existing["planned_supervised_tokens"]
    )
    if (
        training.get("write_curriculum_coverage") != coverage
        or type(training.get("steps")) is not int
        or training["steps"] != existing["planned_steps"]
        or training.get("input_tokens") != factor * existing["planned_input_tokens"]
        or training.get("supervised_tokens")
        != factor * existing["planned_supervised_tokens"]
        or type(training.get("full_projection_positions")) is not int
        or training["full_projection_positions"]
        != factor * existing["planned_input_tokens"]
        or type(training.get("actual_projection_positions")) is not int
        or training["actual_projection_positions"] != projected
        or not isinstance(training.get("losses"), list)
        or len(training["losses"]) != training["steps"]
        or any(
            type(x) not in (int, float) or not math.isfinite(x)
            for x in training["losses"]
        )
    ):
        raise ValueError("completed training does not match the claimed source visits")
    identities = [item["query"]["identity"] for item in original_examples]
    active = [item["query"]["identity"] for item in examples]
    if len(set(identities)) != len(identities):
        raise ValueError("duplicate source-only supervision identity")
    visits = dict.fromkeys(identities, 0)
    visits.update(zip(active, existing["visits_per_example"], strict=True))
    return visits, digest(existing)
