"""Generated Lane-B navigation; module-level evidence never grants execution."""

from typing import Any


def trace_projection(
    truth: dict[str, Any], maps: list[dict[str, Any]]
) -> dict[str, Any]:
    entries = []
    for row in maps:
        for item in row["operations"]:
            if row["module"] == "ui.native":
                entries.append(
                    {
                        "module": row["module"],
                        "operation": item["operation"],
                        "map": "docs/modules/ui.native/IMPLEMENTATION_MAP.json",
                        "testBindingScope": "module",
                        "testSurfaces": row["testSurfaces"],
                        "qualificationWorkflow": row["qualificationWorkflow"],
                        "qualificationEstablished": False,
                    }
                )
                continue
            entries.append(
                {
                    "module": row["module"],
                    "operation": item.get("designOperation") or item.get("operation"),
                    "map": f"docs/modules/{row['module']}/IMPLEMENTATION_MAP.json",
                    "tests": [
                        {"path": test["path"], "command": test["command"]}
                        for test in item["tests"]
                    ],
                }
            )
    return {
        "schema": "hepta.lane-b-test-traceability.v2",
        "schemaVersion": 2,
        "sourceBase": truth["sourceBase"],
        "laneId": truth["laneId"],
        "moduleCount": len(maps),
        "operationCount": len(entries),
        "entries": entries,
        "claimBoundary": {
            "testPathCoverageComplete": all(
                row["module"] != "ui.native" for row in maps
            ),
            "workflowExecutionRequired": True,
            "productExecutionProvedByRegistry": False,
            "externalEffectsProvedByRegistry": False,
        },
    }


def native_projection(
    truth: dict[str, Any], maps: list[dict[str, Any]], operation_count: int
) -> str:
    base = truth["sourceBase"]
    lines = [
        "# Lane B source contracts and implementation gaps",
        "",
        "**Lane:** `LANE-B-RUNTIME`  ",
        f"**Immutable source base:** `{base['commit']}` / tree `{base['tree']}`  ",
        "**Exact candidate:** derived from Git at verification time; never hard-coded  ",
        "**Repository-controlled scope:** documentation, operation inventory and source mapping verified; implementation gaps are reported per module  ",
        "**External scope:** product execution, deployment, real effects and independent acceptance remain open",
        "",
        "## 1. Truth model",
        "",
        "The central truth is a closed index. Detailed module roots, ownership, terminal observers, native symbols, delegated callees, tests and external evidence gates live in each module's `IMPLEMENTATION_MAP.json`. This file and `TEST_TRACEABILITY.json` are generated from those maps. A source symbol or fixture is not deployment or external-effect evidence.",
        "",
    ]
    for number, row in enumerate(maps, start=2):
        native = row["module"] == "ui.native"
        lines += [
            f"## {number}. `{row['module']}`",
            "",
            row["stateOwnership"]["rule"] if native else row["stateOwnerDisposition"],
            "",
            (
                f"Native v6 module test surfaces are checked through `{row['qualificationWorkflow']}`. "
                "Per-operation test bindings and executed qualification are not established by this map."
                if native
                else row["terminalObserverDisposition"]
            ),
            "",
            "| Operation | Class | Owner entrypoint |",
            "|---|---|---|",
        ]
        for item in row["operations"]:
            if native:
                lines.append(
                    f"| `{item['operation']}` | `v6 entrypoint` | `{item['entrypoint']}` |"
                )
                continue
            owner = item.get("ownerEntrypoint") or {
                "path": item.get("sourcePath"),
                "symbol": item.get("nativeSymbol"),
            }
            lines.append(
                f"| `{item.get('designOperation') or item.get('operation')}` | `{item.get('mappingClass', 'owner_native')}` | `{owner.get('path')}` — `{owner.get('symbol')}` |"
            )
        gaps = row.get("repositoryControlledGaps", [])
        if gaps:
            lines += ["", "Remaining repository implementation gaps:", ""]
            lines += [f"- {gap}" for gap in gaps]
        lines += (
            ["", "External evidence gates:", ""]
            + [f"- {gate}" for gate in row["externalEvidenceGates"]]
            + [""]
        )
    lines += [
        "## 13. Cross-module acceptance boundary",
        "",
        f"All {operation_count} operations retain their schema's source contract. V3 maps bind each operation to its owner entrypoint, build target and test paths; native v6 retains exact entrypoints and module-level test surfaces under its strict native verifier. Owner entrypoints remain inside owner roots; delegated callees name their real owner. Exact-head and deterministic synthetic-merge validation must agree with all eleven maps and generated projections.",
        "",
        "Repository source closure does not self-issue real model/provider execution, Servo or Matrix effects, deployed Web/native artifacts, target-host measurements, hardware evidence, external-owner consent, independent acceptance, selection, promotion or release.",
        "",
    ]
    return "\n".join(line.rstrip() for line in lines)
