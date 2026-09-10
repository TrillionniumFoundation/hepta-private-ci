#!/usr/bin/env python3
"""Materialize the deterministic repository-only fixes for Hepta PR #515.

The two qualification files handled here are historical receipts.  Their
original representation recursively embedded complete workflow, job, step, and
archived-log payloads.  This script keeps identity and decision fields while
replacing non-decision payloads with content-addressed summaries.
"""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
STATUS_PATH = REPO_ROOT / "qualification/global-gap-closure-final-r6/STATUS.json"
PREPARE_PATH = (
    REPO_ROOT
    / "qualification/global-gap-closure-final-r8/receipts/PREPARE.json"
)
MAX_REPOSITORY_BLOB_BYTES = 512_000
TARGET_MAX_BYTES = 480_000
COMPACTION_SCHEMA = "hepta.content-addressed-workflow-summary.v1"

Scalar = str | int | float | bool | None


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def value_digest(value: Any) -> str:
    return sha256_bytes(canonical_bytes(value))


def is_scalar(value: Any) -> bool:
    return value is None or isinstance(value, (str, int, float, bool))


def counter(values: list[Any], key: str) -> dict[str, int]:
    counts: Counter[str] = Counter()
    for value in values:
        if isinstance(value, dict):
            item = value.get(key)
            counts["null" if item is None else str(item)] += 1
        else:
            counts[f"<{type(value).__name__}>"] += 1
    return dict(sorted(counts.items()))


def payload_summary(value: Any) -> dict[str, Any]:
    summary: dict[str, Any] = {
        "representation": "sha256-summary",
        "source_type": type(value).__name__,
        "canonical_sha256": value_digest(value),
        "canonical_bytes": len(canonical_bytes(value)),
    }
    if isinstance(value, (dict, list, str)):
        summary["item_count"] = len(value)
    if isinstance(value, list):
        summary["status_counts"] = counter(value, "status")
        summary["conclusion_counts"] = counter(value, "conclusion")
    return summary


def compact_generic_record(
    value: Any,
    *,
    nested_record_fields: frozenset[str] = frozenset(),
) -> Any:
    if not isinstance(value, dict):
        return payload_summary(value)

    compacted: dict[str, Any] = {}
    omitted: dict[str, Any] = {}
    for key, child in value.items():
        if is_scalar(child):
            compacted[key] = child
        elif key in nested_record_fields and isinstance(child, list):
            compacted[key] = [compact_generic_record(item) for item in child]
        else:
            omitted[key] = payload_summary(child)
    if omitted:
        compacted["_omitted_payloads"] = omitted
    return compacted


def compact_job(value: Any, *, keep_steps: bool = False) -> Any:
    if not isinstance(value, dict):
        return payload_summary(value)

    compacted: dict[str, Any] = {}
    omitted: dict[str, Any] = {}
    for key, child in value.items():
        if is_scalar(child):
            compacted[key] = child
        elif key == "steps" and isinstance(child, list) and keep_steps:
            compacted[key] = [compact_generic_record(step) for step in child]
        else:
            omitted[key] = payload_summary(child)
    if omitted:
        compacted["_omitted_payloads"] = omitted
    return compacted


def compact_run(value: Any, *, include_jobs: bool) -> Any:
    if not isinstance(value, dict):
        return payload_summary(value)

    compacted: dict[str, Any] = {}
    omitted: dict[str, Any] = {}
    for key, child in value.items():
        if is_scalar(child):
            compacted[key] = child
        elif key == "jobs" and isinstance(child, list) and include_jobs:
            compacted[key] = [compact_job(job) for job in child]
        elif key == "artifacts" and isinstance(child, list):
            compacted[key] = [compact_generic_record(artifact) for artifact in child]
        else:
            omitted[key] = payload_summary(child)
    if omitted:
        compacted["_omitted_payloads"] = omitted
    return compacted


def compact_status(value: Any, *, include_child_jobs: bool) -> Any:
    if not isinstance(value, dict):
        return payload_summary(value)

    compacted = dict(value)
    children = value.get("children")
    if isinstance(children, list):
        compacted["children"] = [
            compact_run(child, include_jobs=include_child_jobs) for child in children
        ]
        compacted["children_compaction"] = {
            "source": payload_summary(children),
            "retained_fields": "all scalar child fields and content-addressed nested summaries",
            "child_jobs_included": include_child_jobs,
        }
    compacted["_compaction_schema"] = COMPACTION_SCHEMA
    return compacted


def compaction_metadata(raw: bytes, *, profile: str) -> dict[str, Any]:
    return {
        "schema": COMPACTION_SCHEMA,
        "profile": profile,
        "source_bytes": len(raw),
        "source_sha256": sha256_bytes(raw),
        "canonical_source_sha256": value_digest(json.loads(raw)),
        "policy": (
            "retain decision/identity scalars; represent nested workflow, job, step, "
            "artifact, and archived-log payloads by canonical SHA-256, byte count, and counts"
        ),
    }


def encode(value: Any) -> bytes:
    return canonical_bytes(value) + b"\n"


def write_checked(path: Path, value: Any) -> None:
    encoded = encode(value)
    if len(encoded) > TARGET_MAX_BYTES:
        raise SystemExit(
            f"{path.relative_to(REPO_ROOT)} remains too large: {len(encoded)} bytes"
        )
    if len(encoded) > MAX_REPOSITORY_BLOB_BYTES:
        raise SystemExit(
            f"{path.relative_to(REPO_ROOT)} exceeds repository blob policy: "
            f"{len(encoded)} bytes"
        )
    path.write_bytes(encoded)
    reparsed = json.loads(path.read_bytes())
    if canonical_bytes(reparsed) != encoded.rstrip(b"\n"):
        raise SystemExit(f"{path.relative_to(REPO_ROOT)} is not canonical JSON")


def compact_status_file() -> None:
    raw = STATUS_PATH.read_bytes()
    original = json.loads(raw)
    compacted = compact_status(original, include_child_jobs=True)
    compacted["_compaction"] = compaction_metadata(
        raw, profile="historical-status-with-job-identities"
    )
    encoded = encode(compacted)
    if len(encoded) > TARGET_MAX_BYTES:
        compacted = compact_status(original, include_child_jobs=False)
        compacted["_compaction"] = compaction_metadata(
            raw, profile="historical-status-child-identities-only"
        )
    write_checked(STATUS_PATH, compacted)


def compact_prepare_file() -> None:
    raw = PREPARE_PATH.read_bytes()
    original = json.loads(raw)
    compacted = dict(original)

    details = original.get("details")
    if not isinstance(details, dict):
        raise SystemExit("PREPARE.json details is not an object")
    compact_details = dict(details)

    result = details.get("result")
    if not isinstance(result, dict):
        raise SystemExit("PREPARE.json details.result is not an object")
    compact_result = dict(result)

    runs = result.get("runs")
    if not isinstance(runs, list):
        raise SystemExit("PREPARE.json details.result.runs is not an array")
    compact_result["runs"] = [
        compact_run(run, include_jobs=False) for run in runs
    ]
    compact_result["runs_compaction"] = {
        "source": payload_summary(runs),
        "retained_fields": "all scalar run fields and content-addressed nested summaries",
        "run_count": len(runs),
    }

    status = result.get("status")
    if isinstance(status, dict):
        compact_result["status"] = compact_status(
            status, include_child_jobs=False
        )
        compact_result["status_compaction"] = payload_summary(status)

    compact_details["result"] = compact_result
    compacted["details"] = compact_details
    compacted["_compaction"] = compaction_metadata(
        raw, profile="prepare-run-identities-and-status-summary"
    )

    encoded = encode(compacted)
    if len(encoded) > TARGET_MAX_BYTES:
        # A second deterministic tier retains only the run fields needed to bind
        # observation identity and outcome.  Every omitted field remains bound
        # by the per-run canonical digest.
        compact_result["runs"] = [
            {
                **{
                    key: run[key]
                    for key in (
                        "id",
                        "name",
                        "branch",
                        "head_sha",
                        "status",
                        "conclusion",
                        "event",
                        "run_attempt",
                        "created_at",
                        "updated_at",
                        "url",
                    )
                    if isinstance(run, dict) and key in run and is_scalar(run[key])
                },
                "_source": payload_summary(run),
            }
            for run in runs
        ]
        compact_result["runs_compaction"]["retained_fields"] = (
            "run identity/outcome scalars plus canonical source digest"
        )
        compacted["_compaction"]["profile"] = (
            "prepare-minimal-run-identities-and-status-summary"
        )

    write_checked(PREPARE_PATH, compacted)


def verify_no_recursive_payloads() -> None:
    status = json.loads(STATUS_PATH.read_bytes())
    prepare = json.loads(PREPARE_PATH.read_bytes())

    for path, value in ((STATUS_PATH, status), (PREPARE_PATH, prepare)):
        encoded = path.read_bytes()
        if len(encoded) > TARGET_MAX_BYTES:
            raise SystemExit(f"compacted file exceeds target: {path}")
        if value.get("_compaction", {}).get("schema") != COMPACTION_SCHEMA:
            raise SystemExit(f"missing compaction provenance: {path}")

    forbidden_keys = {"archived_job_logs"}
    stack: list[Any] = [status, prepare]
    while stack:
        value = stack.pop()
        if isinstance(value, dict):
            if forbidden_keys.intersection(value):
                raise SystemExit("raw archived job logs remain in compacted evidence")
            for key, child in value.items():
                if key == "steps" and isinstance(child, list):
                    raise SystemExit("raw workflow steps remain in compacted evidence")
                stack.append(child)
        elif isinstance(value, list):
            stack.extend(value)


def main() -> int:
    compact_status_file()
    compact_prepare_file()
    verify_no_recursive_payloads()
    print(
        "PASS_PR515_EVIDENCE_COMPACTION "
        f"status_bytes={STATUS_PATH.stat().st_size} "
        f"prepare_bytes={PREPARE_PATH.stat().st_size}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
