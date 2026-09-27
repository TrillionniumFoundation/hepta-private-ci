#!/usr/bin/env python3
"""Create an immutable AuthBus exact-candidate qualification receipt."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RELEVANT_ROOTS = [
    "codex-rs/hepta-authbus",
    "codex-rs/hepta-authbus-p1-3-qualification",
    "codex-rs/hepta-evidence/src/authbus_outbox.rs",
    "codex-rs/hepta-evidence/src/authbus_store.rs",
    "codex-rs/hepta-agentd/src/authbus_dispatch.rs",
    "codex-rs/hepta-agentd/src/authbus_ingress.rs",
    "codex-rs/hepta-bao-adapter/src/https_consumer.rs",
    "docs/modules/auth.authbus",
]
ARTIFACT_TOKENS = ("authbus", "hepta_evidence", "hepta_agentd", "bao_adapter")


def run(*args: str) -> str:
    return subprocess.check_output(args, cwd=ROOT, text=True).strip()


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def aggregate(entries: list[tuple[str, str]]) -> str:
    digest = hashlib.sha256()
    for name, value in sorted(entries):
        digest.update(name.encode())
        digest.update(b"\0")
        digest.update(value.encode())
        digest.update(b"\n")
    return digest.hexdigest()


def files_under(relative: str) -> list[Path]:
    path = ROOT / relative
    if path.is_file():
        return [path]
    return sorted(
        candidate
        for candidate in path.rglob("*")
        if candidate.is_file() and "target" not in candidate.parts
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--test-log", action="append", default=[], type=Path)
    parser.add_argument("--artifact-root", type=Path, default=ROOT / "codex-rs/target")
    args = parser.parse_args()

    if subprocess.call(["git", "diff", "--quiet"], cwd=ROOT) != 0 or subprocess.call(
        ["git", "diff", "--cached", "--quiet"], cwd=ROOT
    ) != 0:
        raise SystemExit("tracked worktree is not clean")

    commit = run("git", "rev-parse", "HEAD")
    tree = run("git", "rev-parse", "HEAD^{tree}")
    source_entries: list[tuple[str, str]] = []
    for relative in RELEVANT_ROOTS:
        for path in files_under(relative):
            source_entries.append((path.relative_to(ROOT).as_posix(), sha256(path)))

    migration_entries = [
        (path.relative_to(ROOT).as_posix(), sha256(path))
        for path in sorted((ROOT / "codex-rs/hepta-authbus/migrations").glob("*.sql"))
    ]
    log_entries = [
        (path.name, sha256(path)) for path in args.test_log if path.is_file()
    ]
    artifact_entries: list[tuple[str, str]] = []
    if args.artifact_root.exists():
        for path in sorted(args.artifact_root.rglob("*")):
            if not path.is_file() or not any(token in path.name for token in ARTIFACT_TOKENS):
                continue
            artifact_entries.append((path.relative_to(args.artifact_root).as_posix(), sha256(path)))

    cargo_lock = ROOT / "codex-rs/Cargo.lock"
    receipt = {
        "schema": "hepta.authbus.exact-head-evidence.v1",
        "candidate": {"commit": commit, "tree": tree},
        "workflow": {
            "runId": os.environ.get("GITHUB_RUN_ID"),
            "runAttempt": os.environ.get("GITHUB_RUN_ATTEMPT"),
            "job": os.environ.get("GITHUB_JOB"),
            "event": os.environ.get("GITHUB_EVENT_NAME"),
            "ref": os.environ.get("GITHUB_REF"),
            "sha": os.environ.get("GITHUB_SHA"),
        },
        "digests": {
            "relevantSource": aggregate(source_entries),
            "schema": aggregate(migration_entries),
            "cargoLock": sha256(cargo_lock),
            "testLogs": aggregate(log_entries),
            "buildArtifacts": aggregate(artifact_entries),
        },
        "migrationFiles": [
            {"path": name, "sha256": digest} for name, digest in migration_entries
        ],
        "testLogs": [{"path": name, "sha256": digest} for name, digest in log_entries],
        "buildArtifactCount": len(artifact_entries),
        "toolchain": {
            "rustc": run("rustc", "--version"),
            "cargo": run("cargo", "--version"),
        },
        "trackedWorktreeClean": True,
        "activation": False,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
