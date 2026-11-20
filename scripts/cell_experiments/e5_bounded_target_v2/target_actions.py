"""Supervision after an independent input freeze; never selects input units."""

import json

from compact_wire import apply_compact, validate_view
from v2_common import canonical, require
from v2_legacy import source_actions


def target_for_view(visible, view, expected_view_digest, after):
    binding, selected = validate_view(visible, view, expected_view_digest)
    before = visible["runtime"]
    reference, actual_binding, units = source_actions.reference_action(
        visible["identity"]["source_id"], before, after
    )
    require(actual_binding == binding, "reference runtime binding changed")
    require(
        source_actions.apply(before, binding, reference, {u["unit_id"] for u in units})
        == after,
        "full reference does not reconstruct original after runtime",
    )
    original_edits = json.loads(reference)["edits"]
    positions = {unit["unit_id"]: i for i, unit in enumerate(selected)}
    missing = sorted({e["unit_id"] for e in original_edits} - set(positions))
    evidence = {
        "reference": reference,
        "structural_roundtrip": True,
        "edit_count": len(original_edits),
        "missing_visible_unit_ids": missing,
        "visible_action_roundtrip": False,
        "target": None,
    }
    if missing:
        evidence["rejection"] = "complete original edit owner absent from frozen view"
        return evidence
    edits = [
        [
            positions[e["unit_id"]],
            0 if e["kind"] == "replace_lines" else 1,
            e["start_line"],
            e["end_line"],
            e["replacement"],
        ]
        for e in original_edits
    ]
    payload = canonical([2, expected_view_digest, edits])
    require(
        apply_compact(visible, view, expected_view_digest, payload) == after,
        "compact action does not reconstruct complete original after runtime",
    )
    evidence.update(visible_action_roundtrip=True, target=payload)
    return evidence
