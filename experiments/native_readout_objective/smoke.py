"""Diagnostic-only native integration; does not open any registered study seed."""

import argparse
import json
from pathlib import Path

from experiments.continuous_boundary_flow.execution import behavior_data
from experiments.continuous_boundary_flow.scenarios import load_contexts
from experiments.continuous_boundary_flow.study import save_histories

from .common import (
    ARMS,
    CostMeter,
    context_file,
    open_bridge,
    read_json,
    save_json,
    sha,
    write_records,
)
from .diagnostics import same_state_panel
from .execution import run_context
from .training import export_features, train_arm


def run(output, binary):
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    (output / "costs.jsonl").touch()
    meter = CostMeter()
    contexts, development = (
        load_contexts(991, "training", 2),
        load_contexts(991, "development", 1),
    )
    histories = [behavior_data(context, 991, 2) for context in contexts]
    context_file(output, 991, "training", contexts)
    context_file(output, 991, "development", development)
    save_histories(output, 991, contexts, histories)
    activation, q, exported = export_features(output, binary, 991, contexts, histories)
    diagnostic = load_contexts(991, "diagnostic", 1)
    selected, results = {}, []
    for arm in ARMS:
        item, receipt = train_arm(
            output,
            binary,
            991,
            arm,
            activation,
            q,
            exported,
            development,
            epochs=4,
            candidate_indices=[1],
            development_paths=2,
        )
        selected[991, arm] = item
        checkpoint = read_json(output / item["path"])
        bridge = open_bridge(binary, output / "hosts" / arm)
        try:
            bridge.load_profile(
                output / checkpoint["profile_path"], checkpoint["profile_sha256"]
            )
            result = run_context(
                diagnostic[0],
                seed=991,
                phase="diagnostic",
                paths=4,
                arm=arm,
                checkpoint_sha256=item["sha256"],
                checkpoint=checkpoint,
                bridge=bridge,
            )
        finally:
            native_cost = bridge.close()
        path = output / "records" / f"{arm}.jsonl.gz"
        shard = write_records(path, result["records"])
        shard["path"] = str(path.relative_to(output))
        results.append(
            {
                "arm": arm,
                "checkpoint": item,
                "shard": shard,
                "counts": result["counts"],
                "native_process_cost": native_cost,
                "training_cost": receipt["cost"],
            }
        )
    arm = "finite_grid_dp"
    checkpoint = {
        "schema": "hepta.native-readout-objective.control.v1",
        "seed": 991,
        "arm": arm,
    }
    checkpoint_path = output / "checkpoints" / "991" / f"{arm}.json"
    identity = save_json(checkpoint_path, checkpoint)
    result = run_context(
        diagnostic[0],
        seed=991,
        phase="diagnostic",
        paths=4,
        arm=arm,
        checkpoint_sha256=identity,
    )
    path = output / "records" / f"{arm}.jsonl.gz"
    shard = write_records(path, result["records"])
    shard["path"] = str(path.relative_to(output))
    results.append(
        {
            "arm": arm,
            "checkpoint": {
                "path": str(checkpoint_path.relative_to(output)),
                "sha256": identity,
            },
            "shard": shard,
            "counts": result["counts"],
        }
    )
    panel = same_state_panel(output, binary, 991, selected, context_count=1, paths=2)
    summary = {
        "schema": "hepta.native-readout-objective.native-smoke.v1",
        "seed": 991,
        "native_binary_sha256": sha(Path(binary).read_bytes()),
        "registered_confirmation_accessed": False,
        "episodes": 16,
        "arms": results,
        "diagnostic_panel": panel,
        "cost": meter.finish(),
    }
    save_json(output / "SUMMARY.json", summary)
    return summary


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--native-binary", type=Path, required=True)
    args = parser.parse_args()
    result = run(args.output, args.native_binary)
    print(
        json.dumps(
            {
                "episodes": result["episodes"],
                "confirmation_accessed": False,
                "native_binary_sha256": result["native_binary_sha256"],
            }
        )
    )
