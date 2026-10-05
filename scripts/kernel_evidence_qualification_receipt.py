#!/usr/bin/env python3
"""Write one exact, machine-verifiable kernel.evidence qualification receipt."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile

OID = re.compile(r"(?:[0-9a-f]{40}|[0-9a-f]{64})\Z")
KINDS = {
    "exact_source",
    "deterministic_merge",
    "metadata",
    "publication_diagnostics",
}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def atomic_json(path: Path, value: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        dir=path.parent, prefix=".qualification-receipt-"
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(value, stream, indent=2, sort_keys=True, allow_nan=False)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def require_oid(value: str, label: str, *, optional: bool = False) -> None:
    if optional and not value:
        return
    if OID.fullmatch(value) is None:
        raise ValueError(f"{label} must be a full lowercase Git object id")


def build_receipt(args: argparse.Namespace) -> dict[str, object]:
    if args.kind not in KINDS:
        raise ValueError(f"unsupported qualification kind: {args.kind}")
    for label, value in (
        ("source head", args.source_head_sha),
        ("source tree", args.source_head_tree),
        ("base", args.base_sha),
        ("workflow", args.workflow_sha),
        ("tested object", args.tested_object_sha),
    ):
        require_oid(value, label)
    require_oid(args.deterministic_merge_sha, "deterministic merge", optional=True)
    if args.kind == "deterministic_merge":
        if not args.deterministic_merge_sha:
            raise ValueError("deterministic merge receipt requires a merge SHA")
        if args.tested_object_sha != args.deterministic_merge_sha:
            raise ValueError("tested object must equal deterministic merge SHA")
    elif args.tested_object_sha != args.source_head_sha:
        raise ValueError("non-merge receipt must test the exact source head")
    if args.started_at_unix_ms <= 0 or args.finished_at_unix_ms < args.started_at_unix_ms:
        raise ValueError("receipt timestamps are invalid")
    if not args.command or not args.workflow_run_id or not args.workflow_run_attempt:
        raise ValueError("command and workflow run identity are required")
    if not args.log.is_file():
        raise ValueError(f"qualification log does not exist: {args.log}")
    passed = args.exit_code == 0
    return {
        "schemaVersion": 2,
        "module": "kernel.evidence",
        "receiptKind": "candidate_qualification",
        "kind": args.kind,
        "sourceHeadSha": args.source_head_sha,
        "sourceHeadTree": args.source_head_tree,
        "baseSha": args.base_sha,
        "deterministicMergeSha": args.deterministic_merge_sha or None,
        "testedObjectSha": args.tested_object_sha,
        "workflowSha": args.workflow_sha,
        "workflowRunId": args.workflow_run_id,
        "workflowRunAttempt": args.workflow_run_attempt,
        "runnerImage": args.runner_image,
        "targetTriple": args.target_triple,
        "command": args.command,
        "startedAtUnixMs": args.started_at_unix_ms,
        "finishedAtUnixMs": args.finished_at_unix_ms,
        "exitCode": args.exit_code,
        "status": "passed" if passed else "failed",
        "passed": passed,
        "logPath": str(args.log),
        "logSha256": sha256_file(args.log),
        "logBytes": args.log.stat().st_size,
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "qualificationGranted": False,
        "independentAcceptanceGranted": False,
        "productionActivationGranted": False,
        "releaseGranted": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--kind", required=True)
    parser.add_argument("--source-head-sha", required=True)
    parser.add_argument("--source-head-tree", required=True)
    parser.add_argument("--base-sha", required=True)
    parser.add_argument("--deterministic-merge-sha", default="")
    parser.add_argument("--tested-object-sha", required=True)
    parser.add_argument("--workflow-sha", required=True)
    parser.add_argument("--workflow-run-id", required=True)
    parser.add_argument("--workflow-run-attempt", required=True)
    parser.add_argument("--runner-image", required=True)
    parser.add_argument("--target-triple", required=True)
    parser.add_argument("--command", required=True)
    parser.add_argument("--started-at-unix-ms", type=int, required=True)
    parser.add_argument("--finished-at-unix-ms", type=int, required=True)
    parser.add_argument("--exit-code", type=int, required=True)
    parser.add_argument("--log", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        receipt = build_receipt(args)
        atomic_json(args.output, receipt)
        print(json.dumps(receipt, sort_keys=True))
        return 0
    except (OSError, ValueError, json.JSONDecodeError) as error:
        print(json.dumps({"passed": False, "error": str(error)}, sort_keys=True))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
