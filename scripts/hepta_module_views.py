#!/usr/bin/env python3
"""Generate duplicated module presentation facts from MODULES.json.

MODULES.json is the only hand-maintained source for module lifecycle/status,
source-root presence, production implementation, bootstrap package and technical
document identity. SOURCE_BINDINGS.json and MODULE_DOCS.json retain these fields
only as generated compatibility views until their next schema revision removes
them entirely.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODULES = ROOT / "docs/modules/MODULES.json"
BINDINGS = ROOT / "docs/modules/SOURCE_BINDINGS.json"
DOCS = ROOT / "docs/modules/MODULE_DOCS.json"


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def render(document: dict) -> str:
    return json.dumps(document, indent=2, ensure_ascii=False) + "\n"


def generated_facts(module: dict) -> dict:
    return {
        "lifecycle": module["lifecycle"],
        "sourceStatus": module["sourceStatus"],
        "source_root_present": module["source_root_present"],
        "production_implementation": module["production_implementation"],
        "bootstrapWorkPackage": module["bootstrapWorkPackage"],
        "technicalDocument": module["technicalDocument"],
    }


def project() -> dict[Path, str]:
    modules_doc = load(MODULES)
    modules = {row["id"]: row for row in modules_doc["modules"]}
    if len(modules) != len(modules_doc["modules"]):
        raise ValueError("duplicate module id in MODULES.json")

    bindings_doc = load(BINDINGS)
    for row in bindings_doc["bindings"]:
        module = modules.get(row["module"])
        if module is None:
            raise ValueError(f"unknown binding module: {row['module']}")
        facts = generated_facts(module)
        for key in (
            "lifecycle",
            "sourceStatus",
            "source_root_present",
            "production_implementation",
            "bootstrapWorkPackage",
            "technicalDocument",
        ):
            row[key] = facts[key]

    docs_doc = load(DOCS)
    for row in docs_doc["modules"]:
        module = modules.get(row["module"])
        if module is None:
            raise ValueError(f"unknown document module: {row['module']}")
        facts = generated_facts(module)
        for key in (
            "lifecycle",
            "sourceStatus",
            "source_root_present",
            "production_implementation",
            "bootstrapWorkPackage",
        ):
            row[key] = facts[key]
        row["path"] = facts["technicalDocument"]

    return {BINDINGS: render(bindings_doc), DOCS: render(docs_doc)}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check", action="store_true")
    mode.add_argument("--write", action="store_true")
    args = parser.parse_args()

    projected = project()
    changed: list[str] = []
    for path, expected in projected.items():
        actual = path.read_text(encoding="utf-8")
        if actual != expected:
            changed.append(path.relative_to(ROOT).as_posix())
            if args.write:
                path.write_text(expected, encoding="utf-8")
    if args.check and changed:
        print("FAIL_HEPTA_MODULE_VIEWS: generated view drift: " + ", ".join(changed))
        return 1
    print(
        json.dumps(
            {
                "status": "PASS_HEPTA_MODULE_VIEWS" if not changed else "UPDATED_HEPTA_MODULE_VIEWS",
                "source": "docs/modules/MODULES.json",
                "views": ["docs/modules/SOURCE_BINDINGS.json", "docs/modules/MODULE_DOCS.json"],
                "changed": changed,
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
