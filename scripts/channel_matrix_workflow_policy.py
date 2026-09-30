#!/usr/bin/env python3
"""Fail closed if any channel.matrix workflow can mutate reviewed source."""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW_DIRECTORY = ROOT / ".github/workflows"
EXPECTED_WORKFLOWS = (
    "channel-matrix-materialize.yml",
    "channel-matrix-preserve-unknown.yml",
    "channel-matrix-protected-production.yml",
)
RESULT_SCHEMA = "hepta.channel-matrix-workflow-policy.v1"
MAX_WORKFLOW_BYTES = 512 * 1024
FORBIDDEN_PATTERNS = {
    "contents_write": re.compile(r"(?m)^\s*contents:\s*write\s*$"),
    "git_push": re.compile(r"(?m)(?:^|[;&|]\s*)git\s+push(?:\s|$)"),
    "git_commit": re.compile(r"(?m)(?:^|[;&|]\s*)git\s+commit(?:\s|$)"),
    "git_add": re.compile(r"(?m)(?:^|[;&|]\s*)git\s+add(?:\s|$)"),
    "git_rm": re.compile(r"(?m)(?:^|[;&|]\s*)git\s+rm(?:\s|$)"),
    "git_update_ref": re.compile(r"(?m)(?:^|[;&|]\s*)git\s+update-ref(?:\s|$)"),
    "cargo_fix": re.compile(r"(?m)\bcargo\s+(?:clippy\s+--fix|fix)\b"),
    "apply_patch": re.compile(r"(?m)\bapply_patch\b"),
    "decoded_source_bundle": re.compile(r"(?m)\bbase64\s+--decode\b|\bgzip\s+-d[cf]?\b"),
    "staging_source": re.compile(r"(?m)\.matrix-staging|channel_matrix_apply"),
    "persistent_checkout_credentials": re.compile(
        r"(?m)^\s*persist-credentials:\s*(?:true|['\"]true['\"])\s*$"
    ),
}
CHECKOUT = re.compile(r"(?m)^\s*(?:-\s+)?uses:\s*actions/checkout@[^ \n]+\s*$")


def _stable_text(path: Path) -> str:
    resolved = path.resolve(strict=True)
    if path.is_symlink() or not resolved.is_file() or resolved != path.absolute():
        raise ValueError(f"canonical workflow required: {path.name}")
    before = resolved.stat()
    if not 0 < before.st_size <= MAX_WORKFLOW_BYTES:
        raise ValueError(f"workflow size is invalid: {path.name}")
    payload = resolved.read_bytes()
    after = resolved.stat()
    identity = lambda row: (
        row.st_dev,
        row.st_ino,
        row.st_size,
        row.st_mtime_ns,
        row.st_ctime_ns,
    )
    if identity(before) != identity(after) or len(payload) != before.st_size:
        raise ValueError(f"workflow changed while being read: {path.name}")
    try:
        return payload.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError(f"workflow is not UTF-8: {path.name}") from exc


def _checkout_blocks(text: str) -> list[str]:
    matches = list(CHECKOUT.finditer(text))
    blocks = []
    for index, match in enumerate(matches):
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        blocks.append(text[start:end])
    return blocks


def validate_workflow(path: Path) -> dict[str, Any]:
    text = _stable_text(path)
    if not re.search(r"(?m)^permissions:\s*\n\s+contents:\s*read\s*$", text):
        raise ValueError(f"{path.name} lacks top-level contents: read")
    violations = [
        name for name, pattern in FORBIDDEN_PATTERNS.items() if pattern.search(text)
    ]
    if violations:
        raise ValueError(f"{path.name} violates workflow policy: {','.join(violations)}")
    checkout_blocks = _checkout_blocks(text)
    if not checkout_blocks:
        raise ValueError(f"{path.name} has no pinned checkout")
    for block in checkout_blocks:
        if not re.search(r"(?m)^\s+persist-credentials:\s*false\s*$", block):
            raise ValueError(f"{path.name} checkout retains credentials")
    if re.search(r"(?m)uses:\s*actions/checkout@(?![0-9a-f]{40}\b)", text):
        raise ValueError(f"{path.name} checkout action is not pinned by commit")
    return {
        "path": path.relative_to(ROOT).as_posix(),
        "permissions": "contents:read",
        "checkoutCount": len(checkout_blocks),
        "sourceMutationAllowed": False,
    }


def validate_directory(directory: Path = WORKFLOW_DIRECTORY) -> dict[str, Any]:
    resolved = directory.resolve(strict=True)
    if directory.is_symlink() or not resolved.is_dir() or resolved != directory.absolute():
        raise ValueError("canonical workflow directory required")
    observed = tuple(
        sorted(
            path.name
            for pattern in ("channel-matrix-*.yml", "channel-matrix-*.yaml")
            for path in resolved.glob(pattern)
            if path.is_file()
        )
    )
    if observed != EXPECTED_WORKFLOWS:
        raise ValueError(
            f"closed channel.matrix workflow inventory mismatch: {observed!r}"
        )
    workflows = [validate_workflow(resolved / name) for name in observed]
    production = next(
        row for row in workflows if row["path"].endswith("channel-matrix-protected-production.yml")
    )
    production_text = _stable_text(resolved / "channel-matrix-protected-production.yml")
    for marker in (
        "workflow_dispatch:",
        "environment: channel-matrix-production-qualification",
        "self-hosted",
        "production-qualification",
        "scripts/channel_matrix_production_bundle.py",
    ):
        if marker not in production_text:
            raise ValueError(f"protected production workflow lacks marker: {marker}")
    production["protectedEnvironment"] = True
    return {
        "schema": RESULT_SCHEMA,
        "result": "pass",
        "workflows": workflows,
        "authorityGranted": False,
        "activation": False,
        "promotion": False,
        "release": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", type=Path, default=WORKFLOW_DIRECTORY)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    try:
        row = validate_directory(args.directory)
    except (OSError, ValueError) as exc:
        print(
            json.dumps(
                {
                    "schema": RESULT_SCHEMA,
                    "result": "fail",
                    "error": str(exc),
                    "authorityGranted": False,
                    "activation": False,
                    "promotion": False,
                    "release": False,
                },
                sort_keys=True,
            )
        )
        return 2
    print(json.dumps(row, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
