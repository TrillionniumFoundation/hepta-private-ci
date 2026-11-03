"""Bind v3 experiments to exact code, protocol, data, and native source bytes."""

from datetime import datetime, timezone
import json
from pathlib import Path, PurePosixPath
import re
import subprocess

from v2.evidence import (
    checked_path,
    fingerprint,
    source_snapshot,
    verify_snapshot,
    write_json,
)
from .evidence_checks import verify_stage_data


PACKAGE = "qualification/memory-cell-v3"
QUALIFICATIONS = (
    "qualification/memory-cell-research",
    "qualification/memory-cell-v2",
    PACKAGE,
)
NATIVE = tuple(
    "codex-rs/" + name for name in ("hepta-types", "hepta-infer-core", "hepta-neuron")
)
EXTRA = (
    "codex-rs/Cargo.toml",
    "codex-rs/Cargo.lock",
    "codex-rs/rust-toolchain.toml",
    "codex-rs/.config/nextest.toml",
    "codex-rs/rustfmt.toml",
    "codex-rs/clippy.toml",
    "justfile",
    "scripts/run-nextest.py",
)
HEX40 = re.compile(r"[0-9a-f]{40}")


def inventory(root):
    root = Path(root)
    if root.is_symlink() or not root.is_dir():
        raise ValueError("evidence root must be an ordinary directory")
    result = []
    for path in root.rglob("*"):
        if path.is_symlink():
            raise ValueError("symlinks are not evidence files")
        if path.is_file():
            result.append(path.relative_to(root).as_posix())
    return sorted(result)


def source_member(name):
    path = PurePosixPath(name)
    if any(
        part in {"results", "validation", "analyses", "__pycache__", ".ruff_cache"}
        for part in path.parts
    ):
        return False
    if name in EXTRA:
        return True
    if any(name.startswith(prefix + "/") for prefix in NATIVE):
        return True
    if any(name.startswith(prefix + "/") for prefix in QUALIFICATIONS):
        return (
            path.suffix == ".py"
            or path.name
            in {
                "PROTOCOL.json",
                "MODEL_SOURCE.json",
                "requirements.txt",
                "requirements-report.txt",
            }
            or name.startswith(PACKAGE + "/sources/")
            or name.startswith(QUALIFICATIONS[1] + "/sources/")
        )
    return False


def source_identity(repo, commit=None):
    repo = Path(repo).resolve()
    commit = (
        commit
        or subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=repo, text=True
        ).strip()
    )
    if not HEX40.fullmatch(commit):
        raise ValueError("exact forty-character source commit required")
    names = list(EXTRA)
    for prefix in (*QUALIFICATIONS, *NATIVE):
        names.extend(
            prefix + "/" + relative
            for relative in inventory(repo / prefix)
            if source_member(prefix + "/" + relative)
        )
    return {
        "schema": "memory-cell-v3.source.v1",
        "commit": commit,
        "files": {
            name: fingerprint(checked_path(repo, name).read_bytes())
            for name in sorted(set(names))
        },
    }


def verify_sources(identity, repo, *, development=False, current_worktree=True):
    if identity.get("schema") != "memory-cell-v3.source.v1" or not HEX40.fullmatch(
        identity.get("commit", "")
    ):
        raise ValueError("invalid source identity")
    if current_worktree and source_identity(repo, identity["commit"]) != identity:
        raise ValueError("source bytes or inventory changed during execution")
    if not development:
        names = subprocess.check_output(
            [
                "git",
                "ls-tree",
                "-r",
                "--name-only",
                identity["commit"],
                "--",
                *QUALIFICATIONS,
                *NATIVE,
                *EXTRA,
            ],
            cwd=repo,
            text=True,
        ).splitlines()
        if {name for name in names if source_member(name)} != set(identity["files"]):
            raise ValueError("frozen source inventory differs from claimed commit")
        for name, expected in identity["files"].items():
            actual = subprocess.check_output(
                ["git", "show", f"{identity['commit']}:{name}"], cwd=repo
            )
            if fingerprint(actual) != expected:
                raise ValueError(f"frozen source bytes differ: {name}")
    return {
        "source_commit": identity["commit"],
        "source_files": len(identity["files"]),
        "commit_binding": "uncommitted-development"
        if development
        else "exact-committed-bytes",
    }


def seal_run(directory, identity):
    directory = Path(directory)
    names = inventory(directory)
    if "MANIFEST.json" in names:
        raise ValueError("an evidence seal cannot be overwritten")
    manifest = {
        "schema": "memory-cell-v3.evidence.v1",
        "source_commit": identity["commit"],
        "source_identity": fingerprint(
            (directory / "source_identity.json").read_bytes()
        ),
        "files": {
            name: fingerprint(checked_path(directory, name).read_bytes())
            for name in names
        },
        "completed_at_utc": datetime.now(timezone.utc).isoformat(),
        "integrity_does_not_establish_efficacy": True,
    }
    write_json(directory / "MANIFEST.json", manifest)
    return fingerprint((directory / "MANIFEST.json").read_bytes())


def verify_run(directory, repo, *, allow_failed=False):
    directory = Path(directory)
    manifest = json.loads(checked_path(directory, "MANIFEST.json").read_text())
    if manifest.get("schema") != "memory-cell-v3.evidence.v1":
        raise ValueError("unknown evidence schema")
    if set(inventory(directory)) - {"MANIFEST.json"} != set(manifest["files"]):
        raise ValueError("evidence file inventory differs")
    for name, expected in manifest["files"].items():
        if fingerprint(checked_path(directory, name).read_bytes()) != expected:
            raise ValueError(f"evidence byte mismatch: {name}")
    raw = checked_path(directory, "source_identity.json").read_bytes()
    identity = json.loads(raw)
    if (
        fingerprint(raw) != manifest["source_identity"]
        or identity["commit"] != manifest["source_commit"]
    ):
        raise ValueError("source identity is not bound by the seal")
    verify_snapshot(checked_path(directory, "source_snapshot.zip"), identity)
    environment = json.loads(checked_path(directory, "environment.json").read_text())
    if environment["mode"] not in {"development_only", "frozen_protocol_research"}:
        raise ValueError("unknown execution mode")
    development = environment["mode"] == "development_only"
    # Historical evidence is verified against its commit/snapshot, not whatever
    # source changes have been made since that run.
    source_check = verify_sources(
        identity, repo, development=development, current_worktree=False
    )
    protocol_raw = checked_path(directory, "protocol.json").read_bytes()
    if fingerprint(protocol_raw) != identity["files"][PACKAGE + "/PROTOCOL.json"]:
        raise ValueError("executed protocol differs from the bound source")
    protocol = json.loads(protocol_raw)
    if not protocol["stages"] or len(set(protocol["stages"])) != len(
        protocol["stages"]
    ):
        raise ValueError("invalid protocol stage inventory")
    seeds = protocol["development_seeds"] if development else protocol["seeds"]
    if seeds != environment["selected_seeds"]:
        raise ValueError("selected seeds differ from protocol mode")
    requested = (
        protocol["stages"] if environment["stage"] == "all" else [environment["stage"]]
    )
    if any(stage not in protocol["stages"] for stage in requested):
        raise ValueError("unknown requested experiment stage")
    status = json.loads(checked_path(directory, "execution_status.json").read_text())
    completed = status["completed_stages"]
    if completed != requested[: len(completed)] or status["execution"] not in {
        "completed",
        "failed",
        "aborted",
    }:
        raise ValueError("invalid terminal execution status")
    success = status["execution"] == "completed"
    results = json.loads(
        checked_path(
            directory, "results.json" if success else "partial_results.json"
        ).read_text()
    )
    if set(results) != set(completed) or (success and completed != requested):
        raise ValueError("completed stage inventory differs from results")
    for stage, result in results.items():
        if (
            result["selected_seeds"] != seeds
            or result["development_only"] != development
            or result["source_commit"] != identity["commit"]
        ):
            raise ValueError(f"result seed/mode/source binding differs: {stage}")
        verify_stage_data(
            stage, result.get("data"), directory, protocol, identity, seeds, development
        )
    if not success and not allow_failed:
        raise ValueError("run did not complete")
    return {
        **source_check,
        "verified": True,
        "execution": status["execution"],
        "output_files": len(manifest["files"]),
        "output_bytes": sum(info["bytes"] for info in manifest["files"].values()),
        "manifest": fingerprint((directory / "MANIFEST.json").read_bytes()),
        "development_only": development,
        "verified_stages": completed,
    }


__all__ = [
    "fingerprint",
    "source_identity",
    "source_snapshot",
    "verify_sources",
    "seal_run",
    "verify_run",
    "write_json",
]
