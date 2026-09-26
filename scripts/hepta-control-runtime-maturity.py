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
        "`control.runtime` has a deterministic deny-all planner kernel, strict public input guards, a crash-bounded `PlannerStoreV1` source candidate, and one authenticated bounded read-only Agentd context caller. It does **not** yet have a named global-planner product caller, production writer, independently admitted authority consumer, effect executor, terminal reconciler, activation, canary promotion, or release.",
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
            "## Remaining request-integrity work",
            "",
            "The existing Agentd read-only caller must still bind and revalidate the planner receipt at final use, derive observations from a canonical authenticated read instead of a caller-supplied scalar count, bind request/query/retrieval/ranker identity, and use a declared monotonic lease domain.",
            "",
            "## Qualification and governance",
            "",
            "All current candidate checks are pending for the exact Git candidate. Independent semantic review, operator acceptance, activation, canary promotion and release remain externally governed and false. A branch name, this generated file, or an `IMPLEMENTATION_MAP.json` source-base field is not an exact-source receipt.",
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
