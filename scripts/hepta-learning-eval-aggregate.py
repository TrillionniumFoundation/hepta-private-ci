#!/usr/bin/env python3
"""Write and verify commit-addressed learning.eval source qualification summaries."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
from typing import Any

SCHEMA = "hepta.learning-eval.immutable-qualification-summary.v2"
RUN_STATUS_SCHEMA = "hepta.learning-eval.current-run-status.v1"
SHA1 = re.compile(r"[0-9a-f]{40}")
REQUIRED_JOBS = (
    "identityRecorder",
    "compileDefault",
    "compileCompatibility",
    "consumerTests",
    "faultRecoveryTests",
    "formatLint",
    "coverage",
)


def canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")


def evidence_hash(value: dict[str, Any]) -> str:
    unsigned = dict(value)
    unsigned.pop("evidenceSha256", None)
    return hashlib.sha256(canonical(unsigned)).hexdigest()


def parse_jobs(values: list[str]) -> dict[str, str]:
    jobs: dict[str, str] = {}
    for raw in values:
        if "=" not in raw:
            raise ValueError(f"job must be KEY=RESULT: {raw}")
        key, result = raw.split("=", 1)
        if key in jobs:
            raise ValueError(f"duplicate job result: {key}")
        jobs[key] = result
    if set(jobs) != set(REQUIRED_JOBS):
        missing = sorted(set(REQUIRED_JOBS) - set(jobs))
        extra = sorted(set(jobs) - set(REQUIRED_JOBS))
        raise ValueError(f"job inventory mismatch missing={missing} extra={extra}")
    return jobs


def build(
    source_commit: str,
    source_tree: str,
    repository: str,
    run_id: str,
    run_attempt: str,
    jobs: dict[str, str],
) -> dict[str, Any]:
    if SHA1.fullmatch(source_commit) is None:
        raise ValueError("source commit must be a literal lowercase SHA-1")
    tree_valid = SHA1.fullmatch(source_tree) is not None
    passed = tree_valid and all(result == "success" for result in jobs.values())
    value: dict[str, Any] = {
        "schema": SCHEMA,
        "source": {
            "commit": source_commit,
            "tree": source_tree if tree_valid else None,
        },
        "workflow": {
            "repository": repository,
            "runId": str(run_id),
            "runAttempt": str(run_attempt),
        },
        "jobs": jobs,
        "authority": "DENY_ALL",
        "releasePosture": "NO_GO",
        "claims": {
            "sourceInventoryVerified": jobs["identityRecorder"] == "success",
            "sourceQualifiedByThisRun": passed,
            "exactHeadExecuted": False,
            "orderedParentSyntheticMergeExecuted": False,
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
        raise ValueError("unexpected source qualification schema")
    source = value.get("source")
    if not isinstance(source, dict) or SHA1.fullmatch(str(source.get("commit", ""))) is None:
        raise ValueError("invalid source identity")
    jobs = value.get("jobs")
    if not isinstance(jobs, dict) or set(jobs) != set(REQUIRED_JOBS):
        raise ValueError("invalid job inventory")
    if value.get("authority") != "DENY_ALL" or value.get("releasePosture") != "NO_GO":
        raise ValueError("qualification summary grants authority")
    claims = value.get("claims")
    if not isinstance(claims, dict):
        raise ValueError("claims are missing")
    for name in (
        "exactHeadExecuted",
        "orderedParentSyntheticMergeExecuted",
        "targetHostQualified",
        "independentAcceptanceIssued",
        "activationAuthorized",
        "releaseAuthorized",
    ):
        if claims.get(name) is not False:
            raise ValueError(f"source workflow exceeded its claim scope: {name}")
    expected = evidence_hash(value)
    if value.get("evidenceSha256") != expected:
        raise ValueError("source qualification evidence digest mismatch")
    passed = source.get("tree") is not None and all(result == "success" for result in jobs.values())
    if claims.get("sourceQualifiedByThisRun") is not passed:
        raise ValueError("source qualification claim/result mismatch")


def write_outputs(output: Path, value: dict[str, Any]) -> None:
    output.mkdir(parents=True, exist_ok=True)
    summary = output / "qualification-summary.json"
    summary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    status = {
        "schema": RUN_STATUS_SCHEMA,
        "module": "learning.eval",
        "source": value["source"],
        "evidenceSha256": value["evidenceSha256"],
        "releasePosture": value["releasePosture"],
        "authority": value["authority"],
        "claims": value["claims"],
        "jobs": value["jobs"],
    }
    (output / "CURRENT_STATUS.run.json").write_text(
        json.dumps(status, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    write = sub.add_parser("write")
    write.add_argument("--source-commit", required=True)
    write.add_argument("--source-tree", default="")
    write.add_argument("--repository", required=True)
    write.add_argument("--run-id", required=True)
    write.add_argument("--run-attempt", required=True)
    write.add_argument("--job", action="append", default=[])
    write.add_argument("--output", type=Path, required=True)
    verify = sub.add_parser("verify")
    verify.add_argument("summary", type=Path)
    args = parser.parse_args(argv)
    try:
        if args.command == "write":
            value = build(
                args.source_commit,
                args.source_tree,
                args.repository,
                args.run_id,
                args.run_attempt,
                parse_jobs(args.job),
            )
            validate(value)
            write_outputs(args.output, value)
            print(json.dumps(value, indent=2, sort_keys=True))
            return 0
        value = json.loads(args.summary.read_text(encoding="utf-8"))
        validate(value)
        return 0 if value["claims"]["sourceQualifiedByThisRun"] else 1
    except (OSError, ValueError, json.JSONDecodeError) as error:
        print(str(error), file=__import__("sys").stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
