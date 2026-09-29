#!/usr/bin/env python3
"""Generate deterministic split status for knowledge.graph.

The tracked status is deliberately declarative. Runtime execution receipts,
independent operator acceptance, activation and release remain external gates;
this generator never upgrades them from source declarations alone.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
MAP_PATH = ROOT / "docs/modules/knowledge.graph/IMPLEMENTATION_MAP.json"
JSON_PATH = ROOT / "docs/modules/knowledge.graph/CURRENT_STATUS.json"
MARKDOWN_PATH = ROOT / "docs/modules/knowledge.graph/CURRENT_STATUS.md"
SCHEMA = "hepta.knowledge-graph.current-status.v1"


class StatusError(ValueError):
    """The implementation map cannot produce a safe split status."""


def unique_keys(items: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in items:
        if key in result:
            raise StatusError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def git(*args: str) -> str:
    return subprocess.check_output(
        ["git", "-C", str(ROOT), *args],
        text=True,
        stderr=subprocess.STDOUT,
    ).strip()


def load_map() -> dict[str, Any]:
    row = json.loads(MAP_PATH.read_text(encoding="utf-8"), object_pairs_hook=unique_keys)
    if row.get("module") != "knowledge.graph":
        raise StatusError("unexpected implementation map module")
    boundary = row.get("claimBoundary")
    if not isinstance(boundary, dict):
        raise StatusError("claimBoundary must be an object")
    for key in (
        "nativeSourceMappingComplete",
        "productionImplementation",
        "productExecutionProved",
        "independentAcceptance",
        "activation",
        "release",
    ):
        if not isinstance(boundary.get(key), bool):
            raise StatusError(f"claimBoundary.{key} must be boolean")
    return row


def build_status(row: dict[str, Any]) -> dict[str, Any]:
    boundary = row["claimBoundary"]
    source_ready = bool(
        row.get("sourceRootPresent")
        and boundary["nativeSourceMappingComplete"]
        and boundary.get("implementedOperationMappingComplete", False)
    )
    production_implementation = bool(
        row.get("productionImplementation") and boundary["productionImplementation"]
    )
    product_execution = boundary["productExecutionProved"]
    independent_acceptance = boundary["independentAcceptance"]
    activation = boundary["activation"]
    release = boundary["release"]

    if activation and not independent_acceptance:
        raise StatusError("activation cannot precede independent acceptance")
    if release and not activation:
        raise StatusError("release cannot precede activation")
    if product_execution and not production_implementation:
        raise StatusError("product execution cannot precede production implementation")

    return {
        "schema": SCHEMA,
        "module": "knowledge.graph",
        "implementationMapBlob": git(
            "rev-parse", "HEAD:docs/modules/knowledge.graph/IMPLEMENTATION_MAP.json"
        ),
        "sourceObservation": row.get("observedAtHead", row.get("sourceBase")),
        "states": {
            "implementation": {
                "state": (
                    "production_implementation_proved"
                    if production_implementation
                    else "candidate_source_implemented"
                    if source_ready
                    else "incomplete"
                ),
                "sourceMapped": source_ready,
                "productionImplementationProved": production_implementation,
            },
            "testing": {
                "state": "pending_exact_head_immutable_receipts",
                "qualified": False,
                "reason": (
                    "tracked source cannot substitute for current-head execution artifacts"
                ),
            },
            "integration": {
                "state": row.get("productCallerState", "not_composed"),
                "productExecutionProved": product_execution,
            },
            "evidence": {
                "state": "pending_current_head_execution_and_target_host_receipts",
                "sourceNavigationBound": source_ready,
                "executionEvidenceEmbeddedInSource": False,
            },
            "operatorAcceptance": {
                "state": "accepted" if independent_acceptance else "not_accepted",
                "accepted": independent_acceptance,
            },
            "activation": {
                "state": "enabled" if activation else "disabled",
                "enabled": activation,
            },
            "release": {
                "state": "eligible" if release else "not_eligible",
                "eligible": release,
            },
        },
        "failClosed": True,
        "singleCompletionPercentage": None,
        "notes": [
            "Implementation, testing, integration, evidence, acceptance, activation and release are independent states.",
            "Only immutable execution artifacts and an independently verified acceptance signature may advance external gates.",
        ],
    }


def render_markdown(status: dict[str, Any]) -> str:
    states = status["states"]
    rows = [
        ("Implementation", states["implementation"]["state"]),
        ("Testing", states["testing"]["state"]),
        ("Integration", states["integration"]["state"]),
        ("Evidence", states["evidence"]["state"]),
        ("Operator acceptance", states["operatorAcceptance"]["state"]),
        ("Activation", states["activation"]["state"]),
        ("Release", states["release"]["state"]),
    ]
    lines = [
        "# knowledge.graph current status",
        "",
        "This file is generated by `scripts/hepta_kg_status.py`. It deliberately",
        "does not collapse independent delivery gates into one completion percentage.",
        "",
        f"Implementation-map blob: `{status['implementationMapBlob']}`",
        "",
        "| Dimension | State |",
        "|---|---|",
    ]
    lines.extend(f"| {name} | `{value}` |" for name, value in rows)
    lines.extend(
        [
            "",
            "Source mapping is not execution evidence. Current-head receipts, target-host",
            "measurements, an independent operator signature, activation and release must",
            "be evaluated and retained separately. Until those gates pass, the module",
            "remains fail-closed and release-ineligible.",
            "",
        ]
    )
    return "\n".join(lines)


def expected_outputs() -> tuple[str, str]:
    status = build_status(load_map())
    json_text = json.dumps(status, sort_keys=True, indent=2) + "\n"
    return json_text, render_markdown(status)


def apply() -> None:
    json_text, markdown_text = expected_outputs()
    JSON_PATH.write_text(json_text, encoding="utf-8")
    MARKDOWN_PATH.write_text(markdown_text, encoding="utf-8")


def check() -> None:
    json_text, markdown_text = expected_outputs()
    for path, expected in ((JSON_PATH, json_text), (MARKDOWN_PATH, markdown_text)):
        if not path.is_file():
            raise StatusError(f"missing generated status file: {path.relative_to(ROOT)}")
        if path.read_text(encoding="utf-8") != expected:
            raise StatusError(f"stale generated status file: {path.relative_to(ROOT)}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--apply", action="store_true")
    mode.add_argument("--check", action="store_true")
    args = parser.parse_args()
    try:
        if args.apply:
            apply()
        else:
            check()
    except (StatusError, OSError, subprocess.CalledProcessError, json.JSONDecodeError) as exc:
        print(f"FAIL_HEPTA_KG_STATUS: {exc}", file=sys.stderr)
        return 1
    print("PASS_HEPTA_KG_STATUS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
