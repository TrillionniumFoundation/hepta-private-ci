#!/usr/bin/env python3
"""Create an immutable AuthBus exact-candidate qualification receipt."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
RELEVANT_ROOTS = [
    ".github/workflows/authbus-authority-qualification.yml",
    "codex-rs/hepta-authbus",
    "codex-rs/hepta-authbus-p1-3-qualification",
    "codex-rs/hepta-evidence",
    "codex-rs/hepta-agentd",
    "codex-rs/hepta-bao-adapter",
    "docs/modules/auth.authbus",
    "docs/lane-a-foundation/auth.authbus",
    "scripts/check-authbus-closed-world.py",
    "scripts/authbus-exact-head-evidence.py",
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
    job: str | None,
    pull_request: dict[str, Any],
) -> str:
    expected_base = pull_request.get("base")
    expected_head = pull_request.get("head")
    if job == "source-head" and expected_head:
        if commit != expected_head:
            raise SystemExit(
                f"exact-head receipt candidate {commit} does not match PR head {expected_head}"
            )
        return "exact_head"
    if job == "synthetic-merge" and expected_base and expected_head:
        if parents != [expected_base, expected_head]:
            raise SystemExit(
                "synthetic-merge receipt parents do not match the declared PR base/head"
            )
        return "synthetic_merge"
    if len(parents) == 2:
        return "merge_candidate"
    return "source_head"


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
    parents = run("git", "show", "-s", "--format=%P", "HEAD").split()
    event = event_payload()
    pull_request = pull_request_identity(event)
    job = os.environ.get("GITHUB_JOB")
    candidate_kind = verify_candidate_identity(commit, parents, job, pull_request)

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
    if len(log_entries) != len(args.test_log):
        raise SystemExit("one or more declared qualification logs are missing")

    artifact_entries: list[tuple[str, str]] = []
    if args.artifact_root.exists():
        for path in sorted(args.artifact_root.rglob("*")):
            if not path.is_file() or not any(token in path.name for token in ARTIFACT_TOKENS):
                continue
            artifact_entries.append((path.relative_to(args.artifact_root).as_posix(), sha256(path)))

    cargo_lock = ROOT / "codex-rs/Cargo.lock"
    receipt = {
        "schema": "hepta.authbus.exact-head-evidence.v1",
        "candidate": {
            "kind": candidate_kind,
            "commit": commit,
            "tree": tree,
            "parents": parents,
        },
        "pullRequest": pull_request,
        "workflow": {
            "runId": os.environ.get("GITHUB_RUN_ID"),
            "runAttempt": os.environ.get("GITHUB_RUN_ATTEMPT"),
            "job": job,
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
        "sourceFileCount": len(source_entries),
        "migrationFiles": [
            {"path": name, "sha256": digest} for name, digest in migration_entries
        ],
        "testLogs": [{"path": name, "sha256": digest} for name, digest in log_entries],
        "buildArtifactCount": len(artifact_entries),
        "toolchain": {
            "rustc": run("rustc", "--version"),
            "cargo": run("cargo", "--version"),
            "git": run("git", "--version"),
        },
        "trackedWorktreeClean": True,
        "activation": False,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
