#!/usr/bin/env python3
"""Validate pending process-cut obligations, never certify their execution."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
MATRIX = ROOT / "docs/modules/intelligence.control/FAULT_MATRIX.json"
IDENTITY = {"commit": "CI_EXACT_HEAD", "lane": "tracked", "executionStatus": "pending"}
BOUNDARY = "exact candidate qualification-host artifact"
EXPECTED_CUTS = {
    "before_sidecar_temp_write": ("learning-sidecar", "NotDispatched"),
    "after_sidecar_write_before_fsync": ("learning-sidecar", "Indeterminate"),
    "after_file_fsync_before_rename": ("learning-sidecar", "Indeterminate"),
    "after_rename_before_directory_fsync": ("learning-sidecar", "Indeterminate"),
    "before_intent_commit": ("operation-intent", "NotDispatched"),
    "after_intent_commit": ("operation-intent", "Prepared"),
    "after_claim": ("operation-claim", "Prepared"),
    # A pre-entry observation cannot undo a committed dispatch or lost ACK.
    "before_provider_entry": ("physical-provider", "ReconcileOnly"),
    "after_provider_entry_before_terminal": ("physical-provider", "ReconcileOnly"),
    "after_terminal_before_learning_ack": ("physical-terminal", "ReconcileOnly"),
    "after_ledger_append_before_witness": ("learning-ledger", "ReconcileOnly"),
    "after_witness_before_operation_ack": ("learning-ledger", "ReconcileOnly"),
    "hard_timeout_exit_70": ("process-fence", "ReplaceOwner"),
    "supervisor_successor_generation_adoption": ("process-fence", "ReplaceOwner"),
    "lost_provider_ack": ("physical-provider", "ReconcileOnly"),
    "lost_ledger_ack": ("learning-ledger", "ReconcileOnly"),
}
EXPECTED_INVARIANTS = [
    "no_duplicate_physical_effect",
    "unknown_never_becomes_not_started",
    "same_operation_identity",
    "old_generation_cannot_commit",
    "destination_first_reconciliation",
    "already_applied_requires_no_new_write_grant",
    "expired_first_application_rejected",
    "witness_lag_not_applied",
    "corruption_and_clock_rollback_not_retry",
]


def require_keys(value: Any, keys: set[str], label: str) -> None:
    if not isinstance(value, dict) or set(value) != keys:
        raise ValueError(f"unsupported {label} fields")


def load_json(path: Path) -> dict[str, Any]:
    """Reject duplicate keys, linked paths and oversized declaration files."""
    if not path.is_absolute():
        path = ROOT / path
    if not path.is_relative_to(ROOT):
        raise ValueError("declaration path outside repository")
    current = ROOT
    for part in path.relative_to(ROOT).parts:
        if part in (".", ".."):
            raise ValueError("noncanonical declaration path")
        current /= part
        if current.is_symlink():
            raise ValueError("linked declaration path")
    if not path.is_file() or path.stat().st_size > 128 * 1024:
        raise ValueError("missing or oversized declaration")

    def unique(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        value: dict[str, Any] = {}
        for key, item in pairs:
            if key in value:
                raise ValueError(f"duplicate JSON field: {key}")
            value[key] = item
        return value

    value = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=unique)
    if not isinstance(value, dict):
        raise ValueError("declaration must be an object")
    return value


def validate(value: dict[str, Any] | None = None) -> dict[str, Any]:
    value = load_json(MATRIX) if value is None else value
    require_keys(
        value,
        {
            "schema",
            "schemaVersion",
            "module",
            "executionStatus",
            "sourceIdentity",
            "coverageBoundary",
            "invariants",
            "cuts",
        },
        "fault matrix",
    )
    if (
        value["schema"] != "hepta.intelligence-control-fault-matrix.v1"
        or type(value["schemaVersion"]) is not int
        or value["schemaVersion"] != 1
        or value["module"] != "intelligence.control"
    ):
        raise ValueError("wrong fault matrix identity")
    if value["executionStatus"] != "pending" or value["sourceIdentity"] != IDENTITY:
        raise ValueError("tracked fault matrix cannot claim execution")
    if (
        not isinstance(value["coverageBoundary"], str)
        or not value["coverageBoundary"].strip()
    ):
        raise ValueError("fault coverage boundary missing")
    if value["invariants"] != EXPECTED_INVARIANTS:
        raise ValueError("fault invariants changed")
    rows = value["cuts"]
    if not isinstance(rows, list) or len(rows) != len(EXPECTED_CUTS):
        raise ValueError("fault cuts omitted or added")
    ids: list[str] = []
    for row in rows:
        require_keys(
            row,
            {
                "id",
                "phase",
                "requiredDisposition",
                "executionStatus",
                "evidenceBoundary",
                "requiredInvariants",
                "evidenceBindings",
            },
            "fault cut",
        )
        if not isinstance(row["id"], str) or row["id"] not in EXPECTED_CUTS:
            raise ValueError("unknown fault cut")
        ids.append(row["id"])
        if (row["phase"], row["requiredDisposition"]) != EXPECTED_CUTS[row["id"]]:
            raise ValueError(f"unsafe phase/disposition for {row['id']}")
        if (
            row["executionStatus"] != "pending"
            or row["evidenceBoundary"] != BOUNDARY
            or row["requiredInvariants"] != EXPECTED_INVARIANTS
            or row["evidenceBindings"] != []
        ):
            raise ValueError(
                f"tracked cut is not a pending evidence obligation: {row['id']}"
            )
    if ids != list(EXPECTED_CUTS):
        raise ValueError("fault cuts duplicate or reordered")
    return value


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check-tracked", "--check", action="store_true")
    parser.parse_args()
    validate()
    print(
        f"Validated {len(EXPECTED_CUTS)} pending fault obligations; execution remains unproved."
    )


if __name__ == "__main__":
    main()
