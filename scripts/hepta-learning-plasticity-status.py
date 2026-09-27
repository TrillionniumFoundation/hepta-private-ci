#!/usr/bin/env python3
"""Generate an immutable exact-head learning.plasticity status artifact.

The output is deliberately generated into CI artifacts, never committed as a
canonical current-state file. Dynamic workflow/check observations expire and
must not become source-selection authority.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import pathlib
import subprocess
from dataclasses import dataclass
from typing import Any

ROOT = pathlib.Path(__file__).resolve().parents[1]
DEFAULT_TTL_HOURS = 336


def git(*args: str) -> str:
    return subprocess.check_output(
        ["git", *args], cwd=ROOT, text=True, stderr=subprocess.STDOUT
    ).strip()


def sha256_file(path: pathlib.Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def parse_receipt(raw: str) -> tuple[str, pathlib.Path]:
    name, separator, value = raw.partition("=")
    if not separator or not name or not value:
        raise argparse.ArgumentTypeError("receipt must be NAME=PATH")
    return name, pathlib.Path(value)


def utc_now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0)


def workflow_observations() -> list[dict[str, Any]]:
    raw = os.environ.get("HEPTA_REQUIRED_WORKFLOWS_JSON", "")
    if not raw:
        return [
            {"name": "CI required", "state": "not_observed"},
            {"name": "Architecture required", "state": "not_observed"},
            {"name": "Hepta Agentd process qualification", "state": "not_observed"},
            {"name": "Hepta Lane F shadow qualification", "state": "not_observed"},
            {"name": "live runtime structural canary", "state": "not_observed"},
        ]
    parsed = json.loads(raw)
    if not isinstance(parsed, list):
        raise ValueError("HEPTA_REQUIRED_WORKFLOWS_JSON must contain a JSON array")
    return parsed


def build_status(receipts: list[tuple[str, pathlib.Path]], ttl_hours: int) -> dict[str, Any]:
    observed_at = utc_now()
    source_commit = git("rev-parse", "HEAD")
    source_tree = git("rev-parse", "HEAD^{tree}")
    implementation_map = ROOT / "docs/modules/learning.plasticity/IMPLEMENTATION_MAP.json"
    host_profile = ROOT / "docs/modules/learning.plasticity/OPERATIONS.md"

    receipt_rows: list[dict[str, Any]] = []
    for name, path in receipts:
        resolved = path if path.is_absolute() else ROOT / path
        if not resolved.is_file():
            raise FileNotFoundError(f"receipt {name!r} does not exist: {resolved}")
        receipt_rows.append(
            {
                "name": name,
                "path": str(resolved.relative_to(ROOT))
                if resolved.is_relative_to(ROOT)
                else str(resolved),
                "sha256": sha256_file(resolved),
                "bytes": resolved.stat().st_size,
            }
        )

    return {
        "schema": "hepta.learning-plasticity-exact-head-status.v1",
        "schemaVersion": 1,
        "authority": "ephemeral_qualification_observation_only",
        "module": "learning.plasticity",
        "source": {
            "commit": source_commit,
            "tree": source_tree,
            "branch": os.environ.get("GITHUB_HEAD_REF")
            or os.environ.get("GITHUB_REF_NAME")
            or "local",
            "baseCommit": os.environ.get("GITHUB_BASE_SHA") or None,
            "repository": os.environ.get("GITHUB_REPOSITORY")
            or "TrillionniumFoundation/hepta-private-ci",
        },
        "bindings": {
            "implementationMap": {
                "path": str(implementation_map.relative_to(ROOT)),
                "sha256": sha256_file(implementation_map),
            },
            "hostProfile": {
                "path": str(host_profile.relative_to(ROOT)),
                "sha256": sha256_file(host_profile),
            },
        },
        "workflowRun": {
            "id": os.environ.get("GITHUB_RUN_ID"),
            "attempt": os.environ.get("GITHUB_RUN_ATTEMPT"),
            "workflow": os.environ.get("GITHUB_WORKFLOW"),
            "event": os.environ.get("GITHUB_EVENT_NAME"),
        },
        "requiredWorkflowObservations": workflow_observations(),
        "testReceipts": sorted(receipt_rows, key=lambda row: row["name"]),
        "observedAt": observed_at.isoformat().replace("+00:00", "Z"),
        "expiresAt": (observed_at + dt.timedelta(hours=ttl_hours))
        .isoformat()
        .replace("+00:00", "Z"),
        "claimBoundary": {
            "sourceExecutionObserved": bool(receipt_rows),
            "targetHostExecutionProved": False,
            "physicalRollbackDomainIndependenceProved": False,
            "independentAcceptance": False,
            "activation": False,
            "release": False,
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True, type=pathlib.Path)
    parser.add_argument(
        "--receipt",
        action="append",
        default=[],
        type=parse_receipt,
        help="attach a command/evidence file as NAME=PATH",
    )
    parser.add_argument("--ttl-hours", type=int, default=DEFAULT_TTL_HOURS)
    args = parser.parse_args()
    if not 1 <= args.ttl_hours <= DEFAULT_TTL_HOURS:
        parser.error(f"--ttl-hours must be within 1..={DEFAULT_TTL_HOURS}")

    status = build_status(args.receipt, args.ttl_hours)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(status, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
