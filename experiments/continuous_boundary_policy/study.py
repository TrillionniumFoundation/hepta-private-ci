"""Immutable source, training selection, and a new independent confirmation run."""

import argparse
import json
from pathlib import Path
import platform
import re
import subprocess
import shutil
import sys

import numpy as np
import scipy

from experiments.continuous_boundary_flow.common import write_records
from experiments.continuous_boundary_flow.execution import behavior_data
from experiments.continuous_boundary_flow.models import fit_boundary
from experiments.continuous_boundary_flow.native.adapter import NativeBridge
from experiments.continuous_boundary_flow.scenarios import load_contexts
from experiments.continuous_boundary_flow.study import save_histories
from .common import (
    ARMS,
    CONTROLS,
    PACKAGE,
    SEEDS,
    CostMeter,
    append_cost,
    canonical,
    protocol,
    save_json,
    sha,
)
from .execution import run_context
from .native.bridge import ScoreBridge
from .training import train_arm

REPOSITORY = PACKAGE.parent.parent


def freeze_source():
    """Called only after engineering tests and formatting, before any training."""
    protocol_path = PACKAGE / "PROTOCOL.json"
    protocol_path.write_bytes(canonical(protocol()) + b"\n")
    inherited_seal = json.loads(
        (PACKAGE.parent / "continuous_boundary_flow" / "SOURCE_SEAL.json").read_text()
    )
    inherited = inherited_seal["source_files"]
    files = {}
    for rel, expected in inherited.items():
        actual = sha((REPOSITORY / rel).read_bytes())
        if actual != expected:
            raise ValueError(f"Prior frozen scientific source changed: {rel}")
        files[rel] = actual
    for path in PACKAGE.rglob("*"):
        if path.is_file() and path.suffix in {".py", ".rs"}:
            files[str(path.relative_to(REPOSITORY))] = sha(path.read_bytes())
    files[str(protocol_path.relative_to(REPOSITORY))] = sha(protocol_path.read_bytes())
    old_receipt = inherited_seal["native_build_receipt_path"]
    if (
        sha((REPOSITORY / old_receipt).read_bytes())
        != inherited_seal["native_build_receipt_sha256"]
    ):
        raise ValueError("Prior native build receipt changed")
    files[old_receipt] = inherited_seal["native_build_receipt_sha256"]
    score_receipt_path = PACKAGE / "native/preflight/BUILD_RECEIPT.json"
    score_receipt = json.loads(score_receipt_path.read_text())
    manifest_path = PACKAGE / "native/preflight/SOURCE_MANIFEST.json"
    if sha(manifest_path.read_bytes()) != score_receipt["source_manifest_digest"]:
        raise ValueError("Score build manifest mismatch")
    for rel, expected in score_receipt["source_sha256"].items():
        if (
            rel.startswith("experiments/continuous_boundary_policy/")
            and files.get(rel) != expected
        ):
            raise ValueError(
                "Score binary was not built from current supplemental source"
            )
    for path in (score_receipt_path, manifest_path):
        files[str(path.relative_to(REPOSITORY))] = sha(path.read_bytes())
    target = PACKAGE / "SOURCE_SEAL.json"
    target.write_bytes(
        canonical(
            {
                "schema": "hepta.continuous-boundary-policy.source-seal.v1",
                "source_files": files,
                "native_binary_sha256": inherited_seal["native_binary_sha256"],
                "score_binary_sha256": score_receipt["binary_sha256"],
                "prior_source_seal_sha256": sha(
                    (
                        PACKAGE.parent / "continuous_boundary_flow" / "SOURCE_SEAL.json"
                    ).read_bytes()
                ),
            }
        )
        + b"\n"
    )
    return {
        "source_seal_sha256": sha(target.read_bytes()),
        "protocol_sha256": sha(protocol_path.read_bytes()),
        "files": len(files),
    }


def verify_publication(commit, relative, expected):
    """Require the exact artifact in a locally fetched remote-branch ancestor."""
    if not re.fullmatch(r"[0-9a-f]{40}", commit or ""):
        raise ValueError("A full published Git commit identity is required")
    remote = "refs/remotes/origin/research/continuous-boundary-flow-20261028"
    subprocess.run(
        ["git", "merge-base", "--is-ancestor", commit, remote],
        cwd=REPOSITORY,
        check=True,
        capture_output=True,
    )
    raw = subprocess.check_output(
        ["git", "show", f"{commit}:{relative}"], cwd=REPOSITORY
    )
    if raw != expected:
        raise ValueError("Published Git artifact does not match local frozen evidence")


def initialize(output, binaries, publication_commit):
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    for name in ("PROTOCOL.json", "SOURCE_SEAL.json"):
        verify_publication(
            publication_commit,
            str((PACKAGE / name).relative_to(REPOSITORY)),
            (PACKAGE / name).read_bytes(),
        )
        shutil.copyfile(PACKAGE / name, output / name)
    if json.loads((output / "PROTOCOL.json").read_text()) != protocol():
        raise ValueError("Protocol constants differ from published JSON")
    (output / "costs.jsonl").touch()
    source = json.loads((output / "SOURCE_SEAL.json").read_text())
    for key, path in binaries.items():
        if sha(Path(path).read_bytes()) != source[f"{key}_binary_sha256"]:
            raise ValueError(
                "Executable differs from the published source-bound build receipt"
            )
    save_json(
        output / "ENVIRONMENT.json",
        {
            "python": sys.version,
            "numpy": np.__version__,
            "scipy": scipy.__version__,
            "platform": platform.platform(),
            "publication_commit": publication_commit,
            "binary_sha256": {
                key: sha(Path(value).read_bytes()) for key, value in binaries.items()
            },
            "protocol_sha256": sha((output / "PROTOCOL.json").read_bytes()),
            "source_seal_sha256": sha((output / "SOURCE_SEAL.json").read_bytes()),
        },
    )
    verify_frozen(output, binaries)


def verify_frozen(output, binaries):
    output = Path(output)
    env = json.loads((output / "ENVIRONMENT.json").read_text())
    for name, key in (
        ("PROTOCOL.json", "protocol_sha256"),
        ("SOURCE_SEAL.json", "source_seal_sha256"),
    ):
        if sha((output / name).read_bytes()) != env[key]:
            raise ValueError("Immutable experiment identity changed")
    for rel, expected in json.loads((output / "SOURCE_SEAL.json").read_text())[
        "source_files"
    ].items():
        if sha((REPOSITORY / rel).read_bytes()) != expected:
            raise ValueError(f"Frozen source changed: {rel}")
    source = json.loads((output / "SOURCE_SEAL.json").read_text())
    for key, binary in binaries.items():
        if (
            env["binary_sha256"][key] != source[f"{key}_binary_sha256"]
            or sha(Path(binary).read_bytes()) != env["binary_sha256"][key]
        ):
            raise ValueError("Frozen native binary changed")


def store_contexts(output, seed, phase, contexts):
    save_json(
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


def train(output, binaries):
    output = Path(output)
    verify_frozen(output, binaries)
    if (output / "SELECTION_SEAL.json").exists():
        raise ValueError("Selection already sealed")
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
    if (output / "MANIFEST.json").exists():
        raise ValueError("Published selection commit and fresh confirmation required")
    selection_bytes = (output / "SELECTION_SEAL.json").read_bytes()
    selected = json.loads(selection_bytes)
    verify_publication(
        selection_commit,
        "experiments/continuous_boundary_policy/evidence/SELECTION_SEAL.json",
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


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("phase", choices=["freeze", "initialize", "train", "confirm"])
    parser.add_argument("--output", type=Path)
    parser.add_argument("--native-binary", type=Path)
    parser.add_argument("--score-binary", type=Path)
    parser.add_argument("--publication-commit")
    args = parser.parse_args()
    if args.phase == "freeze":
        print(json.dumps(freeze_source()))
        return
    binaries = {"native": args.native_binary, "score": args.score_binary}
    if args.phase == "initialize":
        initialize(args.output, binaries, args.publication_commit)
    elif args.phase == "train":
        train(args.output, binaries)
    else:
        confirm(args.output, binaries, args.publication_commit)


if __name__ == "__main__":
    main()
