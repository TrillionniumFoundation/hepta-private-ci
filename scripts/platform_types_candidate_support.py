"""Shared exact-candidate evidence primitives for platform.types."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from lane_a_foundation_lib import (
    CANDIDATE_KINDS,
    candidate_identity,
    canonical,
    exact_source,
)

ROOT = Path(__file__).resolve().parents[1]
OUTCOMES = frozenset({"success", "failure", "cancelled", "skipped"})
REQUIRED_OUTCOMES = frozenset({"truth", "msrv", "native", "miri", "bundle"})


class CandidateBundleError(RuntimeError):
    """The exact-candidate documentation or evidence bundle is invalid."""


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: Path) -> str:
    try:
        return sha256_bytes(path.read_bytes())
    except OSError as error:
        raise CandidateBundleError(f"cannot hash {path}: {error}") from error


def read_object(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise CandidateBundleError(f"cannot read JSON {path}: {error}") from error
    if not isinstance(value, dict):
        raise CandidateBundleError(f"JSON object required: {path}")
    return value


def write_object(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def exact_identity(args: Any) -> dict[str, Any]:
    candidate_sha, candidate_tree = exact_source(args.expected_sha)
    return candidate_identity(
        args.candidate_kind,
        candidate_sha,
        candidate_tree,
        source_sha=args.source_sha,
        base_sha=args.base_sha,
        pull_request_number=args.pr_number,
    )


def identity_sha256(identity: dict[str, Any]) -> str:
    return sha256_bytes(canonical(identity))


def parse_named_values(values: list[str], *, outcomes: bool) -> dict[str, str]:
    parsed: dict[str, str] = {}
    for value in values:
        if "=" not in value:
            raise CandidateBundleError(f"name=value required: {value!r}")
        name, item = value.split("=", 1)
        if not name or not item or name in parsed:
            raise CandidateBundleError(f"invalid or duplicate named value: {value!r}")
        if outcomes and item not in OUTCOMES:
            raise CandidateBundleError(f"invalid outcome for {name}: {item!r}")
        parsed[name] = item
    if not parsed:
        raise CandidateBundleError("at least one named value is required")
    return parsed


def require_outcome_set(outcomes: dict[str, str]) -> None:
    actual = frozenset(outcomes)
    if actual != REQUIRED_OUTCOMES:
        missing = sorted(REQUIRED_OUTCOMES - actual)
        extra = sorted(actual - REQUIRED_OUTCOMES)
        raise CandidateBundleError(f"outcome set mismatch; missing={missing}, extra={extra}")


def evidence_records(values: list[str], *, require_existing: bool) -> dict[str, Any]:
    named = parse_named_values(values, outcomes=False)
    records: dict[str, Any] = {}
    for name, supplied in named.items():
        path = Path(supplied)
        if not path.is_absolute():
            path = ROOT / path
        exists = path.is_file()
        if require_existing and not exists:
            raise CandidateBundleError(f"required evidence is missing: {name}={path}")
        try:
            shown = str(path.relative_to(ROOT))
        except ValueError:
            shown = str(path)
        record: dict[str, Any] = {"path": shown, "exists": exists}
        if exists:
            record.update({"sha256": sha256_file(path), "bytes": path.stat().st_size})
        records[name] = record
    return records


def resolve_record_path(record: dict[str, Any]) -> Path:
    path = Path(str(record["path"]))
    return path if path.is_absolute() else ROOT / path
