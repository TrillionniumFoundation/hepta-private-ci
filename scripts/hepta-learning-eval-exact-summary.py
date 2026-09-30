#!/usr/bin/env python3
"""Write conservative exact-head and ordered-parent merge matrix evidence."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
from typing import Any

SCHEMA = "hepta.learning-eval.exact-matrix-summary.v1"
SHA1 = re.compile(r"[0-9a-f]{40}")


def canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")


def evidence_hash(value: dict[str, Any]) -> str:
    unsigned = dict(value)
    unsigned.pop("evidenceSha256", None)
    return hashlib.sha256(canonical(unsigned)).hexdigest()


def build(
    source_commit: str,
    source_tree: str,
    base_commit: str,
    merge_commit: str,
    event_name: str,
    matrix_result: str,
    repository: str,
    run_id: str,
    run_attempt: str,
) -> dict[str, Any]:
    if SHA1.fullmatch(source_commit) is None or SHA1.fullmatch(source_tree) is None:
        raise ValueError("exact summary requires literal candidate commit and tree")
    is_pull_request = event_name == "pull_request"
    if is_pull_request and (
        SHA1.fullmatch(base_commit) is None or SHA1.fullmatch(merge_commit) is None
    ):
        raise ValueError("pull-request exact summary requires base and merge commits")
    passed = matrix_result == "success"
    value: dict[str, Any] = {
        "schema": SCHEMA,
        "source": {"commit": source_commit, "tree": source_tree},
        "baseCommit": base_commit or None,
        "syntheticMergeCommit": merge_commit or None,
        "eventName": event_name,
        "matrixResult": matrix_result,
        "workflow": {
            "repository": repository,
            "runId": str(run_id),
            "runAttempt": str(run_attempt),
        },
        "authority": "DENY_ALL",
        "releasePosture": "NO_GO",
        "claims": {
            "sourceInventoryVerified": False,
            "exactHeadExecuted": passed,
            "orderedParentSyntheticMergeExecuted": passed and is_pull_request,
            "targetHostQualified": False,
            "independentAcceptanceIssued": False,
            "activationAuthorized": False,
            "releaseAuthorized": False,
        },
    }
    value["evidenceSha256"] = evidence_hash(value)
    return value


def validate(value: dict[str, Any]) -> None:
    if value.get("schema") != SCHEMA:
        raise ValueError("unexpected exact summary schema")
    if value.get("authority") != "DENY_ALL" or value.get("releasePosture") != "NO_GO":
        raise ValueError("exact summary grants authority")
    if value.get("evidenceSha256") != evidence_hash(value):
        raise ValueError("exact summary evidence digest mismatch")
    claims = value.get("claims", {})
    for name in (
        "targetHostQualified",
        "independentAcceptanceIssued",
        "activationAuthorized",
        "releaseAuthorized",
    ):
        if claims.get(name) is not False:
            raise ValueError(f"exact workflow exceeded its claim scope: {name}")
    passed = value.get("matrixResult") == "success"
    if claims.get("exactHeadExecuted") is not passed:
        raise ValueError("exact-head claim/result mismatch")
    expected_merge = passed and value.get("eventName") == "pull_request"
    if claims.get("orderedParentSyntheticMergeExecuted") is not expected_merge:
        raise ValueError("synthetic-merge claim/result mismatch")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-commit", required=True)
    parser.add_argument("--source-tree", required=True)
    parser.add_argument("--base-commit", default="")
    parser.add_argument("--merge-commit", default="")
    parser.add_argument("--event-name", required=True)
    parser.add_argument("--matrix-result", required=True)
    parser.add_argument("--repository", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--run-attempt", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        value = build(
            args.source_commit,
            args.source_tree,
            args.base_commit,
            args.merge_commit,
            args.event_name,
            args.matrix_result,
            args.repository,
            args.run_id,
            args.run_attempt,
        )
        validate(value)
        args.output.mkdir(parents=True, exist_ok=True)
        (args.output / "exact-summary.json").write_text(
            json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        print(json.dumps(value, indent=2, sort_keys=True))
        return 0
    except (OSError, ValueError) as error:
        print(str(error), file=__import__("sys").stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
