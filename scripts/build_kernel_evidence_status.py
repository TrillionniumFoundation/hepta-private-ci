#!/usr/bin/env python3
"""Build a fail-closed, exact-candidate kernel.evidence execution status.

A retained CI receipt proves repository execution only. It cannot grant external
acceptance, backend deployment, production activation, canary or release authority.
"""

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
from typing import Any
from urllib.parse import urlsplit

from kernel_evidence_record_validation import (
    EXPECTED_COMMANDS,
    inspect_execution_record,
)

EXPECTED_RECORDS = tuple(EXPECTED_COMMANDS)
HEX_SHA = re.compile(r"^[0-9a-f]{40}(?:[0-9a-f]{24})?$")
ARTIFACT_DIGEST = re.compile(r"^(?:sha256:)?[0-9a-f]{64}$")
POSITIVE_ID = re.compile(r"[1-9][0-9]*\Z")
REPOSITORY = re.compile(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+\Z")


def git(*args: str) -> str:
    return subprocess.check_output(["git", *args], text=True).strip()


def candidate_identity() -> dict[str, Any]:
    return {
        "commit": git("rev-parse", "HEAD"),
        "tree": git("rev-parse", "HEAD^{tree}"),
        "parents": git("rev-list", "--parents", "-n", "1", "HEAD").split()[1:],
        "dirty": bool(git("status", "--porcelain", "--untracked-files=normal")),
    }


def normalize_artifact(args: argparse.Namespace) -> dict[str, Any] | None:
    supplied = (args.artifact_id, args.artifact_url, args.artifact_digest)
    if not any(supplied):
        return None
    if not all(supplied):
        raise ValueError("artifact id, URL and digest must be supplied together")
    if POSITIVE_ID.fullmatch(str(args.artifact_id)) is None:
        raise ValueError("artifact id must be a positive integer")
    repository = os.environ.get("GITHUB_REPOSITORY", "")
    run_id = os.environ.get("GITHUB_RUN_ID", "")
    if (
        REPOSITORY.fullmatch(repository) is None
        or POSITIVE_ID.fullmatch(run_id) is None
    ):
        raise ValueError("artifact needs an explicit repository and workflow run")
    if not isinstance(args.artifact_url, str) or not isinstance(
        args.artifact_digest, str
    ):
        raise ValueError("artifact URL and digest must be strings")
    url = urlsplit(args.artifact_url)
    expected_path = f"/{repository}/actions/runs/{run_id}/artifacts/{args.artifact_id}"
    if (
        url.scheme != "https"
        or url.netloc != "github.com"
        or url.path != expected_path
        or url.query
        or url.fragment
    ):
        raise ValueError(
            "artifact URL does not belong to this repository, run and artifact id"
        )
    if ARTIFACT_DIGEST.fullmatch(args.artifact_digest) is None:
        raise ValueError("artifact digest must be a SHA-256 digest")
    return {
        "id": int(args.artifact_id),
        "url": args.artifact_url,
        "sha256": args.artifact_digest.removeprefix("sha256:"),
    }


def build_status(
    records: Path,
    *,
    kind: str,
    artifact: dict[str, Any] | None = None,
) -> dict[str, Any]:
    identity = candidate_identity()
    source_sha = os.environ.get("SOURCE_SHA", "")
    tested_sha = os.environ.get("TESTED_SHA", "")
    base_sha = os.environ.get("BASE_SHA", "")
    lane = os.environ.get("HEPTA_CI_LANE", "")
    expected_lane = {
        "kernel_evidence_exact_source": "source-head",
        "kernel_evidence_synthetic_merge": "base-merge",
    }[kind]
    identity_errors: list[str] = []
    for label, value in (
        ("sourceSha", source_sha),
        ("testedSha", tested_sha),
        ("commit", identity["commit"]),
        ("tree", identity["tree"]),
    ):
        if not isinstance(value, str) or HEX_SHA.fullmatch(value) is None:
            identity_errors.append(f"{label} is not a lowercase Git object id")
    if base_sha and HEX_SHA.fullmatch(base_sha) is None:
        identity_errors.append("baseSha is not a lowercase Git object id")
    if lane != expected_lane:
        identity_errors.append(f"lane must be {expected_lane}")
    if identity["commit"] != tested_sha:
        identity_errors.append("checked-out commit differs from testedSha")
    if identity["dirty"] is not False:
        identity_errors.append("checkout is dirty")
    if kind == "kernel_evidence_exact_source" and source_sha != tested_sha:
        identity_errors.append("exact-source testedSha differs from sourceSha")
    if kind == "kernel_evidence_synthetic_merge":
        if not base_sha or identity["parents"] != [base_sha, source_sha]:
            identity_errors.append(
                "synthetic merge must have exactly the base/source parents"
            )
        else:
            try:
                if (
                    git("merge-tree", "--write-tree", base_sha, source_sha)
                    != identity["tree"]
                ):
                    identity_errors.append(
                        "synthetic merge tree differs from the recomputed merge"
                    )
            except subprocess.SubprocessError as error:
                identity_errors.append(f"cannot recompute deterministic merge: {error}")
    run_id = os.environ.get("GITHUB_RUN_ID", "")
    attempt = os.environ.get("GITHUB_RUN_ATTEMPT", "")
    job = os.environ.get("GITHUB_JOB", "")
    repository = os.environ.get("GITHUB_REPOSITORY", "")
    if (
        POSITIVE_ID.fullmatch(run_id) is None
        or POSITIVE_ID.fullmatch(attempt) is None
        or not job
    ):
        identity_errors.append("workflow run, attempt and job must be explicit")
    if REPOSITORY.fullmatch(repository) is None:
        identity_errors.append("repository identity is missing or invalid")
    artifact_valid = False
    if artifact is not None:
        try:
            normalized = normalize_artifact(
                argparse.Namespace(
                    artifact_id=artifact["id"],
                    artifact_url=artifact["url"],
                    artifact_digest=artifact["sha256"],
                )
            )
            artifact_valid = normalized == artifact
            if not artifact_valid:
                identity_errors.append("artifact metadata is not normalized")
        except (KeyError, TypeError, ValueError) as error:
            identity_errors.append(f"invalid artifact metadata: {error}")
    expected = {
        "source_sha": source_sha,
        "tested_sha": tested_sha,
        "base_sha": base_sha,
        "lane": lane,
        "run_id": run_id,
        "run_attempt": attempt,
        "job": job,
    }
    working_directory = str(Path(git("rev-parse", "--show-toplevel")).resolve())
    checks = {
        name.removesuffix(".json"): inspect_execution_record(
            records,
            name,
            expected=expected,
            identity=identity,
            working_directory=working_directory,
        )
        for name in EXPECTED_RECORDS
    }
    execution_passed = not identity_errors and all(
        entry["passed"] for entry in checks.values()
    )
    # An unretained execution report is diagnostic, not final qualification.
    qualified = execution_passed and artifact_valid
    return {
        "schemaVersion": 1,
        "module": "kernel.evidence",
        "kind": kind,
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "candidate": {
            "asOfCommit": identity["commit"],
            "asOfTree": identity["tree"],
            "parents": identity["parents"],
            "sourceCommit": source_sha,
            "baseCommit": base_sha or None,
            "testedCommit": tested_sha,
            "lane": lane,
            "dirty": identity["dirty"],
            "identityErrors": identity_errors,
        },
        "workflow": {
            "repository": repository,
            "workflow": os.environ.get("GITHUB_WORKFLOW"),
            "workflowRunId": run_id,
            "workflowRunAttempt": attempt,
            "job": job,
            "event": os.environ.get("GITHUB_EVENT_NAME"),
        },
        "checks": checks,
        "artifact": artifact,
        "executionPassed": bool(execution_passed),
        "receiptRetained": artifact_valid,
        "exactSourceQualified": bool(
            kind == "kernel_evidence_exact_source" and qualified
        ),
        "mergeCandidateQualified": bool(
            kind == "kernel_evidence_synthetic_merge" and qualified
        ),
        "independentAcceptance": False,
        "externalFrontierActive": False,
        "backupRestoreDrilled": False,
        "canaryAccepted": False,
        "releaseApproved": False,
        "qualified": bool(qualified),
        "authority": {
            "selfIssuedReleaseAuthority": False,
            "note": "Repository execution only; external acceptance, deployment, canary and release require separately governed evidence.",
        },
    }


def atomic_write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    pending = Path(name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(value, stream, indent=2, sort_keys=True, allow_nan=False)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        pending.replace(path)
        if os.name == "posix":
            directory = os.open(
                path.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
            )
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
    finally:
        pending.unlink(missing_ok=True)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--records", type=Path, required=True)
    parser.add_argument(
        "--kind",
        choices=("kernel_evidence_exact_source", "kernel_evidence_synthetic_merge"),
        required=True,
    )
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--artifact-id")
    parser.add_argument("--artifact-url")
    parser.add_argument("--artifact-digest")
    parser.add_argument("--require-qualified", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        records = args.records.resolve(strict=True)
        output = args.output.resolve()
        if not records.is_dir() or not output.is_relative_to(records):
            raise ValueError("records must be a directory and output must be inside it")
        artifact = normalize_artifact(args)
        status = build_status(records, kind=args.kind, artifact=artifact)
        atomic_write_json(output, status)
        print(json.dumps(status, sort_keys=True))
        # Keep failed diagnostics, but do not let the final artifact-bearing
        # status step turn an invalid execution receipt into a green CI job.
        return (
            1
            if (args.require_qualified or artifact is not None)
            and not status["qualified"]
            else 0
        )
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        print(f"kernel.evidence status construction failed: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
