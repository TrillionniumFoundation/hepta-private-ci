"""Mechanically retained original train/confirm algorithms with new identity gates.

Scientific routines, seeds, budgets, candidate selection and trajectory schemas
are unchanged. Only publication paths, immutable identity checks and monotonic
phase markers differ from the sealed original study driver.
"""

import json
from pathlib import Path

import numpy as np

from experiments.continuous_boundary_flow.common import write_records
from experiments.continuous_boundary_flow.execution import behavior_data
from experiments.continuous_boundary_flow.models import fit_boundary
from experiments.continuous_boundary_flow.native.adapter import NativeBridge
from experiments.continuous_boundary_flow.scenarios import load_contexts
from experiments.continuous_boundary_flow.study import save_histories
from experiments.continuous_boundary_policy.common import (
    ARMS,
    CONTROLS,
    SEEDS,
    CostMeter,
    append_cost,
    save_json,
    sha,
)
from experiments.continuous_boundary_policy.execution import run_context
from experiments.continuous_boundary_policy.native.bridge import ScoreBridge
from experiments.continuous_boundary_policy.study import store_contexts
from experiments.continuous_boundary_policy.training import train_arm
from .identity import (
    SELECTION_PATH,
    begin_training,
    mark_phase,
    verify_frozen,
    verify_preconfirmation,
    verify_publication,
)


def train(output, binaries):
    output = Path(output)
    verify_frozen(output, binaries)
    begin_training(output)
    checkpoints = []
    for seed in SEEDS:
        setup = CostMeter()
        contexts = load_contexts(seed, "training", 12)
        development = load_contexts(seed, "development", 8)
        histories = [behavior_data(context, seed, 8) for context in contexts]
        boundary = fit_boundary(contexts)
        store_contexts(output, seed, "training", contexts)
        store_contexts(output, seed, "development", development)
        save_histories(output, seed, contexts, histories)
        boundary["weights"] = np.asarray(boundary["weights"]).tolist()
        save_json(output / "datasets" / str(seed) / "BOUNDARY.json", boundary)
        append_cost(
            output, {"phase": "training_setup", "seed": seed, "cost": setup.finish()}
        )
        for arm in ARMS:
            checkpoint, receipt = train_arm(
                output, binaries, seed, arm, contexts, histories, development, boundary
            )
            checkpoints.append(checkpoint)
            append_cost(
                output,
                {
                    "phase": "training_development",
                    "seed": seed,
                    "arm": arm,
                    "cost": receipt["cost"],
                    "native_process_cost": receipt["native_process_cost"],
                },
            )
            print(
                json.dumps(
                    {
                        "phase": "trained",
                        "seed": seed,
                        "arm": arm,
                        "selected": receipt["selected_index"],
                    }
                ),
                flush=True,
            )
        for arm in CONTROLS:
            path = output / "checkpoints" / str(seed) / f"{arm}.json"
            identity = save_json(
                path,
                {
                    "schema": "hepta.continuous-boundary-policy.control.v1",
                    "seed": seed,
                    "arm": arm,
                },
            )
            checkpoints.append(
                {
                    "seed": seed,
                    "arm": arm,
                    "path": str(path.relative_to(output)),
                    "sha256": identity,
                }
            )
    mark_phase(output, "TRAINING_COMPLETE")
    env = json.loads((output / "ENVIRONMENT.json").read_text())
    files = {
        str(p.relative_to(output)): sha(p.read_bytes())
        for p in output.rglob("*")
        if p.is_file()
        and not any(part == "host" for part in p.relative_to(output).parts)
    }
    # Costs append during confirmation; bind the immutable training prefix instead.
    training_costs = files.pop("costs.jsonl")
    raw_costs = (output / "costs.jsonl").read_bytes()
    save_json(
        output / "SELECTION_SEAL.json",
        {
            "schema": "hepta.continuous-boundary-policy.selection.v1",
            "protocol_sha256": env["protocol_sha256"],
            "source_seal_sha256": env["source_seal_sha256"],
            "checkpoints": checkpoints,
            "training_files": files,
            "training_costs_prefix_sha256": training_costs,
            "training_costs_prefix_bytes": len(raw_costs),
            "native_binary_sha256": env["binary_sha256"]["native"],
            "score_binary_sha256": env["binary_sha256"]["score"],
        },
    )


def confirm(output, binaries, selection_commit):
    output = Path(output)
    verify_frozen(output, binaries)
    verify_preconfirmation(output)
    selection_bytes = (output / "SELECTION_SEAL.json").read_bytes()
    selected = json.loads(selection_bytes)
    verify_publication(
        selection_commit,
        SELECTION_PATH,
        selection_bytes,
    )
    training_cost_bytes = (output / "costs.jsonl").read_bytes()
    if (
        len(training_cost_bytes) != selected["training_costs_prefix_bytes"]
        or sha(training_cost_bytes) != selected["training_costs_prefix_sha256"]
    ):
        raise ValueError("Training costs changed after selection")
    for rel, expected in selected["training_files"].items():
        if sha((output / rel).read_bytes()) != expected:
            raise ValueError("Training evidence changed after selection")
    save_json(
        output / "EXTERNAL_SELECTION.json",
        {
            "selection_commit": selection_commit,
            "selection_seal_sha256": sha(selection_bytes),
            "confirmation_started_after_publication": True,
        },
    )
    by_key = {(row["seed"], row["arm"]): row for row in selected["checkpoints"]}
    shards = []
    for seed in SEEDS:
        setup = CostMeter()
        contexts = {
            phase: load_contexts(seed, phase, 8) for phase in ("test_id", "test_ood")
        }
        for phase, rows in contexts.items():
            store_contexts(output, seed, phase, rows)
        append_cost(
            output,
            {"phase": "confirmation_setup", "seed": seed, "cost": setup.finish()},
        )
        for arm in ARMS + CONTROLS:
            source = by_key[seed, arm]
            body = (output / source["path"]).read_bytes()
            if sha(body) != source["sha256"]:
                raise ValueError("Selected checkpoint changed")
            checkpoint = json.loads(body) if arm in ARMS else None
            meter = CostMeter()
            bridge = None
            if arm == "native_sparse":
                bridge = NativeBridge(
                    binaries["native"], output / "confirmation_hosts" / str(seed) / arm
                )
                bridge.load_profile(
                    output / checkpoint["profile_path"], checkpoint["profile_sha256"]
                )
            elif arm in ARMS:
                bridge = ScoreBridge(
                    binaries["score"], output / "confirmation_hosts" / str(seed) / arm
                )
            pending = []
            try:
                for phase, group in contexts.items():
                    records, counts = [], []
                    for context in group:
                        run = run_context(
                            context,
                            seed=seed,
                            phase=phase,
                            paths=16,
                            arm=arm,
                            checkpoint_sha256=source["sha256"],
                            checkpoint=checkpoint,
                            bridge=bridge,
                        )
                        records.extend(run["records"])
                        counts.append(run["counts"])
                    pending.append((phase, records, counts))
            finally:
                native_cost = None if bridge is None else bridge.close()
            append_cost(
                output,
                {
                    "phase": "confirmation_rollout",
                    "seed": seed,
                    "arm": arm,
                    "cost": meter.finish(),
                    "native_process_cost": native_cost,
                },
            )
            serialization = CostMeter()
            for phase, records, counts in pending:
                path = output / "shards" / str(seed) / phase / f"{arm}.jsonl.gz"
                receipt = write_records(path, records)
                receipt.update(
                    path=str(path.relative_to(output)),
                    seed=seed,
                    arm=arm,
                    split=phase,
                    counts=counts,
                )
                shards.append(receipt)
            append_cost(
                output,
                {
                    "phase": "serialization",
                    "seed": seed,
                    "arm": arm,
                    "cost": serialization.finish(),
                },
            )
            print(
                json.dumps(
                    {"phase": "confirmed", "seed": seed, "arm": arm, "episodes": 256}
                ),
                flush=True,
            )
    mark_phase(output, "CONFIRMATION_COMPLETE")
    files = {
        str(p.relative_to(output)): sha(p.read_bytes())
        for p in output.rglob("*")
        if p.is_file()
        and "host" not in p.relative_to(output).parts
        and "confirmation_hosts" not in p.relative_to(output).parts
    }
    save_json(
        output / "MANIFEST.json",
        {
            "schema": "hepta.continuous-boundary-policy.manifest.v1",
            "protocol_sha256": sha((output / "PROTOCOL.json").read_bytes()),
            "source_seal_sha256": sha((output / "SOURCE_SEAL.json").read_bytes()),
            "selection_seal_sha256": sha(selection_bytes),
            "files": files,
            "shards": shards,
            "expected_episodes": len(SEEDS) * len(ARMS + CONTROLS) * 256,
        },
    )
