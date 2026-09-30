#!/usr/bin/env python3
"""Fail closed when the secrets.heptabao review tree can rewrite itself.

The final review candidate is ordinary source. Source materializers, source
exporters, patch payloads, bootstrap fragments, and workflow write credentials
are development machinery and must not be reachable from the candidate tree.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Iterable

FROZEN_BRANCH = "codex/secrets-heptabao-frozen-closure-20260930"
MUTABLE_BRANCHES = (
    "codex/secrets-heptabao-production-qualified-20260930",
)

CANONICAL_WORKFLOWS = {
    Path(".github/workflows/secrets-heptabao-five-closure-qualified.yml"),
    Path(".github/workflows/secrets-heptabao-candidate-attestation.yml"),
    Path(".github/workflows/secrets-heptabao-storage-and-supply-chain.yml"),
}

BANNED_WORKFLOW_TOKENS = (
    "materialize",
    "source-export",
    "source_export",
    "full-closure-phase1",
    "five-closure-export",
    "manifest-materialize",
    "direct-materialize",
    "sqlite-source-export",
    "bootstrap-apply-secrets",
    "phase3-evaluate",
    "secrets-recovery",
)

BANNED_FILE_GLOBS = (
    ".ci/secrets-heptabao*",
    ".hepta-bootstrap/**/*",
    ".hepta-staging/**/*",
    "scripts/close_secrets_heptabao*.py",
    "scripts/materialize_secrets_heptabao*.py",
    "scripts/export_secrets_heptabao*.py",
)

WRITE_MARKERS = (
    "contents: write",
    "persist-credentials: true",
    "git push",
    "git commit",
    "git apply",
    "materialize_secrets_heptabao",
    "close_secrets_heptabao",
    "export_secrets_heptabao",
)

SECRETS_MARKERS = (
    "secrets.heptabao",
    "hepta-bao-adapter",
    "secrets-heptabao",
    "hepta-secrets",
    "apply-secrets",
    "secrets-sqlite",
)

EXACT_SHA_MARKERS = (
    "github.sha",
    "github.event.pull_request.head.sha",
)


def _workflow_paths(root: Path) -> Iterable[Path]:
    workflow_dir = root / ".github" / "workflows"
    if not workflow_dir.is_dir():
        return ()
    return sorted((*workflow_dir.glob("*.yml"), *workflow_dir.glob("*.yaml")))


def _is_banned_payload(relative: Path) -> bool:
    lowered = relative.as_posix().lower()
    if lowered.startswith((".hepta-bootstrap/", ".hepta-staging/")):
        return any(
            token in lowered
            for token in ("secret", "material", "bootstrap", "patch", "part-", "trigger")
        )
    return False


def collect_violations(root: Path) -> list[str]:
    root = root.resolve()
    violations: list[str] = []

    for relative in sorted(CANONICAL_WORKFLOWS):
        path = root / relative
        if not path.is_file():
            violations.append(f"missing canonical read-only workflow: {relative}")
            continue
        text = path.read_text(encoding="utf-8").lower()
        if "permissions:" not in text or "contents: read" not in text:
            violations.append(f"canonical workflow is not explicitly read-only: {relative}")
        if "persist-credentials: false" not in text:
            violations.append(f"canonical workflow checkout is not credentialless: {relative}")
        if not any(marker in text for marker in EXACT_SHA_MARKERS):
            violations.append(f"canonical workflow is not bound to an exact candidate SHA: {relative}")
        for mutable_branch in MUTABLE_BRANCHES:
            if mutable_branch.lower() in text:
                violations.append(
                    f"canonical workflow references superseded mutable branch {mutable_branch!r}: {relative}"
                )
        for marker in WRITE_MARKERS:
            if marker in text:
                violations.append(
                    f"canonical workflow contains forbidden write marker {marker!r}: {relative}"
                )

    for path in _workflow_paths(root):
        relative = path.relative_to(root)
        lowered_name = relative.name.lower()
        text = path.read_text(encoding="utf-8").lower()
        secrets_related = any(marker in lowered_name or marker in text for marker in SECRETS_MARKERS)
        if not secrets_related:
            continue

        if relative not in CANONICAL_WORKFLOWS and any(
            token in lowered_name for token in BANNED_WORKFLOW_TOKENS
        ):
            violations.append(f"development source workflow remains in candidate: {relative}")

        for marker in WRITE_MARKERS:
            if marker in text:
                violations.append(
                    f"secrets-related workflow contains forbidden write marker {marker!r}: {relative}"
                )

    for pattern in BANNED_FILE_GLOBS:
        for path in sorted(root.glob(pattern)):
            if path.is_file():
                violations.append(
                    "development materialization/export payload remains in candidate: "
                    f"{path.relative_to(root)}"
                )

    for prefix in (root / ".hepta-bootstrap", root / ".hepta-staging"):
        if not prefix.exists():
            continue
        for path in sorted(prefix.rglob("*")):
            if path.is_file() and _is_banned_payload(path.relative_to(root)):
                violations.append(
                    "development materialization/export payload remains in candidate: "
                    f"{path.relative_to(root)}"
                )

    return sorted(set(violations))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--root",
        type=Path,
        default=Path(__file__).resolve().parents[3],
        help="repository root (defaults to the checked-out repository)",
    )
    args = parser.parse_args()

    violations = collect_violations(args.root)
    report = {
        "schema": "hepta.secrets-candidate-immutability.v2",
        "root": str(args.root.resolve()),
        "frozenBranch": FROZEN_BRANCH,
        "canonicalWorkflows": sorted(str(path) for path in CANONICAL_WORKFLOWS),
        "immutable": not violations,
        "violations": violations,
    }
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if not violations else 1


if __name__ == "__main__":
    raise SystemExit(main())
