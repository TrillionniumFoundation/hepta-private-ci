#!/usr/bin/env python3
"""Generate and verify control.runtime state projections from MATURITY.json."""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
MODULE_ROOT = ROOT / "docs" / "modules" / "control.runtime"
MANIFEST_PATH = MODULE_ROOT / "MATURITY.json"
MAP_PATH = MODULE_ROOT / "IMPLEMENTATION_MAP.json"
CURRENT_PATH = MODULE_ROOT / "CURRENT_IMPLEMENTATION.md"
SUBSYSTEMS = (
    ("Planner kernel", "plannerKernel"),
    ("Public planner guard", "plannerPublicBoundary"),
    ("Planner store", "plannerStore"),
    ("Planner execution coordinator", "plannerExecutionCoordinator"),
    ("Agentd read-only context caller", "readOnlyAgentdContextCaller"),
    ("Global planner caller", "globalPlannerCaller"),
    ("Organ host", "organHost"),
    ("Embodiment reference", "embodimentReference"),
    ("Authority consumer", "authorityConsumer"),
    ("Effect executor", "effectExecutor"),
    ("Terminal reconciliation", "terminalReconciliation"),
)
GOVERNANCE = {
    "independentSemanticReview", "operatorAcceptance", "activation",
    "canaryPromotion", "release",
}


def load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain one JSON object")
    return value


def validate_manifest(manifest: dict[str, Any]) -> None:
    if manifest.get("schema") != "hepta.control-runtime-maturity.v1":
        raise ValueError("unexpected control.runtime maturity schema")
    if type(manifest.get("schemaVersion")) is not int or manifest["schemaVersion"] != 1:
        raise ValueError("unexpected control.runtime maturity schemaVersion")
    if manifest.get("module") != "control.runtime" or manifest.get("authorityDelta") != "none":
        raise ValueError("wrong module or widened authority")
    source = manifest.get("sourceObservation")
    if not isinstance(source, dict) or source.get("selfAuthenticatingTrackedShaClaim") is not False:
        raise ValueError("tracked maturity cannot self-authenticate its containing commit")
    if not re.fullmatch(r"[0-9a-f]{40}", str(source.get("historicalBaseCommit", ""))):
        raise ValueError("historical base must be an exact commit identity")
    external = manifest.get("externalGovernance")
    if not isinstance(external, dict) or set(external) != GOVERNANCE:
        raise ValueError("external governance inventory is not closed")
    if any(value is not False for value in external.values()):
        raise ValueError("external governance requires explicit false, not truthy or falsey substitutes")
    subsystems = manifest.get("subsystems")
    if not isinstance(subsystems, dict) or set(subsystems) != {key for _, key in SUBSYSTEMS}:
        raise ValueError("control.runtime subsystem maturity inventory is not closed")
    for value in subsystems.values():
        if not isinstance(value, dict) or type(value.get("productionComposed")) is not bool:
            raise ValueError("each subsystem requires an explicit composition boolean")
        if not isinstance(value.get("state"), str) or not value["state"]:
            raise ValueError("each subsystem requires a named maturity state")


def render_current(manifest: dict[str, Any]) -> str:
    lines = [
        "# control.runtime current implementation", "",
        "> Generated from `MATURITY.json`. Do not hand-edit state claims in this file.", "",
        "## Current claim boundary", "",
        "The branch contains a deterministic deny-all planner, bounded public guards, an owner-local durable store candidate, an execution coordinator over owner-supplied ports, and a bounded read-only Agentd context caller. Source composition, exact-source execution, target-host qualification, independent acceptance and activation are separate facts. No named global-planner production caller, independently admitted production writer, production effect executor or production reconciler is established by this document.", "",
        "| Subsystem | Current state | Product composition |", "|---|---|---:|",
    ]
    for label, key in SUBSYSTEMS:
        value = manifest["subsystems"][key]
        composed = "yes" if value["productionComposed"] else "no"
        if key == "readOnlyAgentdContextCaller" and value["productionComposed"]:
            composed = "yes, bounded read-only source path; not activation"
        lines.append(f"| {label} | `{value['state']}` | {composed} |")
    lines.extend([
        "", "## Durable store controls and limits", "",
        "`PlannerStoreV1` preserves bounded bodies and their content checksums in a versioned image, with an exclusive writer lock, atomic whole-image replacement, file/directory sync, poisoned indeterminate handles and reopen validation. Whole-image replacement is not append-log last-complete-frame recovery. Stored body coverage is not semantic decoding. An `external_anchor_digest` is an evidence reference, not an independently verified non-regressing anchor. Production composition still requires the semantic owner codec, independent durable anchor and target-host crash/restore qualification.",
        "", "## Request-integrity controls", "",
        "The candidate Agentd path retains request/query/retrieval/ranker binding, a final-use delivery seal and a monotonic process-generation lease. Public planner checks reject extra owners, duplicate payloads, oversized raw collections and effect-bearing abstention. Owner age and clock monotonicity are rechecked at preparation, finalization and grant-request construction. Journal raw append and reopen use the same decision/selection/revocation state machine; valid hashes do not excuse illegal history. These are source-level statements until exact-candidate tests pass.",
        "", "## Execution closure and signature boundary", "",
        "`PlannerExecutionCoordinatorV1` records intent before owner-port calls, binds requests/grants/payloads, prevents redispatch of recorded requests and discovers reconciliation work after restart. A `signature_digest` in an owner-port projection is not a cryptographic signature verification. Actual authority, executor and reconciler adapters must independently authenticate complete signed bodies, pin identities and recheck current revocation. Those named production integrations and terminal-result channels remain open; planner output remains deny-all.",
        "", "## Qualification and governance", "",
        "Use `.github/workflows/hepta-control-runtime-exact.yml` for isolated NDU, control-plane and Agentd source-head/synthetic-merge checks. Evidence must bind source, integration base, executed tree, run ID and run attempt, with every command exit code and output digest. Missing, skipped, queued or failed commands are not passes; a historical same-SHA artifact without matching run-attempt provenance is insufficient. The workflow does not itself install a branch-protection requirement. Independent semantic review, operator acceptance, activation, real canary promotion and release remain false pending independent evidence.", "",
    ])
    return "\n".join(lines)


def projected_map(manifest: dict[str, Any], implementation: dict[str, Any]) -> dict[str, Any]:
    value = json.loads(json.dumps(implementation))
    value["maturityManifest"] = "docs/modules/control.runtime/MATURITY.json"
    value["currentImplementation"] = "docs/modules/control.runtime/CURRENT_IMPLEMENTATION.md"
    for key in ("productCallerState", "productionWriterState", "completion"):
        value[key] = manifest[key]
    value["subsystemMaturity"] = manifest["subsystems"]
    return value


def serialized_json(value: dict[str, Any]) -> str:
    return json.dumps(value, indent=2, sort_keys=False) + "\n"


def run(mode: str) -> None:
    manifest = load_json(MANIFEST_PATH)
    validate_manifest(manifest)
    current = render_current(manifest)
    current_map = load_json(MAP_PATH)
    implementation = projected_map(manifest, current_map)
    if mode == "sync":
        CURRENT_PATH.write_text(current, encoding="utf-8")
        MAP_PATH.write_text(serialized_json(implementation), encoding="utf-8")
        return
    failures: list[str] = []
    if CURRENT_PATH.read_text(encoding="utf-8") != current:
        failures.append(str(CURRENT_PATH.relative_to(ROOT)))
    fields = ("maturityManifest", "currentImplementation", "productCallerState",
              "productionWriterState", "subsystemMaturity", "completion")
    if any(current_map.get(key) != implementation.get(key) for key in fields):
        failures.append(str(MAP_PATH.relative_to(ROOT)))
    if failures:
        raise SystemExit("control.runtime maturity projections are stale: " + ", ".join(failures))


def parse_mode(argv: list[str] | None = None) -> str:
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=("check", "sync"), nargs="?", default="check")
    parser.add_argument("--check", action="store_true", help="Read-only check (alias for check)")
    args = parser.parse_args(argv)
    if args.check and args.mode == "sync":
        parser.error("--check cannot be combined with sync")
    return args.mode


def main() -> None:
    run(parse_mode())


if __name__ == "__main__":
    main()
