#!/usr/bin/env python3
"""Generate and check prompt.registry documentation truth from the implementation map."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOC = ROOT / "docs/modules/prompt.registry"
MAP = DOC / "IMPLEMENTATION_MAP.json"
FACTS = DOC / "QUALIFICATION_FACTS.json"
STATUS = DOC / "QUALIFICATION_STATUS.md"
BEGIN = "<!-- BEGIN GENERATED QUALIFICATION FACTS -->"
END = "<!-- END GENERATED QUALIFICATION FACTS -->"


def derive() -> dict:
    source = json.loads(MAP.read_text())
    boundary = source["claimBoundary"]
    closed_world = bool(source.get("closedWorldPublicFunctions", False))
    source_implemented = bool(
        boundary.get("sourceRootPresent")
        and boundary.get("implementedOperationMappingComplete")
    )
    source_composed = source_implemented and bool(source.get("exactSourceEvidence", {}).get("entries"))
    production_ready = bool(
        boundary.get("productionImplementation")
        and boundary.get("productExecutionProved")
        and boundary.get("activation")
        and boundary.get("independentAcceptance")
        and closed_world
    )
    released = bool(boundary.get("release") and production_ready)
    facts = {
        "schema": "hepta.prompt-registry.documentation-facts.v1",
        "activePersistentSchemas": source["activePersistentSchemas"],
        "sourceImplemented": source_implemented,
        "sourceComposed": source_composed,
        "productExecutionProved": bool(boundary.get("productExecutionProved")),
        "closedWorldPublicFunctions": closed_world,
        "productActivated": bool(boundary.get("activation")),
        "independentlyAccepted": bool(boundary.get("independentAcceptance")),
        "productionReady": production_ready,
        "released": released,
    }
    if (not facts["productExecutionProved"] or not closed_world) and any(
        facts[key] for key in ("productActivated", "independentlyAccepted", "productionReady", "released")
    ):
        raise SystemExit("claim boundary permits a completion claim without product/closed-world proof")
    return facts


def render_block(facts: dict) -> str:
    schemas = ", ".join(map(str, facts["activePersistentSchemas"]))
    rows = [
        ("activePersistentSchemas", schemas),
        ("sourceImplemented", str(facts["sourceImplemented"]).lower()),
        ("sourceComposed", str(facts["sourceComposed"]).lower()),
        ("productExecutionProved", str(facts["productExecutionProved"]).lower()),
        ("closedWorldPublicFunctions", str(facts["closedWorldPublicFunctions"]).lower()),
        ("productActivated", str(facts["productActivated"]).lower()),
        ("independentlyAccepted", str(facts["independentlyAccepted"]).lower()),
        ("productionReady", str(facts["productionReady"]).lower()),
        ("released", str(facts["released"]).lower()),
    ]
    table = "\n".join(f"| {name} | {value} |" for name, value in rows)
    return f"{BEGIN}\n\n| Generated fact | Value |\n| --- | --- |\n{table}\n\n{END}"


def expected_outputs() -> tuple[str, str]:
    facts = derive()
    fact_text = json.dumps(facts, indent=2, sort_keys=True) + "\n"
    status = STATUS.read_text()
    block = render_block(facts)
    if BEGIN in status or END in status:
        if status.count(BEGIN) != 1 or status.count(END) != 1:
            raise SystemExit("malformed generated qualification facts markers")
        prefix, rest = status.split(BEGIN, 1)
        _, suffix = rest.split(END, 1)
        status = prefix.rstrip() + "\n\n" + block + suffix
    else:
        heading = "# prompt.registry qualification status\n"
        if not status.startswith(heading):
            raise SystemExit("qualification status heading changed")
        status = heading + "\n" + block + "\n" + status[len(heading):].lstrip("\n")
    return fact_text, status


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--write", action="store_true")
    mode.add_argument("--check", action="store_true")
    args = parser.parse_args()
    fact_text, status_text = expected_outputs()
    if args.write:
        FACTS.write_text(fact_text)
        STATUS.write_text(status_text)
        return
    failures = []
    if not FACTS.is_file() or FACTS.read_text() != fact_text:
        failures.append(str(FACTS.relative_to(ROOT)))
    if STATUS.read_text() != status_text:
        failures.append(str(STATUS.relative_to(ROOT)))
    if failures:
        raise SystemExit("documentation truth is stale: " + ", ".join(failures))


if __name__ == "__main__":
    main()
