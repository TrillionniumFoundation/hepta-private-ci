#!/usr/bin/env python3
"""Build and verify the canonical kernel.evidence qualification status.

The status document is deliberately generated from immutable Git identity,
per-command outcomes, and upload-artifact digests.  It is the sole CI status
format for kernel.evidence; prose documents link to it rather than carrying
independent completion claims.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import pathlib
import re
import sys
from typing import Any

HEX_40 = re.compile(r"^[0-9a-f]{40}$")
HEX_64 = re.compile(r"^[0-9a-f]{64}$")
ALLOWED_OUTCOMES = {"success", "failure", "cancelled", "skipped"}
REQUIRED_LANE_CHECKS = (
    "candidate_identity",
    "evidence_tests",
    "agentd_product_test",
    "lane_a_truth",
    "docs",
    "implementation_maps",
)


def _sha256(path: pathlib.Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _parse_checks(values: list[str]) -> dict[str, str]:
    checks: dict[str, str] = {}
    for value in values:
        name, separator, outcome = value.partition("=")
        if not separator or not name:
            raise ValueError(f"invalid --check {value!r}; expected NAME=OUTCOME")
        if outcome not in ALLOWED_OUTCOMES:
            raise ValueError(
                f"invalid outcome {outcome!r} for {name}; expected one of "
                f"{sorted(ALLOWED_OUTCOMES)}"
            )
        if name in checks:
            raise ValueError(f"duplicate check {name!r}")
        checks[name] = outcome
    return checks


def _records(directory: pathlib.Path, output: pathlib.Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    if not directory.exists():
        return records
    output_resolved = output.resolve()
    for path in sorted(directory.iterdir(), key=lambda item: item.name):
        if not path.is_file() or path.resolve() == output_resolved:
            continue
        records.append(
            {
                "name": path.name,
                "bytes": path.stat().st_size,
                "sha256": _sha256(path),
            }
        )
    return records


def _validate_git_identity(commit: str, tree: str, parents: list[str]) -> None:
    if not HEX_40.fullmatch(commit):
        raise ValueError("commit must be a lowercase 40-character Git object id")
    if not HEX_40.fullmatch(tree):
        raise ValueError("tree must be a lowercase 40-character Git object id")
    for parent in parents:
        if not HEX_40.fullmatch(parent):
            raise ValueError("every parent must be a lowercase 40-character Git object id")


def _write_json(path: pathlib.Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = json.dumps(value, indent=2, sort_keys=True) + "\n"
    path.write_text(encoded, encoding="utf-8")


def build_lane(args: argparse.Namespace) -> int:
    checks = _parse_checks(args.check)
    missing = sorted(set(REQUIRED_LANE_CHECKS) - checks.keys())
    extra = sorted(checks.keys() - set(REQUIRED_LANE_CHECKS))
    if missing or extra:
        raise ValueError(f"lane checks mismatch: missing={missing}, extra={extra}")

    parents = json.loads(args.parents_json)
    if not isinstance(parents, list) or not all(isinstance(item, str) for item in parents):
        raise ValueError("--parents-json must encode an array of Git object ids")
    _validate_git_identity(args.commit, args.tree, parents)

    qualified = all(outcome == "success" for outcome in checks.values())
    artifact_digest = args.artifact_digest or None
    if artifact_digest is not None and not HEX_64.fullmatch(artifact_digest):
        raise ValueError("artifact digest must be a lowercase SHA-256 digest")

    output = pathlib.Path(args.output)
    records_directory = pathlib.Path(args.records_dir)
    status = {
        "schemaVersion": 1,
        "module": "kernel.evidence",
        "statusKind": "qualification-lane",
        "lane": args.lane,
        "candidateKind": args.candidate_kind,
        "asOfCommit": args.commit,
        "asOfTree": args.tree,
        "parents": parents,
        "sourceCommit": args.source_commit or args.commit,
        "baseCommit": args.base_commit or None,
        "workflowRunId": args.workflow_run_id,
        "workflowRunAttempt": args.workflow_run_attempt,
        "workflowRef": args.workflow_ref,
        "eventName": args.event_name,
        "generatedAt": dt.datetime.now(dt.timezone.utc).isoformat().replace("+00:00", "Z"),
        "checks": {name: {"outcome": checks[name]} for name in sorted(checks)},
        "qualified": qualified,
        "artifact": {
            "name": args.artifact_name,
            "sha256": artifact_digest,
            "durableAcknowledgement": artifact_digest is not None,
        },
        "records": _records(records_directory, output),
    }
    _write_json(output, status)
    if args.github_output:
        with pathlib.Path(args.github_output).open("a", encoding="utf-8") as handle:
            handle.write(f"qualified={'true' if qualified else 'false'}\n")
            handle.write(f"commit={args.commit}\n")
            handle.write(f"tree={args.tree}\n")
    return 0


def _bool_text(value: str) -> bool:
    if value == "true":
        return True
    if value in {"false", "", "null"}:
        return False
    raise ValueError(f"expected true or false, got {value!r}")


def build_aggregate(args: argparse.Namespace) -> int:
    source_qualified = _bool_text(args.source_qualified)
    merge_required = args.event_name == "pull_request"
    merge_qualified = _bool_text(args.merge_qualified)
    exact_source_qualified = source_qualified
    merge_candidate_qualified = merge_qualified if merge_required else False
    all_required_qualified = source_qualified and (merge_qualified if merge_required else True)

    source_artifact_digest = args.source_artifact_digest or None
    merge_artifact_digest = args.merge_artifact_digest or None
    for label, digest in (
        ("source", source_artifact_digest),
        ("merge", merge_artifact_digest),
    ):
        if digest is not None and not HEX_64.fullmatch(digest):
            raise ValueError(f"{label} artifact digest must be a lowercase SHA-256 digest")

    status = {
        "schemaVersion": 1,
        "module": "kernel.evidence",
        "statusKind": "canonical-qualification-status",
        "asOfCommit": args.source_commit,
        "asOfTree": args.source_tree,
        "workflowRunId": args.workflow_run_id,
        "workflowRunAttempt": args.workflow_run_attempt,
        "workflowRef": args.workflow_ref,
        "eventName": args.event_name,
        "generatedAt": dt.datetime.now(dt.timezone.utc).isoformat().replace("+00:00", "Z"),
        "exactSourceQualified": exact_source_qualified,
        "mergeCandidateRequired": merge_required,
        "mergeCandidateQualified": merge_candidate_qualified,
        "independentAcceptance": False,
        "externalFrontierActive": False,
        "backupRestoreDrilled": False,
        "canaryAccepted": False,
        "releaseApproved": False,
        "allRequiredQualificationLanesPassed": all_required_qualified,
        "artifacts": {
            "exactSourceSha256": source_artifact_digest,
            "mergeCandidateSha256": merge_artifact_digest,
        },
        "deploymentClaims": {
            "externalFrontierActive": {
                "value": False,
                "reason": "CI cannot attest deployment of an external rollback-domain backend",
            },
            "releaseApproved": {
                "value": False,
                "reason": "release approval requires an independent operator receipt",
            },
        },
    }
    _write_json(pathlib.Path(args.output), status)
    if args.github_output:
        with pathlib.Path(args.github_output).open("a", encoding="utf-8") as handle:
            handle.write(
                f"qualified={'true' if all_required_qualified else 'false'}\n"
            )
    return 0


def verify(args: argparse.Namespace) -> int:
    path = pathlib.Path(args.path)
    value = json.loads(path.read_text(encoding="utf-8"))
    required = {
        "schemaVersion",
        "module",
        "statusKind",
        "asOfCommit",
        "asOfTree",
        "workflowRunId",
        "exactSourceQualified",
        "mergeCandidateQualified",
        "independentAcceptance",
        "externalFrontierActive",
        "backupRestoreDrilled",
        "canaryAccepted",
        "releaseApproved",
    }
    missing = sorted(required - value.keys())
    if missing:
        raise ValueError(f"canonical status is missing fields: {missing}")
    if value["schemaVersion"] != 1 or value["module"] != "kernel.evidence":
        raise ValueError("canonical status has an unsupported identity")
    return 0


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser()
    commands = root.add_subparsers(dest="command", required=True)

    lane = commands.add_parser("lane")
    lane.add_argument("--candidate-kind", required=True)
    lane.add_argument("--lane", required=True)
    lane.add_argument("--commit", required=True)
    lane.add_argument("--tree", required=True)
    lane.add_argument("--parents-json", required=True)
    lane.add_argument("--source-commit")
    lane.add_argument("--base-commit")
    lane.add_argument("--workflow-run-id", required=True)
    lane.add_argument("--workflow-run-attempt", required=True)
    lane.add_argument("--workflow-ref", required=True)
    lane.add_argument("--event-name", required=True)
    lane.add_argument("--artifact-name", required=True)
    lane.add_argument("--artifact-digest", default="")
    lane.add_argument("--records-dir", required=True)
    lane.add_argument("--output", required=True)
    lane.add_argument("--github-output")
    lane.add_argument("--check", action="append", default=[])
    lane.set_defaults(handler=build_lane)

    aggregate = commands.add_parser("aggregate")
    aggregate.add_argument("--source-commit", required=True)
    aggregate.add_argument("--source-tree", required=True)
    aggregate.add_argument("--source-qualified", required=True)
    aggregate.add_argument("--merge-qualified", required=True)
    aggregate.add_argument("--source-artifact-digest", default="")
    aggregate.add_argument("--merge-artifact-digest", default="")
    aggregate.add_argument("--workflow-run-id", required=True)
    aggregate.add_argument("--workflow-run-attempt", required=True)
    aggregate.add_argument("--workflow-ref", required=True)
    aggregate.add_argument("--event-name", required=True)
    aggregate.add_argument("--output", required=True)
    aggregate.add_argument("--github-output")
    aggregate.set_defaults(handler=build_aggregate)

    check = commands.add_parser("verify")
    check.add_argument("path")
    check.set_defaults(handler=verify)
    return root


def main() -> int:
    args = parser().parse_args()
    try:
        return args.handler(args)
    except (OSError, ValueError, json.JSONDecodeError) as error:
        print(f"kernel.evidence status error: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
