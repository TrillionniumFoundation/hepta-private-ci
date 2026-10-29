"""Fixed study dimensions, immutable files, and source-bound native bridges."""

import json
from pathlib import Path

from experiments.continuous_boundary_flow.common import (
    canonical,
    save_json,
    sha,
    write_records,
)
from experiments.continuous_boundary_flow.native.adapter import NativeBridge
from experiments.continuous_boundary_policy.common import CostMeter

PACKAGE = Path(__file__).resolve().parent
REPOSITORY = PACKAGE.parent.parent
SEEDS = [
    3301,
    3307,
    3313,
    3319,
    3323,
    3329,
    3331,
    3343,
    3347,
    3359,
    3361,
    3371,
    3373,
    3389,
    3391,
    3407,
]
ARMS = ["ridge_reference", "iterative_q_mse", "policy_regret"]
ALL_ARMS = ARMS + ["finite_grid_dp"]
CANDIDATES = [
    {"learning_rate": lr, "native_ridge": ridge, "fixed_boundary": 0.65}
    for lr, ridge in [(0.005, 0.001), (0.02, 0.01), (0.05, 0.1)]
]
REMOTE = "refs/remotes/origin/research/continuous-boundary-flow-20261028"


def read_json(path):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("Duplicate JSON key")
            result[key] = value
        return result

    def reject(value):
        raise ValueError(f"Nonfinite JSON token: {value}")

    return json.loads(
        Path(path).read_bytes(), object_pairs_hook=unique, parse_constant=reject
    )


def protocol():
    value = read_json(PACKAGE / "PROTOCOL.json")
    expected = {
        "train_contexts_per_seed": 12,
        "train_paths_per_context": 8,
        "development_contexts_per_seed": 8,
        "development_paths_per_context": 8,
        "confirmation_contexts_per_split_per_seed": 8,
        "confirmation_paths_per_context": 16,
        "confirmation_splits": ["test_id", "test_ood"],
        "split_weights": [0.5, 0.5],
        "grid_states": 64,
        "grid_upper": 4.8,
    }
    if (
        value["planned_seeds"] != SEEDS
        or [a["name"] for a in value["arms"]] != ARMS
        or value["controls"] != ["finite_grid_dp"]
        or any(value["data_plan"].get(k) != v for k, v in expected.items())
    ):
        raise ValueError("Executable study dimensions differ from protocol")
    settings = value["matched_iterative_training"]
    if (
        settings["updates"] != 120
        or settings["coefficient_abs_bound"] != 7.5
        or settings["regularization"] != 1e-4
        or settings["learning_rate_candidates"]
        != [c["learning_rate"] for c in CANDIDATES]
    ):
        raise ValueError("Executable training budget differs from protocol")
    return value


def append_cost(output, row):
    with (Path(output) / "costs.jsonl").open("ab") as stream:
        stream.write(canonical(row) + b"\n")


def scientific_files(root):
    root = Path(root)
    files = {}
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root)
        if "host" in relative.parts or "hosts" in relative.parts:
            continue
        if path.is_symlink():
            raise ValueError("Scientific evidence cannot contain symbolic links")
        if path.is_file():
            files[str(relative)] = sha(path.read_bytes())
    return files


def open_bridge(binary, root, source=None):
    bridge = NativeBridge(
        binary,
        root,
        expected_binary_sha256=None
        if source is None
        else source["native_binary_sha256"],
    )
    if source is not None and (
        bridge.identity["source_manifest_digest"]
        != source["native_source_manifest_sha256"]
        or bridge.identity["source_commit"]
        != "5898cd8b0f724c3152b6cc52856721f72e5e08be"
        or bridge.identity["owner_authority"] != "DENY_ALL"
    ):
        bridge.close()
        raise ValueError("Native executable source/authority identity mismatch")
    return bridge


def context_file(output, seed, phase, contexts):
    return save_json(
        Path(output) / "contexts" / str(seed) / f"{phase}.json",
        {
            "seed": seed,
            "phase": phase,
            "contexts": [
                {
                    "id": c["id"],
                    "index": c["index"],
                    "spec": c["spec"],
                    "model_build_cost": c["model_build_cost"],
                    "planning_cost": c["planning_cost"],
                    "dp_sha256": sha(c["dp"]["q"].tobytes()),
                }
                for c in contexts
            ],
        },
    )
