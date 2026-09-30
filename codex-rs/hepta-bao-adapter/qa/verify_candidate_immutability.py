#!/usr/bin/env python3
"""Fail closed when the secrets.heptabao review tree can rewrite itself.

The final review candidate is ordinary source. Source materializers, source
exporters, patch payloads, and workflow write credentials are development
machinery and must not be reachable from the candidate tree.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Iterable

CANONICAL_WORKFLOWS = {
    Path(".github/workflows/secrets-heptabao-five-closure-qualified.yml"),
    Path(".github/workflows/secrets-heptabao-candidate-attestation.yml"),
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
    ".hepta-staging/**/*secrets*",
    "scripts/close_secrets_heptabao*.py",
    "scripts/materialize_secrets_heptabao*.py",
)

WRITE_MARKERS = (
    "contents: write",
    "persist-credentials: true",
    "git push",
    "git commit",
    "materialize_secrets_heptabao",
    "close_secrets_heptabao",
)

SECRETS_MARKERS = (
    "secrets.heptabao",
    "hepta-bao-adapter",
    "secrets-heptabao",
    "hepta-secrets",
    "apply-secrets",
    "secrets-sqlite",
)


def _workflow_paths(root: Path) -> Iterable[Path]:
    workflow_dir = root / ".github" / "workflows"
    if not workflow_dir.is_dir():
        return ()
    return sorted((*workflow_dir.glob("*.yml"), *workflow_dir.glob("*.yaml")))


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
                    f"development materialization/export payload remains in candidate: "
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
        "schema": "hepta.secrets-candidate-immutability.v1",
        "root": str(args.root.resolve()),
        "canonicalWorkflows": sorted(str(path) for path in CANONICAL_WORKFLOWS),
        "immutable": not violations,
        "violations": violations,
    }
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if not violations else 1


if __name__ == "__main__":
    raise SystemExit(main())
