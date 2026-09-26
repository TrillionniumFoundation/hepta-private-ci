#!/usr/bin/env python3
"""Validate the fail-closed learning.artifacts status projection."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STATUS = ROOT / "docs/modules/learning.artifacts/QUALIFICATION_STATUS.json"
MAP = ROOT / "docs/modules/learning.artifacts/IMPLEMENTATION_MAP.json"


def main() -> int:
    status = json.loads(STATUS.read_text(encoding="utf-8"))
    mapping = json.loads(MAP.read_text(encoding="utf-8"))
    errors: list[str] = []
    if status.get("schema") != "hepta.learning-artifacts.qualification-status.v1":
        errors.append("unexpected status schema")
    if status.get("aggregateStatusProhibited") is not True:
        errors.append("aggregate status must be prohibited")
    dimensions = status.get("dimensions")
    if not isinstance(dimensions, dict):
        errors.append("dimensions must be an object")
        dimensions = {}
    for key in (
        "sourceImplementation",
        "productReadPath",
        "writerService",
        "productionTransport",
        "actionAuthorization",
        "exactHeadQualification",
        "orderedParentMergeQualification",
        "targetHostDirectoryDurability",
        "powerLossQualification",
        "activation",
        "independentAcceptance",
        "promotion",
        "release",
    ):
        if not isinstance(dimensions.get(key), str) or not dimensions[key]:
            errors.append(f"missing status dimension: {key}")
    if mapping.get("module") != "learning.artifacts":
        errors.append("implementation map module mismatch")
    if mapping.get("productionImplementation") is not False:
        errors.append(
            "productionImplementation may advance only with external activation evidence"
        )
    forbidden = set(status.get("forbiddenAggregateLabels", []))
    for key in ("status", "state", "completion", "aggregateStatus"):
        value = mapping.get(key)
        if isinstance(value, str) and value.upper() in forbidden:
            errors.append(f"forbidden aggregate completion label at {key}")
    if dimensions.get("activation") != "inactive":
        errors.append("repository status must not self-assert activation")
    if dimensions.get("release") != "not_granted":
        errors.append("repository status must not self-grant release")
    if errors:
        for error in errors:
            print(error, file=sys.stderr)
        return 1
    print(json.dumps({"ok": True, "module": "learning.artifacts"}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
