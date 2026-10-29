"""Independent phase, publication, source, artifact and context bindings."""

from pathlib import Path
import subprocess

import numpy as np

from .audit_core import (
    SEEDS,
    checked_file,
    expected_specs,
    read,
    reference,
    require,
    sha,
    source_commit,
    strict_json,
    verify_protocol,
)

PACKAGE = "experiments/native_readout_objective"
REMOTE = "refs/remotes/origin/research/continuous-boundary-flow-20261028"
BASE = "5898cd8b0f724c3152b6cc52856721f72e5e08be"


def inventory(root):
    """Operational native-host directories are the only non-evidence exclusions."""
    files = {}
    for path in root.rglob("*"):
        require(not path.is_symlink(), "Evidence may not contain symlinks")
        if not path.is_file():
            continue
        relative = path.relative_to(root)
        parts = relative.parts
        if "host" in parts or "hosts" in parts:
            allowed = (
                parts[0] == "hosts"
                and len(parts) > 3
                or parts[0] == "datasets"
                and len(parts) > 3
                and parts[2] == "host"
                or parts[0] in {"training", "diagnostics"}
                and len(parts) > 4
                and parts[3] == "host"
            )
            require(allowed, "Undeclared host-directory artifact exclusion")
            continue
        files[str(relative)] = sha(path.read_bytes())
    return files


def exact_manifest(root, expected):
    files = inventory(root)
    require(
        files == expected,
        "Manifest is incomplete, changed, or contains extra unlisted files",
    )
    return files


def verify_bindings(root, repository, confirmed=True):
    protocol = read(root, "PROTOCOL.json")
    verify_protocol(protocol)
    require(
        protocol["status"] == "FROZEN_BEFORE_TRAINING", "Study protocol was not frozen"
    )
    source, environment = read(root, "SOURCE_SEAL.json"), read(root, "ENVIRONMENT.json")
    require(
        source["schema"] == "hepta.native-readout-objective.source-seal.v1"
        and environment["schema"] == "hepta.native-readout-objective.environment.v1"
        and environment["publication_remote_ref"] == REMOTE,
        "Source/environment identity changed",
    )
    for name, key in (
        ("PROTOCOL.json", "protocol_sha256"),
        ("SOURCE_SEAL.json", "source_seal_sha256"),
    ):
        raw = checked_file(root, name, environment[key]).read_bytes()
        source_commit(
            repository,
            environment["publication_commit"],
            f"{PACKAGE}/{name}",
            raw,
            REMOTE,
        )
        require(
            (repository / PACKAGE / name).read_bytes() == raw,
            "Current frozen protocol/source differs from published study",
        )
    inherited = repository / "experiments/continuous_boundary_policy/SOURCE_SEAL.json"
    prior = strict_json(inherited.read_bytes())
    require(
        source["parent_source_seal_sha256"] == sha(inherited.read_bytes())
        and all(
            source["source_files"].get(k) == v for k, v in prior["source_files"].items()
        ),
        "Previously sealed scientific source was not preserved",
    )
    expected_new = {
        str(p.relative_to(repository)) for p in (repository / PACKAGE).rglob("*.py")
    }
    expected_new |= {
        f"{PACKAGE}/{name}"
        for name in (
            "PROTOCOL.json",
            "native/BUILD_RECEIPT.json",
            "native/SOURCE_MANIFEST.json",
        )
    }
    require(
        set(source["source_files"]) == set(prior["source_files"]) | expected_new,
        "Source seal omits or adds undeclared scientific files",
    )
    for path, identity in source["source_files"].items():
        raw = checked_file(repository, path, identity).read_bytes()
        source_commit(repository, environment["publication_commit"], path, raw)
    build = strict_json(
        checked_file(
            repository,
            f"{PACKAGE}/native/BUILD_RECEIPT.json",
            source["native_build_receipt_sha256"],
        ).read_bytes()
    )
    native_manifest = strict_json(
        checked_file(
            repository,
            f"{PACKAGE}/native/SOURCE_MANIFEST.json",
            source["native_source_manifest_sha256"],
        ).read_bytes()
    )
    require(
        build["source_sha256"] == native_manifest
        and build["base_commit"] == BASE
        and build["native_rust_sources_unmodified"] is True
        and build["external_dependencies_match_original_lock"] is True
        and build["binary_sha256"]
        == source["native_binary_sha256"]
        == environment["native_binary_sha256"]
        and source["native_source_manifest_sha256"]
        == environment["native_source_manifest_sha256"],
        "Original native build identity mismatch",
    )
    require(
        read(root, "TRAINING_STARTED.json")
        == {"schema": "hepta.native-readout-objective.phase.v1", "phase": "training"},
        "Training phase marker changed",
    )
    selection = read(root, "SELECTION_SEAL.json")
    require(
        selection["schema"] == "hepta.native-readout-objective.selection.v1"
        and selection["confirmation_generated"] is False,
        "Selection was not sealed before confirmation",
    )
    for key in ("protocol_sha256", "source_seal_sha256", "native_binary_sha256"):
        require(
            selection[key] == environment[key],
            "Selection changed a frozen study identity",
        )
    for relative, identity in selection["training_files"].items():
        checked_file(root, relative, identity)
    prefix = selection["training_costs_prefix_bytes"]
    costs = (root / "costs.jsonl").read_bytes()
    require(
        type(prefix) is int
        and 0 < prefix <= len(costs)
        and costs[:prefix].endswith(b"\n")
        and sha(costs[:prefix]) == selection["training_costs_prefix_sha256"],
        "Training costs changed after selection",
    )
    files, manifest = inventory(root), None
    if confirmed:
        external, manifest = (
            read(root, "EXTERNAL_SELECTION.json"),
            read(root, "MANIFEST.json"),
        )
        require(
            external["schema"] == "hepta.native-readout-objective.external-selection.v1"
            and external["selection_seal_sha256"]
            == sha((root / "SELECTION_SEAL.json").read_bytes())
            and external["confirmation_started_after_publication"] is True,
            "Confirmation lacks the frozen published selection",
        )
        source_commit(
            repository,
            external["selection_commit"],
            f"{PACKAGE}/evidence/SELECTION_SEAL.json",
            (root / "SELECTION_SEAL.json").read_bytes(),
            REMOTE,
        )
        subprocess.run(
            [
                "git",
                "merge-base",
                "--is-ancestor",
                environment["publication_commit"],
                external["selection_commit"],
            ],
            cwd=repository,
            check=True,
            capture_output=True,
        )
        require(
            manifest["schema"] == "hepta.native-readout-objective.manifest.v1"
            and manifest["expected_episodes"] == 16384
            and manifest["selection_seal_sha256"] == external["selection_seal_sha256"]
            and all(
                manifest[k] == environment[k]
                for k in ("protocol_sha256", "source_seal_sha256")
            ),
            "Final manifest identity or sample budget changed",
        )
        exact_manifest(
            root,
            {
                **manifest["files"],
                "MANIFEST.json": sha((root / "MANIFEST.json").read_bytes()),
            },
        )
    else:
        exact_manifest(
            root,
            {
                **selection["training_files"],
                "SELECTION_SEAL.json": sha((root / "SELECTION_SEAL.json").read_bytes()),
                "costs.jsonl": selection["training_costs_prefix_sha256"],
            },
        )
        require(
            len(costs) == prefix, "Confirmation costs exist before published selection"
        )
    return protocol, source, environment, selection, manifest, files


def verify_contexts(root, seeds=SEEDS, phases=None):
    if phases is None:
        phases = {
            "training": 12,
            "development": 8,
            "test_id": 8,
            "test_ood": 8,
            "diagnostic": 4,
        }
    references = {}
    for seed in seeds:
        for phase, count in phases.items():
            saved = read(root, f"contexts/{seed}/{phase}.json")
            require(
                saved["seed"] == seed
                and saved["phase"] == phase
                and len(saved["contexts"]) == count,
                "Task context schedule mismatch",
            )
            for index, (row, expected) in enumerate(
                zip(saved["contexts"], expected_specs(seed, phase, count))
            ):
                require(
                    row["id"] == f"{seed}.{phase}.context{index}"
                    and row["index"] == index
                    and row["spec"] == expected,
                    "Task parameters disagree with frozen phase stream",
                )
                ref = reference(expected)
                require(
                    sha(ref["q"].tobytes()) == row["dp_sha256"],
                    "Independent DP teacher digest mismatch",
                )
                references[seed, phase, index] = ref
                for name in ("model_build_cost", "planning_cost"):
                    require(
                        all(
                            isinstance(row[name][k], (int, float))
                            and np.isfinite(row[name][k])
                            and row[name][k] >= 0
                            for k in ("wall_seconds", "cpu_seconds")
                        ),
                        "Invalid shared boundary/DP/model cost",
                    )
    return references
