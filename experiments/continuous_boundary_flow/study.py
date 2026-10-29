"""Frozen train/development selection, then complete paired confirmation."""

import argparse
import json
from pathlib import Path
import platform
import shutil
import sys

import numpy as np
import scipy

from .common import (
    ARMS,
    CONTROLS,
    SEEDS,
    CostWindow,
    canonical,
    protocol,
    save_json,
    sha,
    write_records,
)
from .execution import behavior_data, run_context
from .models import fit_boundary
from .native.adapter import NativeBridge
from .scenarios import load_contexts
from .training import train_arm

PACKAGE = Path(__file__).resolve().parent


def append_cost(output, row):
    with (output / "costs.jsonl").open("ab") as stream:
        stream.write(canonical(row) + b"\n")


def initialize(output, binary):
    output.mkdir(parents=True, exist_ok=False)
    frozen = (PACKAGE / "PROTOCOL.json").read_bytes()
    if json.loads(frozen) != protocol():
        raise ValueError("Protocol JSON and executable constants differ")
    (output / "protocol.json").write_bytes(frozen)
    (output / "costs.jsonl").touch()
    source = json.loads((PACKAGE / "SOURCE_SEAL.json").read_text())
    for relative, digest in source["source_files"].items():
        if sha((PACKAGE.parent.parent / relative).read_bytes()) != digest:
            raise ValueError(f"Frozen scientific source changed: {relative}")
    shutil.copyfile(PACKAGE / "SOURCE_SEAL.json", output / "SOURCE_SEAL.json")
    save_json(
        output / "ENVIRONMENT.json",
        {
            "python": sys.version,
            "numpy": np.__version__,
            "scipy": scipy.__version__,
            "platform": platform.platform(),
            "native_binary_sha256": sha(Path(binary).read_bytes()),
            "protocol_sha256": sha(frozen),
            "source_seal_sha256": sha((PACKAGE / "SOURCE_SEAL.json").read_bytes()),
            "scope": "controlled known-model finite-window task; no production admission",
        },
    )


def save_histories(output, seed, contexts, histories):
    path = output / "datasets" / str(seed) / "training.npz"
    path.parent.mkdir(parents=True, exist_ok=True)
    arrays = {}
    for i, history in enumerate(histories):
        for name in history[0]:
            arrays[f"context_{i}_{name}"] = np.asarray([r[name] for r in history])
    with path.open("xb") as stream:
        np.savez_compressed(stream, **arrays)
    save_json(
        path.with_suffix(".json"),
        {
            "path": str(path.relative_to(output)),
            "sha256": sha(path.read_bytes()),
            "phase": "training",
            "seed": seed,
            "contexts": [c["spec"] for c in contexts],
            "teacher": "same public-model dynamic programming targets for all learned readouts",
            "behavior": "independent 20 percent repair, otherwise keep; never learns from confirmation",
        },
    )


def verify_frozen(output, binary):
    source_bytes = (output / "SOURCE_SEAL.json").read_bytes()
    environment = json.loads((output / "ENVIRONMENT.json").read_text())
    if sha(source_bytes) != environment["source_seal_sha256"]:
        raise ValueError("Source seal changed between phases")
    if sha(Path(binary).read_bytes()) != environment["native_binary_sha256"]:
        raise ValueError("Native binary changed between phases")
    if sha((output / "protocol.json").read_bytes()) != environment["protocol_sha256"]:
        raise ValueError("Protocol changed between phases")
    for relative, digest in json.loads(source_bytes)["source_files"].items():
        if sha((PACKAGE.parent.parent / relative).read_bytes()) != digest:
            raise ValueError(f"Frozen scientific source changed: {relative}")


def train(output, binary):
    verify_frozen(output, binary)
    frozen = json.loads((output / "protocol.json").read_text())
    if frozen != protocol():
        raise ValueError("The stored protocol changed")
    if (output / "SELECTION_SEAL.json").exists():
        raise ValueError("Training already frozen; do not refit after selection")
    checkpoints = []
    for seed in SEEDS:
        setup = CostWindow()
        train_contexts = load_contexts(seed, "training", frozen["train_contexts"])
        dev_contexts = load_contexts(
            seed, "development", frozen["development_contexts"]
        )
        histories = [
            behavior_data(c, seed, frozen["train_episodes_per_context"])
            for c in train_contexts
        ]
        boundary = fit_boundary(train_contexts)
        save_histories(output, seed, train_contexts, histories)
        save_json(
            output / "datasets" / str(seed) / "development_contexts.json",
            [c["spec"] for c in dev_contexts],
        )
        save_json(
            output / "datasets" / str(seed) / "direct_boundary_fit.json",
            {
                k: v.tolist() if isinstance(v, np.ndarray) else v
                for k, v in boundary.items()
            },
        )
        append_cost(
            output,
            {
                "phase": "solver_setup_training",
                "arm": "shared",
                "train_seed": seed,
                **setup.finish(),
                "contexts": len(train_contexts) + len(dev_contexts),
                "model_build_cpu_seconds": sum(
                    c["model_build_cost"]["cpu_seconds"]
                    for c in train_contexts + dev_contexts
                ),
                "dp_planning_cpu_seconds": sum(
                    c["planning_cost"]["cpu_seconds"]
                    for c in train_contexts + dev_contexts
                ),
                "cost_scope": "actual shared model/DP construction, behavior sampling and dataset write; charged once; sub-timers are included, not additive",
            },
        )
        for arm in ARMS:
            checkpoint, item, receipt = train_arm(
                output,
                binary,
                seed,
                arm,
                train_contexts,
                histories,
                dev_contexts,
                boundary,
                dev_paths=frozen["development_episodes_per_context"],
            )
            checkpoints.append(item)
            counter = receipt["native_process_cost"]["counters"]
            append_cost(
                output,
                {
                    "phase": "training_and_development",
                    "arm": arm,
                    "train_seed": seed,
                    **receipt["cost"],
                    "fits": len(receipt["candidates"]),
                    "actual_kernel_calls": counter["actual_kernel_calls"],
                    "actual_ndu_calls": counter["actual_ndu_calls"],
                    "wire_request_bytes": counter["request_bytes"],
                    "wire_response_bytes": counter["response_bytes"],
                    "cost_scope": "entire 12-candidate training and development, serialization, native startup/shutdown; no confirmation",
                },
            )
            print(
                json.dumps(
                    {
                        "phase": "trained",
                        "seed": seed,
                        "arm": arm,
                        "selected": checkpoint["candidate_index"],
                        "cpu": receipt["cost"]["python_cpu_seconds"]
                        + receipt["cost"]["completed_child_cpu_seconds"],
                    }
                ),
                flush=True,
            )
        for arm in CONTROLS:
            path = output / "checkpoints" / str(seed) / f"{arm}.json"
            digest = save_json(
                path,
                {
                    "schema": "hepta.continuous-boundary.reference.v1",
                    "arm": arm,
                    "seed": seed,
                    "trained_parameters": 0,
                    "algorithm": "frozen mathematical reference",
                },
            )
            checkpoints.append(
                {
                    "arm": arm,
                    "train_seed": seed,
                    "path": str(path.relative_to(output)),
                    "sha256": digest,
                }
            )
    # No test contexts or episode outcomes are created until every model is frozen.
    save_json(
        output / "SELECTION_SEAL.json",
        {
            "schema": "hepta.continuous-boundary.selection-seal.v1",
            "protocol_sha256": sha((output / "protocol.json").read_bytes()),
            "checkpoints": checkpoints,
            "profiles": {
                str(p.relative_to(output)): sha(p.read_bytes())
                for p in sorted((output / "training").glob("*/*/profiles/*.json"))
            },
            "confirmation_started": False,
        },
    )


def confirm(output, binary):
    verify_frozen(output, binary)
    frozen = json.loads((output / "protocol.json").read_text())
    if frozen != protocol():
        raise ValueError("Frozen confirmation protocol mismatch")
    selection_bytes = (output / "SELECTION_SEAL.json").read_bytes()
    selection = json.loads(selection_bytes)
    if selection["protocol_sha256"] != sha((output / "protocol.json").read_bytes()):
        raise ValueError("Selection was made against a different protocol")
    for item in selection["checkpoints"]:
        if sha((output / item["path"]).read_bytes()) != item["sha256"]:
            raise ValueError("Selected checkpoint changed")
    for path, digest in selection["profiles"].items():
        if sha((output / path).read_bytes()) != digest:
            raise ValueError("A frozen candidate profile changed")
    index = {(x["train_seed"], x["arm"]): x for x in selection["checkpoints"]}
    references, scenario_records = [], []
    for seed in SEEDS:
        for phase in ("test_id", "test_ood"):
            setup = CostWindow()
            contexts = load_contexts(
                seed, phase, frozen["confirmation_contexts_per_split"]
            )
            setup_cost = setup.finish()
            append_cost(
                output,
                {
                    "phase": "solver_setup_confirmation",
                    "arm": "shared",
                    "train_seed": seed,
                    "split": phase,
                    **setup_cost,
                    "contexts": len(contexts),
                    "model_build_cpu_seconds": sum(
                        c["model_build_cost"]["cpu_seconds"] for c in contexts
                    ),
                    "dp_planning_cpu_seconds": sum(
                        c["planning_cost"]["cpu_seconds"] for c in contexts
                    ),
                    "cost_scope": "actual shared public model and DP build; sub-timers included; standalone per-context planning charged to value arms and DP only",
                },
            )
            scenario_records.extend(
                {
                    "id": c["id"],
                    "spec": c["spec"],
                    "dp_initial_value": c["dp"]["initial_value"],
                    "diagnostics": c["model"].diagnostics,
                    "boundaries": c["dp"]["boundaries"],
                    "model_build_cost": c["model_build_cost"],
                    "planning_cost": c["planning_cost"],
                }
                for c in contexts
            )
            for arm in ARMS + CONTROLS:
                item = index[(seed, arm)]
                checkpoint = json.loads((output / item["path"]).read_text())
                bridge = None
                window = CostWindow()
                counters = {}
                records = []
                if arm in ARMS:
                    bridge = NativeBridge(
                        binary, output / "evaluation_hosts" / str(seed) / phase / arm
                    )
                    profile_sha = bridge.load_profile(
                        output / checkpoint["profile_path"],
                        checkpoint["profile_sha256"],
                    )
                else:
                    profile_sha = None
                try:
                    for context in contexts:
                        run = run_context(
                            context,
                            seed=seed,
                            phase=phase,
                            paths=frozen["confirmation_episodes_per_context"],
                            arm=arm,
                            checkpoint_sha256=item["sha256"],
                            bridge=bridge,
                            profile_sha=profile_sha,
                            candidate=checkpoint.get("candidate"),
                            boundary_weights=checkpoint.get("boundary_weights"),
                        )
                        records.extend(run["records"])
                        for k, v in run["counts"].items():
                            counters[k] = counters.get(k, 0) + int(v)
                finally:
                    native = None if bridge is None else bridge.close()
                execution_cost = window.finish()
                data_path = output / "episodes" / str(seed) / arm / f"{phase}.jsonl.gz"
                serialization = CostWindow()
                ref = write_records(data_path, records)
                ref["path"] = str(data_path.relative_to(output))
                references.append(ref)
                append_cost(
                    output,
                    {
                        "phase": "serialization",
                        "arm": arm,
                        "train_seed": seed,
                        "split": phase,
                        **serialization.finish(),
                        "bytes": data_path.stat().st_size,
                        "cost_scope": "lossless canonical raw-record compression and persistence only",
                    },
                )
                append_cost(
                    output,
                    {
                        "phase": "evaluation",
                        "arm": arm,
                        "train_seed": seed,
                        "split": phase,
                        **execution_cost,
                        **counters,
                        "cost_scope": "full causal sampled task and adapter plus native original kernel/NDU; source setup separately charged",
                        "native_process": native,
                    },
                )
                print(
                    json.dumps(
                        {
                            "phase": "confirmed",
                            "seed": seed,
                            "split": phase,
                            "arm": arm,
                            "episodes": len(records),
                            "kernels": counters["actual_kernel_calls"],
                        }
                    ),
                    flush=True,
                )
    save_json(output / "SCENARIOS.json", scenario_records)
    keys = (
        "arms",
        "seeds",
        "splits",
        "split_weights",
        "primary_pairs",
        "phase_ids",
        "message_price_per_byte",
        "minimum_effect",
    )
    manifest = {
        "schema": "hepta.continuous-boundary.study.v1",
        **{k: frozen[k] for k in keys},
        "protocol_sha256": sha((output / "protocol.json").read_bytes()),
        "selection_seal_sha256": sha(selection_bytes),
        "source_seal_sha256": sha((output / "SOURCE_SEAL.json").read_bytes()),
        "checkpoints": selection["checkpoints"],
        "records": references,
        "costs_sha256": sha((output / "costs.jsonl").read_bytes()),
        "grid_states": frozen["grid_states"],
        "grid_upper_domain": frozen["grid_upper_domain"],
        "risk_scope": "analytic action-conditioned probability on policy-visited states, not learned-head superiority",
        "cost_scope": "measured CPU and wall time, no energy; task/message-priced net utility is separate from total computation",
    }
    save_json(output / "manifest.json", manifest)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("stage", choices=["initialize", "train", "confirm"])
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--binary", required=True, type=Path)
    args = parser.parse_args()
    {"initialize": initialize, "train": train, "confirm": confirm}[args.stage](
        args.output.resolve(), args.binary.resolve()
    )


if __name__ == "__main__":
    main()
