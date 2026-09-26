#!/usr/bin/env python3
"""Generate and verify control.runtime state projections from MATURITY.json."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
MODULE_ROOT = ROOT / "docs" / "modules" / "control.runtime"
MANIFEST_PATH = MODULE_ROOT / "MATURITY.json"
MAP_PATH = MODULE_ROOT / "IMPLEMENTATION_MAP.json"
CURRENT_PATH = MODULE_ROOT / "CURRENT_IMPLEMENTATION.md"


def load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain one JSON object")
    return value


def validate_manifest(manifest: dict[str, Any]) -> None:
    if manifest.get("schema") != "hepta.control-runtime-maturity.v1":
        raise ValueError("unexpected control.runtime maturity schema")
    if manifest.get("schemaVersion") != 1:
        raise ValueError("unexpected control.runtime maturity schemaVersion")
    if manifest.get("module") != "control.runtime":
        raise ValueError("maturity manifest names the wrong module")
    if manifest.get("authorityDelta") != "none":
        raise ValueError("maturity manifest must not widen authority")
    source = manifest.get("sourceObservation")
    if not isinstance(source, dict) or source.get("selfAuthenticatingTrackedShaClaim") is not False:
        raise ValueError("tracked maturity files cannot self-authenticate their containing commit")
    external = manifest.get("externalGovernance")
    if not isinstance(external, dict) or any(external.values()):
        raise ValueError("external governance states must remain false until external receipts exist")
    subsystems = manifest.get("subsystems")
    required = {
        "plannerKernel",
        "plannerPublicBoundary",
        "plannerStore",
        "plannerExecutionCoordinator",
        "readOnlyAgentdContextCaller",
        "globalPlannerCaller",
        "organHost",
        "embodimentReference",
        "authorityConsumer",
        "effectExecutor",
        "terminalReconciliation",
    }
    if not isinstance(subsystems, dict) or set(subsystems) != required:
        raise ValueError("control.runtime subsystem maturity inventory is not closed")


def render_current(manifest: dict[str, Any]) -> str:
    subsystems = manifest["subsystems"]
    rows = [
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
    ]
    lines = [
        "# control.runtime current implementation",
        "",
        "> Generated from `MATURITY.json`. Do not hand-edit state claims in this file.",
        "",
        "## Current claim boundary",
        "",
        "`control.runtime` has a deterministic deny-all planner kernel, strict public input guards, a crash-bounded `PlannerStoreV1` source candidate, a generic source-level authority/executor/reconciliation coordinator, and one authenticated bounded read-only Agentd context caller. The Agentd caller now uses a canonical authenticated record set, a request/query/retrieval/ranker-bound delivery seal, final-use plan-receipt binding and a monotonic process-generation lease. It does **not** yet have a named global-planner product caller, selected production writer, independently admitted production authority consumer, production effect executor, production reconciler, activation, canary promotion or release.",
        "",
        "| Subsystem | Current state | Product composition |",
        "|---|---|---:|",
    ]
    for label, key in rows:
        value = subsystems[key]
        composed = "yes" if value["productionComposed"] else "no"
        if key == "readOnlyAgentdContextCaller" and value["productionComposed"]:
            composed = "yes, bounded read-only scope"
        lines.append(f"| {label} | `{value['state']}` | {composed} |")
    lines.extend(
        [
            "",
            "## Durable store controls",
            "",
            "The source candidate implements a versioned self-validating image, exclusive writer lock, exact canonical bodies, typed evidence parent links, temp write, file and directory `fsync`, atomic replacement, indeterminate poisoning, crash failpoints, legacy digest-only migration, bounded retention compaction, monotonic backup restore, and externally anchored checkpoints. It remains unqualified and uncomposed until current exact-head and target-host evidence passes.",
            "",
            "## Request-integrity controls",
            "",
            "The bounded Agentd context path authenticates the exact owner cut and selected record set, binds owner/generation/query/limit/request/retrieval/ranker identity, seals the raw planner receipt, uses a bounded monotonic lease registry, and repeats owner-cut, content, retrieval, ranker and lease validation immediately before final use.",
            "",
            "## Execution closure",
            "",
            "`PlannerExecutionCoordinatorV1` consumes deny-all grant requests, calls an independent authority port, validates payload- and expiry-bound grants, persists request/grant/terminal evidence, stops on indeterminate outcomes, and accepts only signed reconciliation receipts. These are source contracts and fixtures, not named activated Agentd production ports.",
            "",
            "## Qualification and governance",
            "",
            "Current exact-head and synthetic-merge checks must pass for the final candidate. Independent semantic review, operator acceptance, activation, canary promotion and release remain externally governed and false. A branch name, generated file, or `IMPLEMENTATION_MAP.json` provenance field is not an exact-source execution receipt.",
            "",
        ]
    )
    return "\n".join(lines)


def projected_map(manifest: dict[str, Any], implementation: dict[str, Any]) -> dict[str, Any]:
    value = json.loads(json.dumps(implementation))
    value["maturityManifest"] = "docs/modules/control.runtime/MATURITY.json"
    value["currentImplementation"] = "docs/modules/control.runtime/CURRENT_IMPLEMENTATION.md"
    value["productCallerState"] = manifest["productCallerState"]
    value["productionWriterState"] = manifest["productionWriterState"]
    value["subsystemMaturity"] = manifest["subsystems"]
    value["completion"] = manifest["completion"]
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
    projected_fields = (
        "maturityManifest",
        "currentImplementation",
        "productCallerState",
        "productionWriterState",
        "subsystemMaturity",
        "completion",
    )
    if any(current_map.get(key) != implementation.get(key) for key in projected_fields):
        failures.append(str(MAP_PATH.relative_to(ROOT)))
    if failures:
        joined = ", ".join(failures)
        raise SystemExit(f"control.runtime maturity projections are stale: {joined}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=("check", "sync"))
    args = parser.parse_args()
    run(args.mode)


if __name__ == "__main__":
    main()
