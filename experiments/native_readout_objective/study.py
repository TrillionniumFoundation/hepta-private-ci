"""Phase-separated native readout training, published selection, and confirmation."""

import argparse
import json
from pathlib import Path

from experiments.continuous_boundary_flow.execution import behavior_data
from experiments.continuous_boundary_flow.scenarios import load_contexts
from experiments.continuous_boundary_flow.study import save_histories

from .common import (
    ALL_ARMS,
    ARMS,
    PACKAGE,
    REPOSITORY,
    SEEDS,
    CostMeter,
    append_cost,
    context_file,
    open_bridge,
    read_json,
    save_json,
    scientific_files,
    sha,
    write_records,
)
from .execution import run_context
from .source import freeze, initialize, verify_frozen, verify_publication
from .training import export_features, train_arm


def train(output, binary):
    output = Path(output)
    source = verify_frozen(output, binary)
    if scientific_files(output).keys() != {
        "PROTOCOL.json",
        "SOURCE_SEAL.json",
        "ENVIRONMENT.json",
        "costs.jsonl",
    }:
        raise ValueError(
            "Training requires fresh initialized evidence; preserve any partial attempt"
        )
    save_json(
        output / "TRAINING_STARTED.json",
        {"schema": "hepta.native-readout-objective.phase.v1", "phase": "training"},
    )
    checkpoints = []
    for seed in SEEDS:
        setup = CostMeter()
        contexts, development = (
            load_contexts(seed, "training", 12),
            load_contexts(seed, "development", 8),
        )
        histories = [behavior_data(c, seed, 8) for c in contexts]
        context_file(output, seed, "training", contexts)
        context_file(output, seed, "development", development)
        save_histories(output, seed, contexts, histories)
        append_cost(
            output, {"phase": "training_setup", "seed": seed, "cost": setup.finish()}
        )
        activation, q, exported = export_features(
            output, binary, seed, contexts, histories, source
        )
        append_cost(
            output,
            {
                "phase": "native_feature_export",
                "seed": seed,
                "cost": exported["cost"],
                "native_process_cost": exported["native_process_cost"],
            },
        )
        for arm in ARMS:
            item, receipt = train_arm(
                output, binary, seed, arm, activation, q, exported, development, source
            )
            checkpoints.append(item)
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
        control_path = output / "checkpoints" / str(seed) / "finite_grid_dp.json"
        control_sha = save_json(
            control_path,
            {
                "schema": "hepta.native-readout-objective.control.v1",
                "seed": seed,
                "arm": "finite_grid_dp",
            },
        )
        checkpoints.append(
            {
                "seed": seed,
                "arm": "finite_grid_dp",
                "path": str(control_path.relative_to(output)),
                "sha256": control_sha,
            }
        )
    files = scientific_files(output)
    costs = files.pop("costs.jsonl")
    env = read_json(output / "ENVIRONMENT.json")
    save_json(
        output / "SELECTION_SEAL.json",
        {
            "schema": "hepta.native-readout-objective.selection.v1",
            "checkpoints": checkpoints,
            "training_files": files,
            "training_costs_prefix_sha256": costs,
            "training_costs_prefix_bytes": (output / "costs.jsonl").stat().st_size,
            "protocol_sha256": env["protocol_sha256"],
            "source_seal_sha256": env["source_seal_sha256"],
            "native_binary_sha256": env["native_binary_sha256"],
            "confirmation_generated": False,
        },
    )


def confirm(output, binary, commit):
    output = Path(output)
    source = verify_frozen(output, binary)
    selection_bytes = (output / "SELECTION_SEAL.json").read_bytes()
    selection = read_json(output / "SELECTION_SEAL.json")
    verify_publication(
        commit,
        str((PACKAGE / "evidence/SELECTION_SEAL.json").relative_to(REPOSITORY)),
        selection_bytes,
    )
    expected_files = dict(selection["training_files"])
    expected_files.update(
        {
            "costs.jsonl": selection["training_costs_prefix_sha256"],
            "SELECTION_SEAL.json": sha(selection_bytes),
        }
    )
    if (
        scientific_files(output) != expected_files
        or (output / "costs.jsonl").stat().st_size
        != selection["training_costs_prefix_bytes"]
    ):
        raise ValueError(
            "Training changed or confirmation already started; preserve the attempt"
        )
    env = read_json(output / "ENVIRONMENT.json")
    if any(
        selection[name] != env[name]
        for name in ["protocol_sha256", "source_seal_sha256", "native_binary_sha256"]
    ):
        raise ValueError("Selection seal refers to different study identities")
    selected = {(x["seed"], x["arm"]): x for x in selection["checkpoints"]}
    if len(selected) != len(selection["checkpoints"]) or set(selected) != {
        (seed, arm) for seed in SEEDS for arm in ALL_ARMS
    }:
        raise ValueError("Selection checkpoint roster is incomplete or duplicated")
    save_json(
        output / "EXTERNAL_SELECTION.json",
        {
            "schema": "hepta.native-readout-objective.external-selection.v1",
            "selection_commit": commit,
            "selection_seal_sha256": sha(selection_bytes),
            "confirmation_started_after_publication": True,
        },
    )
    shards, panels = [], []
    for seed in SEEDS:
        setup = CostMeter()
        contexts = {
            split: load_contexts(seed, split, 8) for split in ["test_id", "test_ood"]
        }
        for split, group in contexts.items():
            context_file(output, seed, split, group)
        append_cost(
            output,
            {"phase": "confirmation_setup", "seed": seed, "cost": setup.finish()},
        )
        for arm in ALL_ARMS:
            item = selected[seed, arm]
            checkpoint = read_json(output / item["path"]) if arm in ARMS else None
            if sha((output / item["path"]).read_bytes()) != item["sha256"]:
                raise ValueError("Selected checkpoint identity changed")
            meter, bridge = CostMeter(), None
            if arm in ARMS:
                bridge = open_bridge(
                    binary, output / "hosts" / "confirmation" / str(seed) / arm, source
                )
                bridge.load_profile(
                    output / checkpoint["profile_path"], checkpoint["profile_sha256"]
                )
            pending = []
            try:
                for split, group in contexts.items():
                    records, counts = [], []
                    for context in group:
                        run = run_context(
                            context,
                            seed=seed,
                            phase=split,
                            paths=16,
                            arm=arm,
                            checkpoint_sha256=item["sha256"],
                            checkpoint=checkpoint,
                            bridge=bridge,
                        )
                        records.extend(run["records"])
                        counts.append(run["counts"])
                    pending.append((split, records, counts))
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
            for split, records, counts in pending:
                path = output / "shards" / str(seed) / split / f"{arm}.jsonl.gz"
                receipt = write_records(path, records)
                receipt.update(
                    path=str(path.relative_to(output)),
                    seed=seed,
                    arm=arm,
                    split=split,
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
        from .diagnostics import same_state_panel

        panels.append(same_state_panel(output, binary, seed, selected, source))
    save_json(
        output / "MANIFEST.json",
        {
            "schema": "hepta.native-readout-objective.manifest.v1",
            "protocol_sha256": sha((output / "PROTOCOL.json").read_bytes()),
            "source_seal_sha256": sha((output / "SOURCE_SEAL.json").read_bytes()),
            "selection_seal_sha256": sha(selection_bytes),
            "files": scientific_files(output),
            "shards": shards,
            "diagnostic_panels": panels,
            "expected_episodes": len(SEEDS) * len(ALL_ARMS) * 256,
        },
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=["freeze", "initialize", "train", "confirm"])
    parser.add_argument("--output", type=Path)
    parser.add_argument("--native-binary", type=Path, required=True)
    parser.add_argument("--build-receipt", type=Path)
    parser.add_argument("--native-manifest", type=Path)
    parser.add_argument("--publication-commit")
    args = parser.parse_args()
    if args.phase == "freeze":
        print(
            json.dumps(
                freeze(args.native_binary, args.build_receipt, args.native_manifest)
            )
        )
    elif args.phase == "initialize":
        initialize(args.output, args.native_binary, args.publication_commit)
    elif args.phase == "train":
        train(args.output, args.native_binary)
    else:
        confirm(args.output, args.native_binary, args.publication_commit)


if __name__ == "__main__":
    main()
