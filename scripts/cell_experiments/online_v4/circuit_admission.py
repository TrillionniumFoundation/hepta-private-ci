"""Separate router fitting groups and bind the actual message implementation."""

import hashlib
from pathlib import Path

from .. import data
from .circuit_contract import digest, is_sha, require

GROUPS = ("task_id", "lineage_id", "family_id", "source_id", "project_id")


def group_bindings(records):
    """Hash declared groups and exact source/prompt bytes; not provenance proof."""
    groups = {key: set() for key in (*GROUPS, "source_bytes", "input")}
    for row in records:
        data.validate_record(row, require_outcome=False)
        for key in GROUPS:
            value = row.get(key)
            require(
                isinstance(value, str) and 0 < len(value.encode()) <= 512,
                "missing bounded router group: " + key,
            )
            groups[key].add(digest(value))
        source = row.get("source", {}).get("sha256")
        require(is_sha(source), "missing router source bytes identity")
        groups["source_bytes"].add(source)
        groups["input"].add(digest(row["task"]["input"]))
    return {key: sorted(values) for key, values in groups.items()}


def message_binding(cells, style):
    """Include serialization code and admitted provider runtime/template bundle."""
    require(style in ("bundled_v4", "native_turn_v1"), "unknown message style")
    root = Path(__file__).resolve().parent
    paths = (
        "circuit_runtime.py",
        "circuit_contract.py",
        "onpolicy_feedback.py",
        "../chat_protocol.py",
    )
    return digest(
        {
            "message_style": style,
            "source_sha256": {
                name: hashlib.sha256((root / name).read_bytes()).hexdigest()
                for name in paths
            },
            "provider_protocols": {
                name: {"runtime": cell.protocol_digest, "bundle": cell.bundle_digest}
                for name, cell in sorted(cells.items())
            },
        }
    )


def evaluation_admission(router, records, scope):
    """Fail before dispatch; exposed diagnostics explicitly retain overlap."""
    require(scope in ("heldout", "exposed_diagnostic"), "unknown evaluation scope")
    require(
        all(
            row.get("split") in ("selection", "confirmation")
            and row.get("authorization", {}).get("evaluation_allowed") is True
            for row in records
        ),
        "evaluation-only panel with explicit permission required",
    )
    fitted = router.record.get("training_group_bindings")
    current = group_bindings(records)
    require(
        isinstance(fitted, dict) and set(fitted) == set(current),
        "router lacks frozen training group bindings",
    )
    require(
        all(
            isinstance(values, list)
            and values
            and all(is_sha(value) for value in values)
            and values == sorted(set(values))
            for values in fitted.values()
        ),
        "invalid frozen training groups",
    )
    overlap = {
        key: sorted(set(fitted[key]) & set(values)) for key, values in current.items()
    }
    exposed = any(row.get("exposure") == "previously_exposed" for row in records)
    if scope == "heldout":
        require(not any(overlap.values()), "router fit/evaluation source-group overlap")
        require(not exposed, "exposed panel requires explicit diagnostic scope")
        require(
            all(
                row["authorization"].get("training_allowed") is False for row in records
            ),
            "heldout panel must prohibit fitting",
        )
    return {
        "scope": scope,
        "group_bindings": current,
        "overlap": overlap,
        "selection_on_this_panel": any(overlap.values()),
        "diagnostic_only": scope == "exposed_diagnostic",
        "previously_exposed": exposed,
        "provenance_authenticated": False,
        "semantic_duplicate_detection_complete": False,
        "independent_confirmation": False,
    }
