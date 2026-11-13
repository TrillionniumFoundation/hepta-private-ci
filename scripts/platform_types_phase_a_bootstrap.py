#!/usr/bin/env python3
"""Prepare and run the platform.types phase-A convergence patch."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def write(path: str, value: str) -> None:
    (ROOT / path).write_text(value, encoding="utf-8")


def load_json(path: str) -> dict:
    return json.loads(read(path))


def save_json(path: str, value: dict) -> None:
    write(path, json.dumps(value, indent=2, ensure_ascii=False) + "\n")


def replace_once(path: str, old: str, new: str) -> None:
    text = read(path)
    if new in text:
        return
    if old not in text:
        raise RuntimeError(f"missing bootstrap anchor in {path}: {old[:120]!r}")
    write(path, text.replace(old, new, 1))


# The protocol registry may have more than one protocol for a module. Preserve
# every row and its original same-module order while presenting modules in the
# canonical Lane-A order.
replace_once(
    "scripts/platform_types_phase_a.py",
    '''for json_path, key in (
    ("docs/lane-a-foundation/MODULE_TRUTH_MATRIX.json", "modules"),
    ("docs/lane-a-foundation/PROTOCOL_REGISTRY_V1.json", "protocols"),
):
    value = load_json(json_path)
    rows = value[key]
    by_name = {row["module"]: row for row in rows}
    if set(by_name) != set(expected_modules) or len(rows) != len(expected_modules):
        raise RuntimeError(f"{json_path}: unexpected Lane-A module set")
    value[key] = [by_name[name] for name in expected_modules]
    save_json(json_path, value)
''',
    '''matrix_path = "docs/lane-a-foundation/MODULE_TRUTH_MATRIX.json"
matrix_value = load_json(matrix_path)
matrix_rows = matrix_value["modules"]
matrix_by_name = {row["module"]: row for row in matrix_rows}
if set(matrix_by_name) != set(expected_modules) or len(matrix_rows) != len(expected_modules):
    raise RuntimeError(f"{matrix_path}: unexpected Lane-A module set")
matrix_value["modules"] = [matrix_by_name[name] for name in expected_modules]
save_json(matrix_path, matrix_value)

protocol_path = "docs/lane-a-foundation/PROTOCOL_REGISTRY_V1.json"
protocol_value = load_json(protocol_path)
protocol_rows = protocol_value["protocols"]
module_rank = {module: index for index, module in enumerate(expected_modules)}
if {row["module"] for row in protocol_rows} != set(expected_modules):
    raise RuntimeError(f"{protocol_path}: unexpected Lane-A protocol module set")
protocol_value["protocols"] = [
    row
    for _, row in sorted(
        enumerate(protocol_rows),
        key=lambda item: (module_rank[item[1]["module"]], item[0]),
    )
]
save_json(protocol_path, protocol_value)
''',
)

subprocess.run(
    ["python3", "scripts/platform_types_phase_a.py"],
    cwd=ROOT,
    check=True,
)

# Refresh current-source anchors that drifted while retaining the same claimed
# operation and rejection semantics.
matrix_path = "docs/lane-a-foundation/MODULE_TRUTH_MATRIX.json"
matrix = load_json(matrix_path)
authority = next(row for row in matrix["modules"] if row["module"] == "kernel.authority")
for anchor in authority["sourceAnchors"]:
    if anchor["path"] == "codex-rs/hepta-fleet/src/authority_port.rs":
        anchor["mustContain"] = [
            "dispatch_authority_lease_with_witness"
            if value == ".with_verified_use("
            else value
            for value in anchor["mustContain"]
        ]
save_json(matrix_path, matrix)

capability_path = "docs/lane-a-foundation/CAPABILITY_EVIDENCE_MAP.json"
capability = load_json(capability_path)
for row in capability["entries"]:
    for field in ("sourceEvidence", "positiveTests", "negativeTests", "callerEvidence"):
        for anchor in row.get(field, []):
            if anchor["path"] == "codex-rs/hepta-fleet/src/authority_port.rs":
                anchor["mustContain"] = [
                    "dispatch_authority_lease_with_witness"
                    if value == ".with_verified_use("
                    else value
                    for value in anchor.get("mustContain", [])
                ]
            if anchor["path"] == "codex-rs/hepta-types/conformance/verify_rejections.py":
                anchor["mustContain"] = [
                    "raw-byte rejection oracle accepted invalid bytes"
                    if value == "rejection oracle accepted invalid case"
                    else value
                    for value in anchor.get("mustContain", [])
                ]
save_json(capability_path, capability)

# Closed-world means the module set is closed, not that each module owns exactly
# one protocol row.
replace_once(
    "qualification/module-execution-dossiers/test_lane_a_foundation.py",
    '''        self.assertEqual(
            [row["module"] for row in registry["protocols"]],
            verify.EXPECTED_MODULES,
        )
        self.assertEqual(len(registry["protocols"]), 7)
        for row in registry["protocols"]:
''',
    '''        observed_modules = []
        for row in registry["protocols"]:
            if row["module"] not in observed_modules:
                observed_modules.append(row["module"])
        self.assertEqual(observed_modules, verify.EXPECTED_MODULES)
        self.assertGreaterEqual(len(registry["protocols"]), len(verify.EXPECTED_MODULES))
        for row in registry["protocols"]:
''',
)

print("platform.types phase-A bootstrap applied")
