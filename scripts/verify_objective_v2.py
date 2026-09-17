#!/usr/bin/env python3
"""Fail closed on objective source/publication contract drift."""

from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def fail(message: str) -> None:
    raise SystemExit("FAIL_OBJECTIVE_V2_CONTRACT: " + message)


def load(path: str):
    return json.loads((ROOT / path).read_text(encoding="utf-8"))


def constant(source: str, name: str) -> int:
    match = re.search(rf"pub const {re.escape(name)}: usize = ([0-9_]+);", source)
    if not match:
        fail(f"missing Rust constant {name}")
    return int(match.group(1).replace("_", ""))


def main() -> int:
    contract = load("docs/contracts/OBJECTIVE_V2.json")
    objectives = load("docs/control-plane/OBJECTIVES.json")
    legacy_registry = load("docs/contracts/PROTOCOL_SCHEMAS.json")
    validation = (ROOT / "codex-rs/hepta-objective/src/source_envelope_validation.rs").read_text(encoding="utf-8")
    lib = (ROOT / "codex-rs/hepta-objective/src/lib.rs").read_text(encoding="utf-8")
    wire = (ROOT / "codex-rs/hepta-objective/src/objective_function_v2.rs").read_text(encoding="utf-8")

    if contract.get("schema") != "hepta.objective-wire-contract.v2":
        fail("objective V2 contract schema")
    if objectives.get("objectiveFunctionContract", {}).get("schema") != "ObjectiveFunctionV2":
        fail("OBJECTIVES.json must select ObjectiveFunctionV2")
    if objectives["objectiveFunctionContract"].get("canonicalRegistry") != "docs/contracts/OBJECTIVE_V2.json":
        fail("OBJECTIVES.json canonical registry binding")

    bounds = contract["sourceProtocol"]["bounds"]
    expected = {
        "sourceHardConstraintsMax": constant(validation, "MAX_OBJECTIVE_SOURCE_CONSTRAINTS"),
        "aggregateSuccessTerminalEvidenceMax": constant(validation, "MAX_OBJECTIVE_AGGREGATE_PREDICATES"),
        "callerLegalActionClassesMax": constant(validation, "MAX_OBJECTIVE_CALLER_ACTIONS"),
    }
    for key, actual in expected.items():
        if bounds.get(key) != actual:
            fail(f"{key}: contract={bounds.get(key)!r} Rust={actual}")
    if bounds.get("generatedHardConstraintReserve") != 10:
        fail("generated hard-constraint reserve must remain 10")
    if bounds.get("callerLegalActionClassesMin") != 0 or bounds.get("intrinsicAbstainSlots") != 1:
        fail("V2 action bound must reserve one intrinsic abstain slot")
    if bounds.get("nativeLegalActionCapacity") != bounds["callerLegalActionClassesMax"] + 1:
        fail("caller action capacity does not compose with intrinsic abstain")

    required_exports = [
        "ObjectiveFunctionV2",
        "ObjectiveSourceEnvelopeV2",
        "decode_source_envelope_json_v2",
        "admit_and_compile_objective_v2",
        "project_objective_function_v2",
    ]
    for symbol in required_exports:
        if symbol not in lib:
            fail(f"missing public V2 symbol {symbol}")

    immutable = set(contract["compiledProtocol"]["immutableCoreFields"])
    rust_field_markers = {
        "principalScope": "pub principal_scope:",
        "successPredicates": "pub success_predicates:",
        "terminalConditions": "pub terminal_conditions:",
        "hardConstraints": "pub hard_constraints:",
        "evidenceRequirements": "pub evidence_requirements:",
        "allowedActionClasses": "pub allowed_action_classes:",
        "forbiddenActionClasses": "pub forbidden_action_classes:",
        "resourceEndowment": "pub resource_endowment:",
        "risk": "pub risk:",
    }
    if immutable != set(rust_field_markers):
        fail("contract immutable-core set drift")
    for field, marker in rust_field_markers.items():
        if marker not in wire:
            fail(f"V2 Rust wire omits immutable field {field}")

    legacy = next((row for row in legacy_registry["protocols"] if row.get("id") == "ObjectiveFunctionV1"), None)
    if legacy is None:
        fail("historical ObjectiveFunctionV1 registry row disappeared")
    legacy_fields = {row["name"] for row in legacy.get("fields", [])}
    absent = {"evidenceRequirements", "allowedActionClasses", "forbiddenActionClasses"} - legacy_fields
    if not absent:
        fail("V1 field set changed; review versioning instead of silently retaining legacy status")
    legacy_status = contract.get("legacyV1", {}).get("ObjectiveFunctionV1", "")
    if "read_only_compatibility" not in legacy_status or "incomplete" not in legacy_status:
        fail("legacy V1 status must remain explicit and fail closed")

    print(json.dumps({
        "status": "PASS_OBJECTIVE_V2_CONTRACT",
        "sourceProtocol": contract["sourceProtocol"]["id"],
        "compiledProtocol": contract["compiledProtocol"]["id"],
        "legacyMissingImmutableFields": sorted(absent),
        "bounds": expected,
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
