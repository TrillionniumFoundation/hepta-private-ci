#!/usr/bin/env python3
"""Project objective.compiler execution artifacts into one traceable status view.

The projection is derived from observed receipts. It never grants independent
acceptance, activation, promotion, release, or selected deployment-host approval.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from typing import Any

SHA = re.compile(r"[0-9a-f]{40}\Z")
LOG_SHA = re.compile(r"[0-9a-f]{64}\Z")


def load(path: Path) -> dict[str, Any]:
    def unique(items: list[tuple[str, Any]]) -> dict[str, Any]:
        value: dict[str, Any] = {}
        for key, item in items:
            if key in value:
                raise ValueError(f"duplicate JSON key in {path}: {key}")
            value[key] = item
        return value

    value = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=unique)
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain one JSON object")
    return value


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def candidate_state(receipt: dict[str, Any], kind: str) -> str:
    candidates = receipt.get("candidates")
    if not isinstance(candidates, list):
        return "failed"
    matching = [
        item
        for item in candidates
        if isinstance(item, dict) and item.get("kind") == kind
    ]
    if len(matching) != 1:
        return "failed"
    candidate = matching[0]
    checks = candidate.get("checks")
    if (
        candidate.get("clean") is True
        and isinstance(checks, list)
        and checks
        and all(
            isinstance(check, dict)
            and check.get("status") == "completed"
            and check.get("exitCode") == 0
            and isinstance(check.get("logSha256"), str)
            and LOG_SHA.fullmatch(check["logSha256"])
            for check in checks
        )
    ):
        return "passed"
    return "failed"


def exact_projection(
    path: Path, source_commit: str, source_tree: str
) -> dict[str, Any]:
    receipt = load(path)
    if receipt.get("schema") != "hepta.objective.exact-execution.v1":
        raise ValueError("unexpected exact-execution schema")
    if (
        receipt.get("sourceCommit") != source_commit
        or receipt.get("sourceTree") != source_tree
    ):
        raise ValueError("exact-execution source identity mismatch")
    return {
        "artifactSha256": sha256(path),
        "runId": receipt.get("runId"),
        "runAttempt": receipt.get("runAttempt"),
        "workflowCommit": receipt.get("workflowCommit"),
        "sourceHeadQualification": candidate_state(receipt, "source-head"),
        "syntheticMergeQualification": candidate_state(receipt, "synthetic-merge"),
        "checksPassed": receipt.get("checksPassed") is True,
        "errors": receipt.get("errors")
        if isinstance(receipt.get("errors"), list)
        else [],
    }


def target_projection(
    path: Path, source_commit: str, source_tree: str
) -> dict[str, Any]:
    receipt = load(path)
    if receipt.get("schema") != "hepta.objective-target-host-evidence.v1":
        raise ValueError("unexpected target-measurement schema")
    if (
        receipt.get("sourceCommit") != source_commit
        or receipt.get("sourceTree") != source_tree
    ):
        raise ValueError("target-measurement source identity mismatch")
    measurements = receipt.get("measurements")
    observed = isinstance(measurements, list) and bool(measurements)
    return {
        "artifactSha256": sha256(path),
        "hostProfileId": receipt.get("hostProfileId"),
        "measurementObserved": observed,
        "measurementCount": len(measurements)
        if isinstance(measurements, list)
        else 0,
        "selectedDeploymentHostAccepted": False,
        "storageQualificationProved": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-commit", required=True)
    parser.add_argument("--source-tree", required=True)
    parser.add_argument("--exact-execution", type=Path)
    parser.add_argument("--target-measurement", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    if not SHA.fullmatch(args.source_commit) or not SHA.fullmatch(args.source_tree):
        parser.error("source commit and tree must be complete lowercase SHA-1 identities")
    if args.exact_execution is None and args.target_measurement is None:
        parser.error("at least one evidence input is required")

    exact = (
        exact_projection(args.exact_execution, args.source_commit, args.source_tree)
        if args.exact_execution is not None
        else {
            "sourceHeadQualification": "unverified",
            "syntheticMergeQualification": "unverified",
            "checksPassed": False,
        }
    )
    target = (
        target_projection(args.target_measurement, args.source_commit, args.source_tree)
        if args.target_measurement is not None
        else {
            "measurementObserved": False,
            "selectedDeploymentHostAccepted": False,
            "storageQualificationProved": False,
        }
    )
    projection = {
        "schema": "hepta.objective-evidence-projection.v1",
        "module": "objective.compiler",
        "sourceCommit": args.source_commit,
        "sourceTree": args.source_tree,
        "exactExecution": exact,
        "targetHostMeasurement": target,
        "independentAcceptance": "unverified",
        "operatorAcceptance": "unverified",
        "truth": {
            "productionImplementation": False,
            "accepted": False,
            "activated": False,
            "released": False,
        },
        "claimBoundary": (
            "observed execution only; no independent acceptance, selected-host "
            "approval, activation, promotion, or release authority"
        ),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    temporary = args.output.with_suffix(args.output.suffix + ".tmp")
    temporary.write_text(
        json.dumps(projection, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    temporary.replace(args.output)
    print(json.dumps(projection, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
