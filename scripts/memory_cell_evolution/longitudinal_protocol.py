"""Register a new finite development stream before model execution or scoring."""

import argparse
from pathlib import Path

from evolution_common import digest, read_json, require, retain

BASELINE = "429894ac8e0818102cfdea4ad47a56e4583b2902"
BASE_REVISION = "12fd25f77366fa6b3b4b768ec3050bf629380bac"
BASE_IDENTITY = "46b83e37620f8bb1ae57754856718886c6aa1b12d267b5b0993e779f9596f96f"
SCOPE = "longitudinal-development-20261024"
TRAIN_TEMPLATES = [
    "What is the {relation} for {entity}?",
    "Recall the {relation} of {entity}.",
    "For {entity}, return the stored {relation}.",
    "Give {entity}'s {relation}.",
]
READ_TEMPLATES = [
    "Return the retained {relation} for {entity}.",
    "From this cell's recorded facts, what {relation} belongs to {entity}?",
]


def event(kind, source, value=None, revision=None, entity=None):
    return dict(
        kind=kind,
        source_id=source,
        entity=entity or source,
        relation="color",
        value=value,
        expected_revision=revision,
    )


def protocol():
    initial = [
        event("write", f"long_{i:02}", value)
        for i, value in enumerate(
            ["amber", "blue", "cyan", "green", "ivory", "orange", "purple", "red"]
        )
    ]
    rounds = [
        dict(label="initial", background_steps=0, events=initial),
        dict(
            label="arrival",
            background_steps=64,
            events=[event("write", "long_08", "silver")],
        ),
        dict(
            label="corrections",
            background_steps=64,
            events=[
                event("correct", "long_00", "white", 0),
                event("correct", "long_02", "blue", 0),
                event("write", "long_09", "yellow"),
            ],
        ),
        dict(
            label="withdrawal",
            background_steps=64,
            events=[
                event("correct", "long_00", "orange", 1),
                event("revoke", "long_03", revision=0),
                event("write", "long_10", "white"),
            ],
        ),
        dict(
            label="conflict",
            background_steps=0,
            events=[
                event("write", "conflict_04", "red", entity="long_04"),
                event("write", "long_11", "black"),
                event("correct", "long_07", "green", 0),
            ],
        ),
        dict(
            label="resolve",
            background_steps=0,
            events=[
                event("revoke", "conflict_04", revision=0, entity="long_04"),
                event("revoke", "long_05", revision=0),
                event("correct", "long_02", "silver", 1),
            ],
        ),
    ]
    for index, item in enumerate(rounds):
        item["before_background"] = (
            [event("correct", "long_06", ["red", "blue", "cyan"][index - 1], index - 1)]
            if item["background_steps"]
            else []
        )
    return dict(
        schema="hepta.longitudinal.protocol.v3",
        source_baseline=BASELINE,
        supersedes_unexecuted_recipe="78b9712f670a5fe523288ac9fafdea93a2b1c318014ce8005b505db4e0021f6d",
        preexecution_amendment="retain real pre-background queued revisions; conflict_04 revoke targets its original long_04 typed key",
        scope=SCOPE,
        cell_id="semantic-stream",
        role="semantic",
        seed=24019,
        base_repository="HuggingFaceTB/SmolLM2-135M-Instruct",
        base_revision=BASE_REVISION,
        base_identity=BASE_IDENTITY,
        train_templates=TRAIN_TEMPLATES,
        read_templates=READ_TEMPLATES,
        rounds=rounds,
        clean_steps=256,
        rank=8,
        learning_rate=0.001,
        torch_threads=2,
        expected_live_fact_counts=[8, 9, 10, 10, 10, 10],
        control_rounds=[0, 5],
        controls=["base", "shuffled"],
        decoder_optimizer_updates=1728,
        published_training_attempts=6,
        superseded_training_attempts=3,
        expected_parameter_query_rows=186,
        maximum_parameter_query_rows=400,
        runtime_limits=dict(
            train_timeout_seconds=900,
            read_timeout_seconds=240,
            whole_trial_seconds=5400,
        ),
        predeclared_quality=dict(
            each_round_source_both_wordings_accuracy_min=0.9,
            unchanged_retention_both_wordings_accuracy_min=0.9,
            corrected_sources_both_wordings_exact=True,
        ),
        quality_unit="current source entity/relation, both registered held-out wordings must match; repeated questions are correlated",
        admission_gates=dict(
            unknown_conflict_revoked_callbacks=0,
            stale_parameter_callbacks=0,
            revoked_ancestry_in_clean_publication=0,
        ),
        background_schedule="write after candidate directory exists and before trainer returns; verify 64 completed updates in retained superseded artifact",
        starvation_measurement="three adversarial in-construction supersessions plus recovery after quiescence; no unmeasured sustained-rate claim",
        source_overlay_in_parameter_metrics=False,
        failure_policy="retain every attempt; complete all quality panels without retuning; stop only on execution/integrity/resource failure",
        baseline_comparison="same questions from disabled/shuffled adapter at first and last round; exact source overlay scored separately",
        confirmation=False,
        prospective=False,
        natural_task_cohort=False,
        production_accepted=False,
        new_capability="bounded repeated correction/withdrawal engineering and measured finite retention; no future or general-memory qualification",
    )


def load_protocol(path, expected_digest):
    value = read_json(path)
    require(
        digest(value) == expected_digest,
        "registered longitudinal protocol digest changed",
    )
    require(value == protocol(), "driver recipe differs from registered stream")
    return value


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    value = protocol()
    retain(args.output, value)
    print(digest(value))
