#!/usr/bin/env python3
"""Emit an exact-candidate inference.worker readiness identity receipt.

This script binds repository truth to the Git candidate being checked. It does
not turn source or documentation evidence into deployment/hardware acceptance.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
MAP = ROOT / "docs/modules/inference.worker/IMPLEMENTATION_MAP.json"
TECH = ROOT / "docs/modules/inference.worker/TECHNICAL.md"
RUNBOOK = ROOT / "docs/modules/inference.worker/PRODUCTION_READINESS.md"
WORKER_ROOT = ROOT / "codex-rs/hepta-infer-worker-host"

NEGATIVE_CLAIMS = (
    "productionImplementation",
    "productExecutionComplete",
    "deploymentQualificationComplete",
    "independentAcceptanceComplete",
    "productExecutionProved",
    "independentAcceptance",
    "activation",
    "release",
)


def git(*args: str) -> str:
    result = subprocess.run(["git", *args], cwd=ROOT, text=True, capture_output=True)
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or f"git {' '.join(args)} failed")
    return result.stdout.rstrip("\n")


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path}: expected object")
    return value


def worker_tree(head: str) -> str:
    value = git("rev-parse", f"{head}:codex-rs/hepta-infer-worker-host")
    if len(value) != 40:
        raise ValueError("invalid worker tree identity")
    return value


def build_receipt(expected_sha: str | None = None) -> dict[str, Any]:
    head = git("rev-parse", "HEAD")
    if expected_sha is not None and head != expected_sha:
        raise ValueError(f"checkout {head} does not match expected candidate {expected_sha}")
    tree = git("rev-parse", "HEAD^{tree}")
    mapping = load_json(MAP)
    if mapping.get("module") != "inference.worker":
        raise ValueError("implementation map module mismatch")
    source_base = mapping.get("sourceBase")
    if not isinstance(source_base, dict) or set(source_base) != {"commit", "tree"}:
        raise ValueError("invalid implementation-map sourceBase")
    if git("rev-parse", f"{source_base['commit']}^{{tree}}") != source_base["tree"]:
        raise ValueError("implementation-map sourceBase tree mismatch")
    git("merge-base", "--is-ancestor", source_base["commit"], head)

    claim = mapping.get("claimBoundary")
    if not isinstance(claim, dict):
        raise ValueError("missing claimBoundary")
    for key in NEGATIVE_CLAIMS:
        value = mapping.get(key) if key in mapping else claim.get(key)
        if value is not False:
            raise ValueError(f"{key} must remain false until independently qualified")

    for path in (TECH, RUNBOOK):
        text = path.read_text(encoding="utf-8")
        if "ResourceGrant" not in text or "isolation" not in text.lower():
            raise ValueError(f"{path}: trust/isolation contract is incomplete")

    return {
        "schema": "hepta.inference-worker-candidate-receipt.v1",
        "schemaVersion": 1,
        "module": "inference.worker",
        "candidate": {"commit": head, "tree": tree, "workerTree": worker_tree(head)},
        "implementationMapSourceBase": source_base,
        "documents": {
            str(MAP.relative_to(ROOT)): sha256_file(MAP),
            str(TECH.relative_to(ROOT)): sha256_file(TECH),
            str(RUNBOOK.relative_to(ROOT)): sha256_file(RUNBOOK),
        },
        "repositoryControlledGaps": mapping.get("repositoryControlledGaps", []),
        "externalEvidenceGates": mapping.get("externalEvidenceGates", []),
        "claimBoundary": {key: False for key in NEGATIVE_CLAIMS},
        "limitations": [
            "receipt binds source/document identity only",
            "receipt is not hardware qualification",
            "receipt is not provider reconciliation evidence",
            "receipt is not independent acceptance or activation authority",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--expected-sha")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    receipt = build_receipt(args.expected_sha)
    encoded = json.dumps(receipt, indent=2, sort_keys=True) + "\n"
    if args.output:
        output = args.output if args.output.is_absolute() else ROOT / args.output
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(encoded, encoding="utf-8")
    else:
        print(encoded, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
