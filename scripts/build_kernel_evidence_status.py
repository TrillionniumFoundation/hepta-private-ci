#!/usr/bin/env python3
"""Build one fail-closed machine-readable kernel.evidence qualification status.

The status is an execution receipt, not a self-issued release decision. It binds
all command records and retained logs to the exact Git candidate. Missing,
malformed, rejected, interrupted, or failed records are represented explicitly
and can never be interpreted as qualification success.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from typing import Any

EXPECTED_RECORDS = (
    "evidence-tests.json",
    "agentd-product-test.json",
    "lane-a-truth.json",
    "docs.json",
    "implementation-maps.json",
)
HEX_SHA = re.compile(r"^[0-9a-f]{40}(?:[0-9a-f]{24})?$")
ARTIFACT_DIGEST = re.compile(r"^(?:sha256:)?[0-9a-f]{64}$")


def git(*args: str) -> str:
    return subprocess.check_output(["git", *args], text=True).strip()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def read_record(path: Path) -> tuple[dict[str, Any] | None, str | None]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        return None, str(error)
    if not isinstance(value, dict):
        return None, "record root must be an object"
    return value, None


def candidate_identity() -> dict[str, Any]:
    commit = git("rev-parse", "HEAD")
    tree = git("rev-parse", "HEAD^{tree}")
    parents = git("rev-list", "--parents", "-n", "1", "HEAD").split()[1:]
    dirty = bool(git("status", "--porcelain", "--untracked-files=normal"))
    return {"commit": commit, "tree": tree, "parents": parents, "dirty": dirty}


def normalize_artifact(args: argparse.Namespace) -> dict[str, Any] | None:
    supplied = (args.artifact_id, args.artifact_url, args.artifact_digest)
    if not any(supplied):
        return None
    if not all(supplied):
        raise ValueError("artifact id, URL and digest must be supplied together")
    if not str(args.artifact_id).isdigit() or int(args.artifact_id) <= 0:
        raise ValueError("artifact id must be a positive integer")
    if not args.artifact_url.startswith("https://github.com/"):
        raise ValueError("artifact URL must be an authenticated GitHub URL")
    if ARTIFACT_DIGEST.fullmatch(args.artifact_digest) is None:
        raise ValueError("artifact digest must be a SHA-256 digest")
    digest = args.artifact_digest.removeprefix("sha256:")
    return {
        "id": int(args.artifact_id),
        "url": args.artifact_url,
        "sha256": digest,
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
    for label, value in (("sourceSha", source_sha), ("testedSha", tested_sha)):
        if HEX_SHA.fullmatch(value) is None:
            identity_errors.append(
                f"{label} is not a 40- or 64-character lowercase object id"
            )
    if base_sha and HEX_SHA.fullmatch(base_sha) is None:
        identity_errors.append(
            "baseSha is not a 40- or 64-character lowercase object id"
        )
    if lane != expected_lane:
        identity_errors.append(f"lane must be {expected_lane}")
    if tested_sha and identity["commit"] != tested_sha:
        identity_errors.append("checked-out commit differs from testedSha")
    if identity["dirty"]:
        identity_errors.append("checkout is dirty")
    if kind == "kernel_evidence_exact_source" and source_sha != tested_sha:
        identity_errors.append("exact-source testedSha differs from sourceSha")
    if kind == "kernel_evidence_synthetic_merge":
        expected_parents = [base_sha, source_sha]
        if identity["parents"] != expected_parents:
            identity_errors.append("synthetic merge parents differ from base/source")
        if len(identity["parents"]) != 2:
            identity_errors.append("synthetic merge must have exactly two parents")

    checks: dict[str, Any] = {}
    all_passed = not identity_errors
    for name in EXPECTED_RECORDS:
        path = records / name
        entry: dict[str, Any] = {
            "path": name,
            "present": path.is_file(),
            "sha256": sha256_file(path) if path.is_file() else None,
            "bytes": path.stat().st_size if path.is_file() else None,
            "status": "missing",
            "exitCode": None,
            "commandExitCode": None,
            "log": None,
            "error": None,
        }
        if path.is_file():
            record, error = read_record(path)
            if error is not None:
                entry["status"] = "malformed"
                entry["error"] = error
            else:
                assert record is not None
                entry["status"] = record.get("status", "malformed")
                entry["exitCode"] = record.get("exit_code")
                entry["commandExitCode"] = record.get("command_exit_code")
                entry["error"] = record.get("error")
                log_name = record.get("log_file")
                if isinstance(log_name, str) and log_name:
                    log_path = records / log_name
                    entry["log"] = {
                        "path": log_name,
                        "present": log_path.is_file(),
                        "sha256": sha256_file(log_path)
                        if log_path.is_file()
                        else None,
                        "bytes": log_path.stat().st_size
                        if log_path.is_file()
                        else None,
                    }
                if (
                    record.get("tested_sha") != tested_sha
                    or record.get("source_sha") != source_sha
                    or record.get("base_sha", "") != base_sha
                    or record.get("lane") != lane
                ):
                    entry["status"] = "identity_mismatch"
                    entry["error"] = (
                        "execution record identity differs from candidate"
                    )
        passed = (
            entry["present"]
            and entry["status"] == "passed"
            and entry["exitCode"] == 0
            and entry["commandExitCode"] == 0
            and isinstance(entry["log"], dict)
            and entry["log"]["present"]
        )
        entry["passed"] = passed
        all_passed = all_passed and passed
        checks[name.removesuffix(".json")] = entry

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
            "repository": os.environ.get("GITHUB_REPOSITORY"),
            "workflow": os.environ.get("GITHUB_WORKFLOW"),
            "workflowRunId": os.environ.get("GITHUB_RUN_ID"),
            "workflowRunAttempt": os.environ.get("GITHUB_RUN_ATTEMPT"),
            "job": os.environ.get("GITHUB_JOB"),
            "event": os.environ.get("GITHUB_EVENT_NAME"),
        },
        "checks": checks,
        "artifact": artifact,
        "exactSourceQualified": bool(
            kind == "kernel_evidence_exact_source" and all_passed
        ),
        "mergeCandidateQualified": bool(
            kind == "kernel_evidence_synthetic_merge" and all_passed
        ),
        "independentAcceptance": False,
        "externalFrontierActive": False,
        "backupRestoreDrilled": False,
        "canaryAccepted": False,
        "releaseApproved": False,
        "qualified": bool(all_passed),
        "authority": {
            "selfIssuedReleaseAuthority": False,
            "note": (
                "This receipt establishes repository execution only. Independent "
                "acceptance, external rollback-domain deployment, canary, promotion "
                "and release remain separately governed."
            ),
        },
    }


def atomic_write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    pending = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        with pending.open("x", encoding="utf-8") as stream:
            json.dump(value, stream, indent=2, sort_keys=True)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        pending.replace(path)
    finally:
        pending.unlink(missing_ok=True)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--records", type=Path, required=True)
    parser.add_argument(
        "--kind",
        choices=(
            "kernel_evidence_exact_source",
            "kernel_evidence_synthetic_merge",
        ),
        required=True,
    )
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--artifact-id")
    parser.add_argument("--artifact-url")
    parser.add_argument("--artifact-digest")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        records = args.records.resolve(strict=True)
        output = args.output.resolve()
        if not records.is_dir():
            raise ValueError("records must be a directory")
        if not output.is_relative_to(records):
            raise ValueError("status output must be inside the records directory")
        artifact = normalize_artifact(args)
        status = build_status(records, kind=args.kind, artifact=artifact)
        atomic_write_json(output, status)
        print(json.dumps(status, sort_keys=True))
        return 0
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        print(
            f"kernel.evidence status construction failed: {error}",
            file=sys.stderr,
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
