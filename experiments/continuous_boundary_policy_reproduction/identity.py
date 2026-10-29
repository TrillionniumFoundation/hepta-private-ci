"""Fail-closed publication, executable, immutable-run and phase bindings."""

from pathlib import Path
import platform
import re
import subprocess
import sys

import numpy as np
import scipy

from experiments.continuous_boundary_policy.audit_integrity import (
    checked_file,
    read_json,
)
from experiments.continuous_boundary_policy.audit_math import require
from experiments.continuous_boundary_policy.common import (
    ARMS,
    CONTROLS,
    SEEDS,
    save_json,
    sha,
)
from .sources import (
    BINARY_SHA,
    IDENTITY_FILES,
    PACKAGE,
    REPOSITORY,
    verify_plan,
    verify_source,
)

REMOTE = "refs/remotes/origin/research/continuous-boundary-flow-20261028"
SELECTION_PATH = (
    "experiments/continuous_boundary_policy_reproduction/evidence/SELECTION_SEAL.json"
)
IDENTITY_KEYS = {
    "PROTOCOL.json": "protocol_sha256",
    "SOURCE_SEAL.json": "source_seal_sha256",
    "REPRODUCTION_PLAN.json": "reproduction_plan_sha256",
}
INITIAL_FILES = {
    *IDENTITY_FILES,
    "ENVIRONMENT.json",
    "costs.jsonl",
    "phases/INITIALIZED.json",
}


def verify_publication(commit, relative, expected, repository=REPOSITORY):
    require(
        isinstance(commit, str) and re.fullmatch(r"[0-9a-f]{40}", commit) is not None,
        "A full published Git commit identity is required",
    )
    require(
        not Path(relative).is_absolute() and ".." not in Path(relative).parts,
        "Unsafe publication path",
    )
    subprocess.run(
        ["git", "merge-base", "--is-ancestor", commit, REMOTE],
        cwd=repository,
        check=True,
        capture_output=True,
    )
    raw = subprocess.check_output(
        ["git", "show", f"{commit}:{relative}"], cwd=repository
    )
    require(raw == expected, "Published artifact differs from frozen evidence")


def verify_binaries(binaries, expected=BINARY_SHA):
    require(
        isinstance(binaries, dict) and set(binaries) == {"native", "score"},
        "Both exact native and score executable identities are required",
    )
    for key, path in binaries.items():
        require(
            path is not None and Path(path).is_file(), "Native executable is missing"
        )
        require(
            sha(Path(path).read_bytes()) == expected[key] == BINARY_SHA[key],
            "Frozen native binary changed",
        )


def initialize(output, binaries, publication_commit, repository=REPOSITORY):
    """Validate all published identities before creating a fresh output directory."""
    output, repository = Path(output), Path(repository)
    require(
        not output.exists(),
        "Run output already exists; partial runs cannot be resumed or replaced",
    )
    package = repository / PACKAGE.relative_to(REPOSITORY)
    source = verify_source(read_json(package, "SOURCE_SEAL.json"), repository)
    verify_binaries(
        binaries, {key: source[f"{key}_binary_sha256"] for key in BINARY_SHA}
    )
    artifacts = {name: (package / name).read_bytes() for name in IDENTITY_FILES}
    for name, raw in artifacts.items():
        verify_publication(
            publication_commit,
            str((package / name).relative_to(repository)),
            raw,
            repository,
        )
    output.mkdir(parents=True, exist_ok=False)
    for name, raw in artifacts.items():
        with (output / name).open("xb") as handle:
            handle.write(raw)
    with (output / "costs.jsonl").open("xb"):
        pass
    environment = {
        "python": sys.version,
        "numpy": np.__version__,
        "scipy": scipy.__version__,
        "platform": platform.platform(),
        "processor": platform.processor(),
        "cpu_model": next(
            (
                line.split(":", 1)[1].strip()
                for line in Path("/proc/cpuinfo").read_text().splitlines()
                if line.startswith("model name")
            ),
            "unavailable",
        )
        if Path("/proc/cpuinfo").exists()
        else "unavailable",
        "publication_commit": publication_commit,
        "publication_remote": REMOTE,
        "study_kind": "same_seed_rebuilt_binary_reproduction",
        "binary_sha256": dict(BINARY_SHA),
        "binary_paths": {
            key: str(Path(value).resolve()) for key, value in binaries.items()
        },
        **{IDENTITY_KEYS[name]: sha(raw) for name, raw in artifacts.items()},
    }
    save_json(output / "ENVIRONMENT.json", environment)
    mark_phase(output, "INITIALIZED")
    verify_frozen(output, binaries, repository)
    return environment


def verify_frozen(output, binaries=None, repository=REPOSITORY):
    output, repository = Path(output), Path(repository)
    env = read_json(output, "ENVIRONMENT.json")
    package = repository / PACKAGE.relative_to(REPOSITORY)
    require(
        env["publication_remote"] == REMOTE
        and env["study_kind"] == "same_seed_rebuilt_binary_reproduction",
        "Run identity or publication branch changed",
    )
    for name in IDENTITY_FILES:
        raw = (output / name).read_bytes()
        require(
            sha(raw) == env[IDENTITY_KEYS[name]],
            "Immutable experiment identity changed",
        )
        require(
            raw == (package / name).read_bytes(),
            "Run differs from current frozen reproduction source",
        )
        verify_publication(
            env["publication_commit"],
            str((package / name).relative_to(repository)),
            raw,
            repository,
        )
    source = verify_source(read_json(output, "SOURCE_SEAL.json"), repository)
    verify_plan((output / "REPRODUCTION_PLAN.json").read_bytes())
    require(
        env["binary_sha256"]
        == BINARY_SHA
        == {key: source[f"{key}_binary_sha256"] for key in BINARY_SHA},
        "Environment/build/source executable identities differ",
    )
    if binaries is not None:
        verify_binaries(binaries, env["binary_sha256"])
    return env


def mark_phase(output, phase):
    return save_json(
        Path(output) / "phases" / f"{phase}.json",
        {
            "schema": "hepta.boundary-policy-reproduction.phase.v1",
            "phase": phase,
            "source_seal_sha256": sha((Path(output) / "SOURCE_SEAL.json").read_bytes()),
        },
    )


def verify_marker(output, phase):
    marker = read_json(Path(output), f"phases/{phase}.json")
    require(
        marker
        == {
            "schema": "hepta.boundary-policy-reproduction.phase.v1",
            "phase": phase,
            "source_seal_sha256": sha((Path(output) / "SOURCE_SEAL.json").read_bytes()),
        },
        "Phase marker identity changed",
    )


def actual_files(output):
    return {
        str(p.relative_to(output))
        for p in output.rglob("*")
        if p.is_file()
        and "host" not in p.relative_to(output).parts
        and "confirmation_hosts" not in p.relative_to(output).parts
    }


def begin_training(output):
    output = Path(output)
    verify_marker(output, "INITIALIZED")
    require(
        {p.name for p in output.iterdir()}
        == {"phases", *IDENTITY_FILES, "ENVIRONMENT.json", "costs.jsonl"}
        and actual_files(output) == INITIAL_FILES
        and (output / "costs.jsonl").read_bytes() == b"",
        "Training requires a fresh initialized run; partial/repeated phases are forbidden",
    )
    mark_phase(output, "TRAINING_STARTED")


def verify_preconfirmation(output):
    output = Path(output)
    for phase in ("INITIALIZED", "TRAINING_STARTED", "TRAINING_COMPLETE"):
        verify_marker(output, phase)
    require(
        not any(
            (output / name).exists()
            for name in (
                "confirmation_hosts",
                "shards",
                "EXTERNAL_SELECTION.json",
                "MANIFEST.json",
                "phases/CONFIRMATION_COMPLETE.json",
            )
        ),
        "Confirmation already started or confirmation artifacts exist",
    )
    selection = read_json(output, "SELECTION_SEAL.json")
    env = read_json(output, "ENVIRONMENT.json")
    require(
        selection["schema"] == "hepta.continuous-boundary-policy.selection.v1",
        "Selection schema changed",
    )
    for key in ("protocol_sha256", "source_seal_sha256"):
        require(selection[key] == env[key], "Selection identity changed")
    for key in BINARY_SHA:
        require(
            selection[f"{key}_binary_sha256"]
            == env["binary_sha256"][key]
            == BINARY_SHA[key],
            "Selection executable identity changed",
        )
    roster = [(row["seed"], row["arm"]) for row in selection["checkpoints"]]
    require(
        len(roster) == len(SEEDS) * len(ARMS + CONTROLS)
        and set(roster) == {(seed, arm) for seed in SEEDS for arm in ARMS + CONTROLS},
        "Incomplete or duplicate selected checkpoint roster",
    )
    require(
        "costs.jsonl" not in selection["training_files"],
        "Mutable costs must be bound by prefix",
    )
    expected = set(selection["training_files"]) | {"costs.jsonl", "SELECTION_SEAL.json"}
    require(
        actual_files(output) == expected,
        "Unexpected preconfirmation artifact or partial confirmation exists",
    )
    require(
        INITIAL_FILES - {"costs.jsonl"} <= set(selection["training_files"]),
        "Selection omits initial identities",
    )
    for relative, identity in selection["training_files"].items():
        require(
            not any(
                part in {"shards", "confirmation_hosts"}
                for part in Path(relative).parts
            )
            and "test_id" not in relative
            and "test_ood" not in relative
            and "EXTERNAL_SELECTION" not in relative
            and "CONFIRMATION" not in relative,
            "Confirmation data entered selection",
        )
        checked_file(output, relative, identity)
    raw = (output / "costs.jsonl").read_bytes()
    require(
        len(raw) == selection["training_costs_prefix_bytes"]
        and sha(raw) == selection["training_costs_prefix_sha256"],
        "Training costs changed after selection",
    )
    return selection
