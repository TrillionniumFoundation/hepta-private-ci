#!/usr/bin/env python3
"""Render and verify the canonical memory.federation capability state."""

from __future__ import annotations

import argparse
import json
import pathlib
import re
from typing import Any

ROOT = pathlib.Path(__file__).resolve().parents[1]
STATE_PATH = ROOT / "docs/modules/memory.federation/CAPABILITY_STATE.json"
IMPLEMENTATION_MAP_PATH = ROOT / "docs/modules/memory.federation/IMPLEMENTATION_MAP.json"
WIRE_MAP_PATH = ROOT / "docs/modules/memory.federation/WIRE_IMPLEMENTATION_MAP.json"
STATUS_SOURCE = "docs/modules/memory.federation/CAPABILITY_STATE.json"
BEGIN = "<!-- BEGIN GENERATED MEMORY FEDERATION STATUS -->"
END = "<!-- END GENERATED MEMORY FEDERATION STATUS -->"


class StatusError(RuntimeError):
    pass


def _load(path: pathlib.Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise StatusError(f"cannot read {path.relative_to(ROOT)}: {error}") from error
    if not isinstance(value, dict):
        raise StatusError(f"{path.relative_to(ROOT)} must contain a JSON object")
    return value


def _state() -> dict[str, Any]:
    state = _load(STATE_PATH)
    if state.get("schema") != "hepta.memory-federation.capability-state.v1":
        raise StatusError("capability-state schema mismatch")
    if state.get("schemaVersion") != 1 or state.get("module") != "memory.federation":
        raise StatusError("capability-state identity mismatch")
    capabilities = state.get("capabilities")
    if not isinstance(capabilities, dict):
        raise StatusError("capability-state capabilities must be an object")
    if capabilities.get("logicalCapacityProbe") != "source_candidate_retained_metrics_pending_execution":
        raise StatusError("logical capacity probe state drift")
    execution = state.get("execution")
    if not isinstance(execution, dict):
        raise StatusError("capability-state execution must be an object")
    if execution.get("successfulReceiptsRequireCapacityMetrics") is not True:
        raise StatusError("successful receipts must require retained capacity metrics")
    claims = state.get("claims")
    if not isinstance(claims, dict) or any(type(value) is not bool for value in claims.values()):
        raise StatusError("capability-state claims must be boolean")
    documents = state.get("generatedStatusDocuments")
    if not isinstance(documents, list) or not documents:
        raise StatusError("generated status documents must be nonempty")
    return state


def render_status(state: dict[str, Any]) -> str:
    capabilities = state["capabilities"]
    execution = state["execution"]
    claims = state["claims"]
    rows = [
        BEGIN,
        "## Generated capability status",
        "",
        "This block is generated from `CAPABILITY_STATE.json`. It separates source,",
        "execution, independent acceptance, activation, promotion, and release; prose",
        "outside this block cannot widen those claims.",
        "",
        "| Capability or gate | Canonical state |",
        "| --- | --- |",
        f"| In-process V2 engine | `{capabilities['inProcessV2Engine']}` |",
        f"| Agentd product caller | `{capabilities['agentdProductCaller']}` |",
        f"| Discovery/read budgeting | `{capabilities['boundedDiscovery']}` |",
        f"| Authenticated wire | `{capabilities['authenticatedWire']}` |",
        f"| Verified-frame boundary | `{capabilities['verifiedFrameType']}` |",
        f"| Replay admission | `{capabilities['replayAdmission']}` |",
        f"| Cross-host product transport | `{capabilities['crossHostProductTransport']}` |",
        f"| Durable attempt/replay recovery | `{capabilities['durableAttemptReplayRecovery']}` |",
        f"| Exact-head execution | `{execution['exactHead']}` |",
        f"| Deterministic merge execution | `{execution['deterministicCurrentBaseMerge']}` |",
        f"| Product execution proved | `{str(claims['productExecutionProved']).lower()}` |",
        f"| Independent acceptance | `{str(claims['independentAcceptance']).lower()}` |",
        f"| Activation | `{str(claims['activation']).lower()}` |",
        f"| Promotion | `{str(claims['promotion']).lower()}` |",
        f"| Release | `{str(claims['release']).lower()}` |",
        "",
        END,
    ]
    return "\n".join(rows)


def _verify_document(path: pathlib.Path, expected: str) -> None:
    text = path.read_text(encoding="utf-8")
    pattern = re.compile(re.escape(BEGIN) + r".*?" + re.escape(END), re.S)
    matches = pattern.findall(text)
    if matches != [expected]:
        raise StatusError(
            f"generated capability status differs in {path.relative_to(ROOT)}"
        )


def _verify_implementation_map(state: dict[str, Any]) -> None:
    row = _load(IMPLEMENTATION_MAP_PATH)
    claims = state["claims"]
    if row.get("statusSource") != STATUS_SOURCE:
        raise StatusError("implementation map does not name the canonical status source")
    if row.get("productCallerState") != capabilities_product_caller_state(state):
        raise StatusError("implementation-map product caller state drift")
    if row.get("productionImplementation") is not claims["productionImplementation"]:
        raise StatusError("implementation-map production implementation drift")
    boundary = row.get("claimBoundary")
    if not isinstance(boundary, dict):
        raise StatusError("implementation-map claim boundary missing")
    mapping = {
        "sourceRootPresent": "sourceRootPresent",
        "nativeSourceMappingComplete": "nativeSourceMappingComplete",
        "productionImplementation": "productionImplementation",
        "productExecutionProved": "productExecutionProved",
        "independentAcceptance": "independentAcceptance",
        "activation": "activation",
        "release": "release",
    }
    for map_field, state_field in mapping.items():
        if boundary.get(map_field) is not claims[state_field]:
            raise StatusError(f"implementation-map claim drift: {map_field}")


def capabilities_product_caller_state(state: dict[str, Any]) -> str:
    capability = state["capabilities"]["agentdProductCaller"]
    if capability != "composed_candidate_pending_execution":
        raise StatusError("unsupported canonical Agentd product-caller state")
    return capability


def _verify_wire_map(state: dict[str, Any]) -> None:
    row = _load(WIRE_MAP_PATH)
    claims = state["claims"]
    if row.get("statusSource") != STATUS_SOURCE:
        raise StatusError("wire map does not name the canonical status source")
    boundary = row.get("claimBoundary")
    if not isinstance(boundary, dict):
        raise StatusError("wire-map claim boundary missing")
    mapping = {
        "sourceCandidate": "wireSourceCandidate",
        "productComposed": "wireProductComposed",
        "productExecutionProved": "productExecutionProved",
        "mutuallyAuthenticatedTransportSelected": "mutuallyAuthenticatedTransportSelected",
        "twoRealHostQualification": "twoRealHostQualification",
        "independentAcceptance": "independentAcceptance",
        "activation": "activation",
        "promotion": "promotion",
        "release": "release",
    }
    for map_field, state_field in mapping.items():
        if boundary.get(map_field) is not claims[state_field]:
            raise StatusError(f"wire-map claim drift: {map_field}")
    if row.get("externalGates") != state.get("externalGates"):
        raise StatusError("wire-map external gates drift")
    qualification = row.get("qualification")
    if not isinstance(qualification, dict):
        raise StatusError("wire-map qualification is missing")
    if qualification.get("capacityMetricsRequiredForSuccess") is not True:
        raise StatusError("wire-map capacity metrics are not required for success")
    operations = row.get("operations")
    if not isinstance(operations, list) or not any(
        operation.get("name") == "measure_logical_host_capacity_and_recovery"
        and operation.get("source")
        == "codex-rs/hepta-memory-federation-wire/src/bin/memory_federation_capacity_probe.rs"
        for operation in operations
        if isinstance(operation, dict)
    ):
        raise StatusError("wire-map capacity probe operation is missing")


def verify() -> int:
    state = _state()
    expected = render_status(state)
    for relative in state["generatedStatusDocuments"]:
        path = ROOT / relative
        if not path.is_file():
            raise StatusError(f"missing generated status document: {relative}")
        _verify_document(path, expected)
    _verify_implementation_map(state)
    _verify_wire_map(state)

    # The thin shell invokes a recorder. Validate the actual command contract,
    # not inert shell comments or a second, potentially divergent command list.
    import memory_federation_full_attestation as full

    qualification = (ROOT / state["qualificationScript"]).read_text(encoding="utf-8")
    if "exec python3 scripts/memory_federation_execution_receipt.py run" not in qualification:
        raise StatusError("qualification does not invoke the execution recorder")
    commands = list(full.base.COMMANDS)
    required = (
        "python3 scripts/verify_memory_federation_status.py verify",
        "python3 scripts/memory_federation_execution_guard.py capture "
        "--state <guard-state> --expected-sha <tested-sha> --expected-tree <tested-tree>",
        "python3 scripts/memory_federation_execution_guard.py verify "
        "--state <guard-state> --expected-sha <tested-sha> --expected-tree <tested-tree>",
        "cargo test --locked -p codex-hepta-memory --lib product_nonce_tests",
        "cargo run --locked --manifest-path codex-rs/hepta-memory-federation-wire/Cargo.toml "
        "--bin memory_federation_capacity_probe -- <capacity-metrics.json>",
    )
    if len(commands) != len(set(commands)) or any(commands.count(command) != 1 for command in required):
        raise StatusError("qualification command contract is missing or duplicates a required gate")
    for key in ("successfulReceiptsRequireCommandExecution", "successfulReceiptsRequireTrackedLock"):
        if state["execution"].get(key) is not True:
            raise StatusError(f"execution evidence requirement drift: {key}")
    attestation = (ROOT / state["attestationScript"]).read_text(encoding="utf-8")
    for marker in (
        "capability-state.json",
        "capabilityStateSha256",
        "capacity-metrics.json",
        "capacityMetricsSha256",
        "successful qualification is missing capacity metrics",
    ):
        if marker not in attestation:
            raise StatusError(f"qualification attestation is missing {marker}")
    print(json.dumps({"status": "PASS_MEMORY_FEDERATION_STATUS", "module": state["module"]}))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["render", "verify"])
    args = parser.parse_args()
    if args.command == "render":
        print(render_status(_state()))
        return 0
    return verify()


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except StatusError as error:
        raise SystemExit(f"FAIL_MEMORY_FEDERATION_STATUS: {error}") from error
