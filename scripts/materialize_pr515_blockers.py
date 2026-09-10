#!/usr/bin/env python3
"""Materialize deterministic compact evidence for Hepta PR #515.

Historical receipts contain recursive workflow/job/log payloads and have used
more than one envelope schema. Preserve bounded scalar identity and decisions,
replace unbounded payloads with canonical SHA-256 summaries, and never assume a
single historical ``details.result`` shape.
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
    REPO_ROOT / "qualification/global-gap-closure-final-r8/receipts/PREPARE.json"
)
MAX_REPOSITORY_BLOB_BYTES = 512_000
TARGET_MAX_BYTES = 480_000
MAX_INLINE_STRING_BYTES = 2_048
MAX_RECURSION_DEPTH = 12
COMPACTION_SCHEMA = "hepta.content-addressed-workflow-summary.v3"

RUN_IDENTITY_FIELDS = (
    "id",
    "run_id",
    "database_id",
    "name",
    "workflow_id",
    "workflow_name",
    "branch",
    "head_branch",
    "head_sha",
    "base_sha",
    "status",
    "conclusion",
    "event",
    "run_attempt",
    "created_at",
    "updated_at",
    "started_at",
    "completed_at",
    "url",
    "html_url",
)
FORBIDDEN_RAW_KEYS = {
    "archived_job_logs",
    "raw_job_logs",
    "raw_logs",
    "log_archive",
}


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


def is_inline_scalar(value: Any) -> bool:
    if not is_scalar(value):
        return False
    return not isinstance(value, str) or len(value.encode("utf-8")) <= MAX_INLINE_STRING_BYTES


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
    canonical = canonical_bytes(value)
    summary: dict[str, Any] = {
        "representation": "sha256-summary",
        "source_type": type(value).__name__,
        "canonical_sha256": sha256_bytes(canonical),
        "canonical_bytes": len(canonical),
    }
    if isinstance(value, (dict, list, str)):
        summary["item_count"] = len(value)
    if isinstance(value, list):
        summary["status_counts"] = counter(value, "status")
        summary["conclusion_counts"] = counter(value, "conclusion")
    return summary


def compact_generic_record(value: Any) -> Any:
    if not isinstance(value, dict):
        return payload_summary(value)
    compacted: dict[str, Any] = {}
    omitted: dict[str, Any] = {}
    for key, child in value.items():
        if key in FORBIDDEN_RAW_KEYS:
            omitted[key] = payload_summary(child)
        elif is_inline_scalar(child):
            compacted[key] = child
        else:
            omitted[key] = payload_summary(child)
    if omitted:
        compacted["_omitted_payloads"] = omitted
    return compacted


def compact_job(value: Any) -> Any:
    if not isinstance(value, dict):
        return payload_summary(value)
    compacted: dict[str, Any] = {}
    omitted: dict[str, Any] = {}
    for key, child in value.items():
        if key in FORBIDDEN_RAW_KEYS or key == "steps":
            omitted[key] = payload_summary(child)
        elif is_inline_scalar(child):
            compacted[key] = child
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
        if key in FORBIDDEN_RAW_KEYS:
            omitted[key] = payload_summary(child)
        elif is_inline_scalar(child):
            compacted[key] = child
        elif key == "jobs" and isinstance(child, list) and include_jobs:
            compacted[key] = [compact_job(job) for job in child]
        elif key == "artifacts" and isinstance(child, list):
            compacted[key] = [compact_generic_record(item) for item in child]
        else:
            omitted[key] = payload_summary(child)
    if omitted:
        compacted["_omitted_payloads"] = omitted
    return compacted


def compact_run_identity(value: Any) -> Any:
    if not isinstance(value, dict):
        return payload_summary(value)
    compacted = {
        key: value[key]
        for key in RUN_IDENTITY_FIELDS
        if key in value and is_inline_scalar(value[key])
    }
    compacted["_source"] = payload_summary(value)
    return compacted


def compact_status(value: Any, *, child_profile: str) -> Any:
    if not isinstance(value, dict):
        return payload_summary(value)
    compacted: dict[str, Any] = {}
    omitted: dict[str, Any] = {}
    children = value.get("children")
    for key, child in value.items():
        if key in FORBIDDEN_RAW_KEYS:
            omitted[key] = payload_summary(child)
        elif key == "children" and isinstance(child, list):
            if child_profile == "jobs":
                compacted[key] = [compact_run(item, include_jobs=True) for item in child]
            elif child_profile == "scalars":
                compacted[key] = [compact_run(item, include_jobs=False) for item in child]
            elif child_profile == "minimal":
                compacted[key] = [compact_run_identity(item) for item in child]
            elif child_profile == "summary":
                compacted[key] = payload_summary(child)
            else:
                raise ValueError(f"unknown child profile: {child_profile}")
        elif is_inline_scalar(child):
            compacted[key] = child
        elif isinstance(child, dict):
            compacted[key] = compact_generic_record(child)
        else:
            omitted[key] = payload_summary(child)
    if omitted:
        compacted["_omitted_payloads"] = omitted
    if isinstance(children, list):
        compacted["children_compaction"] = {
            "source": payload_summary(children),
            "profile": child_profile,
            "child_count": len(children),
        }
    compacted["_compaction_schema"] = COMPACTION_SCHEMA
    return compacted


def compact_tree(value: Any, *, depth: int, profile: str) -> Any:
    """Compact an arbitrary historical envelope without changing dict shape."""
    if is_inline_scalar(value):
        return value
    if is_scalar(value):
        return payload_summary(value)
    if depth >= MAX_RECURSION_DEPTH:
        return payload_summary(value)
    if isinstance(value, list):
        if profile == "detailed" and len(value) <= 64:
            return [compact_tree(item, depth=depth + 1, profile=profile) for item in value]
        if profile == "minimal" and len(value) <= 16:
            return [compact_tree(item, depth=depth + 1, profile="summary") for item in value]
        return payload_summary(value)
    if not isinstance(value, dict):
        return payload_summary(value)

    compacted: dict[str, Any] = {}
    omitted: dict[str, Any] = {}
    for key, child in value.items():
        if key in FORBIDDEN_RAW_KEYS:
            omitted[key] = payload_summary(child)
        elif key == "steps" and isinstance(child, list):
            omitted[key] = payload_summary(child)
        elif key == "runs" and isinstance(child, list):
            if profile == "detailed":
                compacted[key] = [compact_run(run, include_jobs=False) for run in child]
            elif profile == "minimal":
                compacted[key] = [compact_run_identity(run) for run in child]
            else:
                compacted[key] = payload_summary(child)
            compacted[f"{key}_compaction"] = payload_summary(child)
        elif key == "jobs" and isinstance(child, list):
            compacted[key] = (
                [compact_job(job) for job in child]
                if profile == "detailed"
                else payload_summary(child)
            )
        elif key == "status" and isinstance(child, dict):
            compacted[key] = compact_status(child, child_profile="minimal")
        else:
            compacted[key] = compact_tree(
                child,
                depth=depth + 1,
                profile=profile,
            )
    if omitted:
        compacted["_omitted_payloads"] = omitted
    return compacted


def compaction_metadata(raw: bytes, *, profile: str) -> dict[str, Any]:
    parsed = json.loads(raw)
    return {
        "schema": COMPACTION_SCHEMA,
        "profile": profile,
        "source_bytes": len(raw),
        "source_sha256": sha256_bytes(raw),
        "canonical_source_sha256": value_digest(parsed),
        "max_inline_string_bytes": MAX_INLINE_STRING_BYTES,
        "policy": (
            "retain bounded decision/identity scalars and historical dictionary "
            "shape; represent recursive or unbounded payloads by canonical SHA-256, "
            "canonical byte count, item count, and outcome counts"
        ),
    }


def encode(value: Any) -> bytes:
    return canonical_bytes(value) + b"\n"


def largest_fields(value: Any, *, limit: int = 12) -> str:
    if not isinstance(value, dict):
        return f"root={type(value).__name__}:{len(canonical_bytes(value))}"
    rows = sorted(
        (
            (len(canonical_bytes(child)), key, type(child).__name__)
            for key, child in value.items()
        ),
        reverse=True,
    )[:limit]
    return ", ".join(f"{key}:{kind}:{size}" for size, key, kind in rows)


def write_checked(path: Path, value: Any) -> None:
    encoded = encode(value)
    if len(encoded) > TARGET_MAX_BYTES:
        raise SystemExit(
            f"{path.relative_to(REPO_ROOT)} remains too large: {len(encoded)} bytes; "
            f"largest_fields={largest_fields(value)}"
        )
    if len(encoded) > MAX_REPOSITORY_BLOB_BYTES:
        raise SystemExit(
            f"{path.relative_to(REPO_ROOT)} exceeds repository blob policy: {len(encoded)} bytes"
        )
    path.write_bytes(encoded)
    reparsed = json.loads(path.read_bytes())
    if canonical_bytes(reparsed) != encoded.rstrip(b"\n"):
        raise SystemExit(f"{path.relative_to(REPO_ROOT)} is not canonical JSON")


def compact_status_file() -> None:
    raw = STATUS_PATH.read_bytes()
    original = json.loads(raw)
    compacted: Any = None
    for child_profile, metadata_profile in (
        ("jobs", "historical-status-with-job-identities"),
        ("scalars", "historical-status-child-scalars"),
        ("minimal", "historical-status-minimal-child-identities"),
        ("summary", "historical-status-content-addressed-child-summary"),
    ):
        candidate = compact_status(original, child_profile=child_profile)
        candidate["_compaction"] = compaction_metadata(raw, profile=metadata_profile)
        compacted = candidate
        if len(encode(candidate)) <= TARGET_MAX_BYTES:
            break
    write_checked(STATUS_PATH, compacted)


def compact_prepare_file() -> None:
    raw = PREPARE_PATH.read_bytes()
    original = json.loads(raw)
    if not isinstance(original, dict):
        raise SystemExit("PREPARE.json root is not an object")

    compacted: Any = None
    for profile in ("detailed", "minimal", "summary"):
        candidate = compact_tree(original, depth=0, profile=profile)
        if not isinstance(candidate, dict):
            raise SystemExit("PREPARE.json compacted root is not an object")
        candidate["_compaction"] = compaction_metadata(
            raw,
            profile=f"schema-independent-{profile}",
        )
        compacted = candidate
        if len(encode(candidate)) <= TARGET_MAX_BYTES:
            break
    write_checked(PREPARE_PATH, compacted)


def verify_no_recursive_payloads() -> None:
    status = json.loads(STATUS_PATH.read_bytes())
    prepare = json.loads(PREPARE_PATH.read_bytes())
    for path, value in ((STATUS_PATH, status), (PREPARE_PATH, prepare)):
        if len(path.read_bytes()) > TARGET_MAX_BYTES:
            raise SystemExit(f"compacted file exceeds target: {path}")
        if value.get("_compaction", {}).get("schema") != COMPACTION_SCHEMA:
            raise SystemExit(f"missing compaction provenance: {path}")

    stack: list[Any] = [status, prepare]
    while stack:
        value = stack.pop()
        if isinstance(value, dict):
            if FORBIDDEN_RAW_KEYS.intersection(value):
                raise SystemExit("raw archived job logs remain in compacted evidence")
            for key, child in value.items():
                if key == "steps" and isinstance(child, list):
                    raise SystemExit("raw workflow steps remain in compacted evidence")
                stack.append(child)
        elif isinstance(value, list):
            stack.extend(value)
        elif isinstance(value, str) and len(value.encode("utf-8")) > MAX_INLINE_STRING_BYTES:
            raise SystemExit("unbounded string remains in compacted evidence")


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
