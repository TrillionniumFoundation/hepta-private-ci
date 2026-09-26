#!/usr/bin/env python3
"""Generate/check kernel.authority current-state projections.

The implementation map is the only input. The projections are navigation and
readiness facts; they never grant deployment, activation, acceptance or release.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MAP = ROOT / "docs/modules/kernel.authority/IMPLEMENTATION_MAP.json"
JSON_OUT = ROOT / "docs/modules/kernel.authority/CURRENT_STATE.json"
MD_OUT = ROOT / "docs/modules/kernel.authority/CURRENT_STATE.md"


def load_map() -> dict:
    value = json.loads(MAP.read_text(encoding="utf-8"))
    if value.get("module") != "kernel.authority":
        raise SystemExit("kernel.authority implementation map identity mismatch")
    return value


def projection(row: dict) -> dict:
    boundary = row["claimBoundary"]
    return {
        "schema": "hepta.kernel-authority-current-state.v1",
        "schemaVersion": 1,
        "module": "kernel.authority",
        "generatedFrom": "docs/modules/kernel.authority/IMPLEMENTATION_MAP.json",
        "sourceBase": row["sourceBase"],
        "current": {
            "sourceRootPresent": bool(row["sourceRootPresent"]),
            "productionImplementation": bool(row["productionImplementation"]),
            "productCallerState": row["productCallerState"],
            "productionWriterState": row["productionWriterState"],
            "claimBoundary": boundary,
        },
        "operations": [
            {
                "operation": op["operation"],
                "nativeSymbol": op.get("nativeSymbol"),
                "state": op["state"],
                "sourcePath": op.get("sourcePath"),
                "tests": op.get("tests") or [],
            }
            for op in row["operations"]
        ],
        "productCallers": row.get("productCallers", []),
        "remainingToTarget": {
            "repositoryControlledGaps": row.get("repositoryControlledGaps", []),
            "externalEvidenceGates": row.get("externalEvidenceGates", []),
        },
    }


def render_json(value: dict) -> str:
    return json.dumps(value, indent=2, ensure_ascii=False) + "\n"


def render_markdown(value: dict) -> str:
    current = value["current"]
    boundary = current["claimBoundary"]
    lines = [
        "# kernel.authority current state",
        "",
        "This file is generated from `IMPLEMENTATION_MAP.json` by",
        "`scripts/kernel_authority_status.py`. It records source-navigation and",
        "readiness facts only; it grants no deployment, activation or release authority.",
        "",
        "## Claims",
        "",
        f"- Production implementation: `{str(current['productionImplementation']).lower()}`",
        f"- Product execution proved: `{str(bool(boundary['productExecutionProved'])).lower()}`",
        f"- Independent acceptance: `{str(bool(boundary['independentAcceptance'])).lower()}`",
        f"- Activation: `{str(bool(boundary['activation'])).lower()}`",
        f"- Release: `{str(bool(boundary['release'])).lower()}`",
        f"- Product caller state: `{current['productCallerState']}`",
        f"- Production writer state: `{current['productionWriterState']}`",
        "",
        "## Operations",
        "",
        "| Operation | State | Source | Tests |",
        "| --- | --- | --- | ---: |",
    ]
    for op in value["operations"]:
        lines.append(
            f"| `{op['operation']}` | `{op['state']}` | "
            f"`{op['sourcePath'] or '-'}` | {len(op['tests'])} |"
        )
    lines.extend(["", "## Repository-controlled gaps", ""])
    lines.extend(f"- {gap}" for gap in value["remainingToTarget"]["repositoryControlledGaps"])
    lines.extend(["", "## External evidence gates", ""])
    lines.extend(f"- {gate}" for gate in value["remainingToTarget"]["externalEvidenceGates"])
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["write", "check"])
    args = parser.parse_args()
    value = projection(load_map())
    expected_json = render_json(value)
    expected_md = render_markdown(value)
    if args.command == "write":
        JSON_OUT.write_text(expected_json, encoding="utf-8")
        MD_OUT.write_text(expected_md, encoding="utf-8")
        return
    failures = []
    if not JSON_OUT.is_file() or JSON_OUT.read_text(encoding="utf-8") != expected_json:
        failures.append(str(JSON_OUT.relative_to(ROOT)))
    if not MD_OUT.is_file() or MD_OUT.read_text(encoding="utf-8") != expected_md:
        failures.append(str(MD_OUT.relative_to(ROOT)))
    if failures:
        raise SystemExit("stale kernel.authority status projections: " + ", ".join(failures))
    print("PASS_KERNEL_AUTHORITY_STATUS_PROJECTIONS")


if __name__ == "__main__":
    main()
