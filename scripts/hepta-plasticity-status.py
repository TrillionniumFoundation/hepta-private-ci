#!/usr/bin/env python3
"""Generate and verify learning.plasticity current-vs-target status.

CURRENT_STATE.json is the single machine-readable source for the current source
capability table. TECHNICAL.md remains the target/stable design authority.
CURRENT_IMPLEMENTATION.md embeds a generated projection of CURRENT_STATE.json.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STATE_PATH = ROOT / "docs/modules/learning.plasticity/CURRENT_STATE.json"
DOC_PATH = ROOT / "docs/modules/learning.plasticity/CURRENT_IMPLEMENTATION.md"
MAP_PATH = ROOT / "docs/modules/learning.plasticity/IMPLEMENTATION_MAP.json"
BEGIN = "<!-- BEGIN GENERATED CURRENT STATE -->"
END = "<!-- END GENERATED CURRENT STATE -->"


def load_state() -> dict:
    return json.loads(STATE_PATH.read_text(encoding="utf-8"))


def load_implementation_map() -> dict:
    return json.loads(MAP_PATH.read_text(encoding="utf-8"))


def generated_block(state: dict) -> str:
    rows = [
        BEGIN,
        "| Capability | Current source state | Surface | Source |",
        "| --- | --- | --- | --- |",
    ]
    for capability in state["capabilities"]:
        rows.append(
            "| `{id}` | `{status}` | `{surface}` | `{source}` |".format(**capability)
        )
    rows.extend(["", "**Claim boundary:**"])
    for key, value in state["claims"].items():
        rows.append(f"- `{key}={str(value).lower()}`")
    rows.extend(["", "**Remaining gates:**"])
    for gate in state["remainingGates"]:
        rows.append(f"- {gate}")
    rows.append(END)
    return "\n".join(rows)


def validate_state(state: dict) -> list[str]:
    failures: list[str] = []
    if state.get("schema") != "hepta.learning-plasticity-current-state.v1":
        failures.append("schema")
    if state.get("schemaVersion") != 1:
        failures.append("schemaVersion")
    if state.get("module") != "learning.plasticity":
        failures.append("module")
    if (
        state.get("architectureBoundary")
        != "deterministic_core__authenticated_product_adapter__agentd_host"
    ):
        failures.append("architectureBoundary")
    stable = state.get("stableRecord") or {}
    if stable.get("id") != "ParameterProposalV2" or not stable.get(
        "wireAndDigestStable"
    ):
        failures.append("stable ParameterProposalV2 boundary")
    stable_source = stable.get("source")
    if not stable_source or not (ROOT / stable_source).is_file():
        failures.append("stable record source")

    capabilities = state.get("capabilities")
    if not isinstance(capabilities, list) or not capabilities:
        failures.append("capabilities")
    else:
        ids: set[str] = set()
        for capability in capabilities:
            cid = capability.get("id")
            if not cid or cid in ids:
                failures.append(f"duplicate/empty capability {cid!r}")
                continue
            ids.add(cid)
            for key in ("status", "surface", "source", "tests"):
                if key not in capability:
                    failures.append(f"{cid}: missing {key}")
            source = capability.get("source")
            if not source or not (ROOT / source).is_file():
                failures.append(f"{cid}: missing source {source}")
            tests = capability.get("tests")
            if not isinstance(tests, list) or not tests:
                failures.append(f"{cid}: tests")
            else:
                for test_path in tests:
                    if not (ROOT / test_path).is_file():
                        failures.append(f"{cid}: missing test {test_path}")

    claims = state.get("claims") or {}
    deny_claims = (
        "productionImplementation",
        "targetHostExecutionProved",
        "independentAcceptance",
        "topologyApplicationImplemented",
        "weightInstallationImplemented",
        "activation",
        "promotion",
        "release",
    )
    for claim in deny_claims:
        if claims.get(claim) is not False:
            failures.append(f"claim must remain false: {claim}")
    gates = state.get("remainingGates")
    if not isinstance(gates, list) or not gates:
        failures.append("remainingGates")
    return failures


def validate_map_coherence(state: dict, implementation_map: dict) -> list[str]:
    failures: list[str] = []
    if implementation_map.get("module") != "learning.plasticity":
        failures.append("implementation map module")
    if implementation_map.get("currentState") != str(STATE_PATH.relative_to(ROOT)):
        failures.append("implementation map currentState")
    if implementation_map.get("currentImplementation") != str(DOC_PATH.relative_to(ROOT)):
        failures.append("implementation map currentImplementation")

    operations = implementation_map.get("operations")
    if not isinstance(operations, list) or not operations:
        failures.append("implementation map operations")
        operations = []

    for operation in operations:
        operation_id = operation.get("operation") or "<unknown>"
        source = operation.get("sourcePath")
        if not source or not (ROOT / source).is_file():
            failures.append(f"map {operation_id}: missing source {source}")
        tests = operation.get("tests")
        if not isinstance(tests, list) or not tests:
            failures.append(f"map {operation_id}: tests")
            continue
        for test_path in tests:
            if not (ROOT / test_path).is_file():
                failures.append(f"map {operation_id}: missing test {test_path}")

    for capability in state.get("capabilities") or []:
        cid = capability["id"]
        source = capability["source"]
        capability_tests = set(capability["tests"])
        matching = [operation for operation in operations if operation.get("sourcePath") == source]
        if not matching:
            failures.append(f"{cid}: no implementation-map operation for {source}")
            continue
        if not any(
            capability_tests.intersection(operation.get("tests") or []) for operation in matching
        ):
            failures.append(f"{cid}: tests do not intersect implementation map")

    producers = implementation_map.get("receiptProducers")
    if not isinstance(producers, list) or not producers:
        failures.append("implementation map receiptProducers")
    else:
        for producer in producers:
            if not (ROOT / producer).is_file():
                failures.append(f"missing receipt producer {producer}")
    if implementation_map.get("receiptState") != "dynamic_exact_candidate_only_not_cached_in_map":
        failures.append("implementation map receiptState")

    claims = implementation_map.get("claimBoundary") or {}
    for key, value in state.get("claims", {}).items():
        if key in claims and claims[key] != value:
            failures.append(f"claim mismatch: {key}")
    if implementation_map.get("productionImplementation") is not False:
        failures.append("implementation map productionImplementation must remain false")
    return failures


def project(source: str, block: str) -> str:
    if source.count(BEGIN) != 1 or source.count(END) != 1:
        raise ValueError("CURRENT_IMPLEMENTATION.md must contain exactly one generated block")
    before, rest = source.split(BEGIN, 1)
    _, after = rest.split(END, 1)
    return before + block + after


def generate() -> None:
    state = load_state()
    failures = validate_state(state)
    failures.extend(validate_map_coherence(state, load_implementation_map()))
    if failures:
        raise SystemExit("FAIL_PLASTICITY_CURRENT_STATE: " + "; ".join(failures))
    source = DOC_PATH.read_text(encoding="utf-8")
    expected = project(source, generated_block(state))
    DOC_PATH.write_text(expected, encoding="utf-8")
    print(json.dumps({"status": "GENERATED_PLASTICITY_CURRENT_STATE"}, sort_keys=True))


def verify() -> None:
    state = load_state()
    failures = validate_state(state)
    failures.extend(validate_map_coherence(state, load_implementation_map()))
    if failures:
        raise SystemExit("FAIL_PLASTICITY_CURRENT_STATE: " + "; ".join(failures))
    source = DOC_PATH.read_text(encoding="utf-8")
    expected = project(source, generated_block(state))
    if source != expected:
        raise SystemExit(
            "FAIL_PLASTICITY_CURRENT_STATE: CURRENT_IMPLEMENTATION.md projection is stale; "
            "run python3 scripts/hepta-plasticity-status.py generate"
        )
    print(
        json.dumps(
            {
                "status": "PASS_PLASTICITY_CURRENT_STATE",
                "capabilities": len(state["capabilities"]),
                "productionImplementation": False,
                "activation": False,
                "release": False,
            },
            sort_keys=True,
        )
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["generate", "verify"])
    args = parser.parse_args()
    {"generate": generate, "verify": verify}[args.command]()


if __name__ == "__main__":
    main()
