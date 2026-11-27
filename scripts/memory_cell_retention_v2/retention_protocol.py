"""Freeze all nine exposed-development trials before any pretrained execution."""

import argparse
from pathlib import Path
import time

from retention_common import (
    BASE_IDENTITY,
    CAMPAIGN,
    base_inventory,
    digest,
    file_digest,
    read_json,
    require,
    retain,
    runtime_versions,
    source_inventory,
)
from longitudinal_runtime import apply_events
from memory_service import MemoryService

SEEDS = [24019, 24023, 24029]
ARMS = [
    dict(name="ce_001", objective="completion_ce", learning_rate=0.001, steps=256),
    dict(name="ce_01", objective="completion_ce", learning_rate=0.01, steps=256),
    dict(
        name="margin_01",
        objective="source_value_margin_v2",
        learning_rate=0.01,
        steps=128,
    ),
]


def trial_order():
    return [
        (seed, ARMS[(index + offset) % 3])
        for index, seed in enumerate(SEEDS)
        for offset in range(3)
    ]


def prepare_sources(directory, stream):
    """Replay actual corrections/conflicts/withdrawals, without starting jobs."""
    service = MemoryService(
        directory / "source-owner", stream["scope"], stream["cell_id"], stream["role"]
    )
    rounds, events = [], []
    for item in stream["rounds"]:
        events.append(apply_events(service, item["before_background"] + item["events"]))
        rounds.append(service.snapshot())
    require(
        [len(s["facts"]) for s in rounds] == stream["expected_live_fact_counts"],
        "replayed source stream changed",
    )
    require(
        not set(rounds[-1]["revoked"])
        & {f["source_digest"] for f in rounds[-1]["facts"]},
        "withdrawn source entered terminal training facts",
    )
    require(
        service.parameter_binding() is None,
        "preparation unexpectedly published a model",
    )
    retain(directory / "source-events.json", events)
    retain(directory / "source-rounds.json", rounds)
    retain(directory / "snapshot.json", rounds[-1])
    retain(directory / "previous-snapshot.json", rounds[-2])
    return service, rounds[-1], rounds[-2]


def freeze(output, base):
    output, base = Path(output).resolve(), Path(base).resolve()
    output.mkdir(parents=True, exist_ok=False)
    campaign = read_json(CAMPAIGN)
    require(campaign["seeds"] == SEEDS, "old development seed set changed")
    model = base_inventory(base)
    require(digest(model) == BASE_IDENTITY, "registered fixed base bytes changed")
    source = source_inventory()
    retain(output / "source-identity.json", source)
    retain(output / "base-inventory.json", model)
    retain(output / "runtime-versions.json", runtime_versions())
    trials = []
    for seed, arm in trial_order():
        trial_id = f"s{seed}-{arm['name']}"
        directory = output / trial_id
        directory.mkdir()
        stream = campaign["streams"][str(seed)]
        service, snapshot, previous = prepare_sources(directory, stream)
        train = dict(
            schema="hepta.retention-v2.train-request.v1",
            trial_id=trial_id,
            source_identity_path=str(output / "source-identity.json"),
            source_identity_sha256=digest(source),
            base=str(base),
            base_identity=BASE_IDENTITY,
            service_root=str(service.root),
            snapshot_path=str(directory / "snapshot.json"),
            snapshot_sha256=digest(snapshot),
            scope=stream["scope"],
            cell_id=stream["cell_id"],
            role=stream["role"],
            seed=seed,
            rank=8,
            torch_threads=2,
            actual_forward_budget=256,
            templates=stream["train_templates"],
            **arm,
        )
        panels = dict(
            train_templates=stream["train_templates"],
            heldout_templates=stream["read_templates"],
            final_events=stream["rounds"][-1]["events"],
        )
        retain(directory / "train-request.json", train)
        retain(directory / "panels.json", panels)
        trials.append(
            dict(
                trial_id=trial_id,
                seed=seed,
                arm=arm["name"],
                train_request_sha256=digest(train),
                panels_sha256=digest(panels),
                snapshot_sha256=digest(snapshot),
                previous_sha256=digest(previous),
            )
        )
    protocol = dict(
        schema="hepta.retention-v2.screen.v1",
        frozen_unix_ns=time.time_ns(),
        old_campaign_sha256=file_digest(CAMPAIGN),
        base_identity=BASE_IDENTITY,
        source_identity_sha256=digest(source),
        seeds=SEEDS,
        arms=ARMS,
        trials=trials,
        data_status="previously exposed old terminal states; development only",
        initialization="fresh fixed base and fresh LoRA per trial; no learned parent",
        objective="CE(value+EOS) + relu(1 + mean_logp(negative_value) - mean_logp(positive_value))",
        negative_policy="cycle distinct tokenized values from live facts; same prompt; no EOS in margin",
        controls=dict(
            adapter=["train", "heldout"], base=["heldout"], shuffled=["heldout"]
        ),
        expected_training_forwards=2304,
        expected_optimizer_updates=1920,
        expected_decoder_queries=900,
        expected_training_processes=9,
        expected_reader_processes=27,
        selection_rule="maximize minimum across seeds of min(current-source both-wordings accuracy, unchanged-retention accuracy); then mean of those seed minima; then fixed arm order",
        tie_order=[arm["name"] for arm in ARMS],
        diagnostic_only="training-wording scores; never used to select or retune",
        quality_rule="all three seeds current >=0.9 and retention >=0.9; all final corrections exact; adapter exceeds both controls on current accuracy in every seed",
        withdrawal_probe="after all reads revoke long_00 at its actual revision; revoked key and another live key must produce zero decoder callbacks from stale published version",
        budget_match="equal actual training forwards, not equal optimizer updates, token counts, FLOPs or total end-to-end cost",
        limits=dict(
            train_seconds=900,
            reader_seconds=300,
            retained_bytes=150_000_000,
            torch_threads=2,
            whole_screen_seconds=10800,
        ),
        failure_policy="retain every planned attempt and charge its reserved training budget without refunds; no automatic retry or hyperparameter changes; stop on execution/integrity/resource failure",
        source_overlay_in_parameter_metrics=False,
        automatic_followup_training=False,
        future_natural_task_gate_satisfied=False,
        independent_task_generalization=False,
        biological_or_general_memory_claim=False,
        production_accepted=False,
    )
    retain(output / "protocol.json", protocol)
    retain(
        output / "freeze.json",
        dict(
            protocol_sha256=digest(protocol),
            model_invocation_started=False,
            frozen_trials=len(trials),
        ),
    )
    return digest(protocol)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--base", type=Path, required=True)
    args = parser.parse_args()
    print(freeze(args.output, args.base))
