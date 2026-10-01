#!/usr/bin/env python3
"""Create an immutable AuthBus exact-candidate qualification receipt."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import subprocess
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
RELEVANT_ROOTS = [
    ".github/workflows/authbus-authority-qualification.yml",
    ".github/workflows/authbus-target-host-qualification.yml",
    ".github/workflows/authbus-production-acceptance.yml",
    "codex-rs/hepta-authbus",
    "codex-rs/hepta-authbus-p1-3-qualification",
    "codex-rs/hepta-evidence",
    "codex-rs/hepta-agentd",
    "codex-rs/hepta-bao-adapter",
    "docs/modules/auth.authbus",
    "docs/lane-a-foundation/auth.authbus",
    "scripts/check-authbus-closed-world.py",
    "scripts/authbus-evidence-projection.py",
    "scripts/authbus-exact-head-evidence.py",
    "scripts/authbus-target-host-evidence.py",
    "scripts/authbus-performance-evidence.py",
    "scripts/authbus-production-acceptance.py",
]
ARTIFACT_TOKENS = ("authbus", "hepta_evidence", "hepta_agentd", "bao_adapter")
REQUIRED_PROJECTIONS = (
    "source-head.json",
    "implementation-map.bound.json",
    "current-implementation.bound.json",
    "qualification-dossier.bound.json",
    "release-status.bound.json",
)


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
    if not path.exists():
        raise SystemExit(f"receipt source root does not exist: {relative}")
    if path.is_file():
        return [path]
    return sorted(
        candidate
        for candidate in path.rglob("*")
        if candidate.is_file() and "target" not in candidate.parts
    )


def event_payload() -> dict[str, Any]:
    event_path = os.environ.get("GITHUB_EVENT_PATH")
    if not event_path:
        return {}
    path = Path(event_path)
    if not path.is_file():
        raise SystemExit("GITHUB_EVENT_PATH does not name a readable event payload")
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise SystemExit("GitHub event payload is not an object")
    return value


def pull_request_identity(event: dict[str, Any]) -> dict[str, Any]:
    pull_request = event.get("pull_request")
    if not isinstance(pull_request, dict):
        return {}
    base = pull_request.get("base")
    head = pull_request.get("head")
    return {
        "number": event.get("number"),
        "base": base.get("sha") if isinstance(base, dict) else None,
        "head": head.get("sha") if isinstance(head, dict) else None,
    }


def verify_candidate_identity(
    commit: str,
    parents: list[str],
    candidate_kind: str,
    expected_head: str | None,
    expected_base: str | None,
) -> None:
    if candidate_kind == "exact_head":
        if expected_head and commit != expected_head:
            raise SystemExit(
                f"exact-head receipt candidate {commit} does not match expected head {expected_head}"
            )
        if len(parents) > 1:
            raise SystemExit("exact-head receipt unexpectedly names a merge commit")
        return
    if candidate_kind == "synthetic_merge":
        if len(parents) != 2:
            raise SystemExit("synthetic-merge receipt must have exactly two parents")
        if expected_base and parents[0] != expected_base:
            raise SystemExit("synthetic-merge first parent does not match expected base")
        if expected_head and parents[1] != expected_head:
            raise SystemExit("synthetic-merge second parent does not match expected head")
        return
    if candidate_kind == "main_head" and len(parents) > 2:
        raise SystemExit("main-head receipt has an invalid parent set")


def target_triple() -> str:
    verbose = run("rustc", "--version", "--verbose")
    for line in verbose.splitlines():
        if line.startswith("host: "):
            return line.removeprefix("host: ").strip()
    raise SystemExit("rustc did not report a host target triple")


def nonempty_files(paths: list[Path], label: str) -> list[tuple[str, str]]:
    entries: list[tuple[str, str]] = []
    for path in paths:
        if not path.is_file() or path.stat().st_size == 0:
            raise SystemExit(f"{label} is missing or empty: {path}")
        entries.append((path.name, sha256(path)))
    return entries


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--test-log", action="append", default=[], type=Path)
    parser.add_argument("--projection-dir", required=True, type=Path)
    parser.add_argument("--artifact-root", type=Path, default=ROOT / "codex-rs/target")
    parser.add_argument(
        "--candidate-kind",
        required=True,
        choices=("exact_head", "synthetic_merge", "main_head"),
    )
    parser.add_argument("--expected-head")
    parser.add_argument("--expected-base")
    args = parser.parse_args()

    if subprocess.call(["git", "diff", "--quiet"], cwd=ROOT) != 0 or subprocess.call(
        ["git", "diff", "--cached", "--quiet"], cwd=ROOT
    ) != 0:
        raise SystemExit("tracked worktree is not clean")

    commit = run("git", "rev-parse", "HEAD")
    tree = run("git", "rev-parse", "HEAD^{tree}")
    parents = run("git", "show", "-s", "--format=%P", "HEAD").split()
    verify_candidate_identity(
        commit,
        parents,
        args.candidate_kind,
        args.expected_head,
        args.expected_base,
    )

    event = event_payload()
    pull_request = pull_request_identity(event)
    source_entries: list[tuple[str, str]] = []
    for relative in RELEVANT_ROOTS:
        for path in files_under(relative):
            source_entries.append((path.relative_to(ROOT).as_posix(), sha256(path)))

    migration_entries = [
        (path.relative_to(ROOT).as_posix(), sha256(path))
        for path in sorted((ROOT / "codex-rs/hepta-authbus/migrations").glob("*.sql"))
    ]
    log_entries = nonempty_files(args.test_log, "qualification log")
    projection_paths = [args.projection_dir / name for name in REQUIRED_PROJECTIONS]
    projection_entries = nonempty_files(projection_paths, "evidence projection")

    artifact_entries: list[tuple[str, str]] = []
    if args.artifact_root.exists():
        for path in sorted(args.artifact_root.rglob("*")):
            if not path.is_file() or not any(
                token in path.name for token in ARTIFACT_TOKENS
            ):
                continue
            artifact_entries.append(
                (path.relative_to(args.artifact_root).as_posix(), sha256(path))
            )

    cargo_lock = ROOT / "codex-rs/Cargo.lock"
    workflow_sha = os.environ.get("GITHUB_SHA")
    workflow_event = os.environ.get("GITHUB_EVENT_NAME")
    receipt = {
        "schema": "hepta.authbus.exact-head-evidence.v2",
        "candidate": {
            "kind": args.candidate_kind,
            "commit": commit,
            "tree": tree,
            "parents": parents,
        },
        "pullRequest": pull_request,
        "workflow": {
            "runId": os.environ.get("GITHUB_RUN_ID"),
            "runAttempt": os.environ.get("GITHUB_RUN_ATTEMPT"),
            "job": os.environ.get("GITHUB_JOB"),
            "event": workflow_event,
            "ref": os.environ.get("GITHUB_REF"),
            "triggerSha": workflow_sha,
            "repository": os.environ.get("GITHUB_REPOSITORY"),
            "workflowRef": os.environ.get("GITHUB_WORKFLOW_REF"),
        },
        "runner": {
            "os": os.environ.get("RUNNER_OS") or platform.system(),
            "arch": os.environ.get("RUNNER_ARCH") or platform.machine(),
            "name": os.environ.get("RUNNER_NAME"),
            "environment": os.environ.get("RUNNER_ENVIRONMENT"),
            "image": os.environ.get("ImageOS") or os.environ.get("ImageVersion"),
            "targetTriple": target_triple(),
        },
        "digests": {
            "relevantSource": aggregate(source_entries),
            "schema": aggregate(migration_entries),
            "cargoLock": sha256(cargo_lock),
            "testLogs": aggregate(log_entries),
            "evidenceProjections": aggregate(projection_entries),
            "buildArtifacts": aggregate(artifact_entries),
        },
        "sourceFileCount": len(source_entries),
        "migrationFiles": [
            {"path": name, "sha256": digest} for name, digest in migration_entries
        ],
        "testLogs": [
            {"path": name, "sha256": digest} for name, digest in log_entries
        ],
        "evidenceProjections": [
            {"path": name, "sha256": digest} for name, digest in projection_entries
        ],
        "buildArtifactCount": len(artifact_entries),
        "toolchain": {
            "rustc": run("rustc", "--version"),
            "cargo": run("cargo", "--version"),
            "git": run("git", "--version"),
        },
        "trackedWorktreeClean": True,
        "qualificationComplete": True,
        "targetHostQualification": False,
        "independentSecurityAcceptance": False,
        "activation": False,
        "release": False,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


if __name__ == "__main__":
    main()
