#!/usr/bin/env python3
"""Generate and verify one implementation map for every registered module.

Maps are source-navigation evidence.  They deliberately distinguish a native
entrypoint from a composed production caller; an entrypoint never grants
runtime, effect, acceptance, promotion, or release authority.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def load(rel: str):
    return json.loads((ROOT / rel).read_text(encoding="utf-8"))


def git(*args: str) -> str:
    p = subprocess.run(["git", *args], cwd=ROOT, text=True, capture_output=True, check=True)
    return p.stdout.strip()


def lane_by_module():
    return {m: lane["id"] for lane in load("docs/readiness/READINESS.json")["implementationLanes"] for m in lane["modules"]}


def parse_entrypoints(module: str):
    path = ROOT / f"qualification/module-execution-dossiers/detail/{module}.md"
    text = path.read_text(encoding="utf-8") if path.exists() else ""
    match = re.search(r"\*\*Implemented entrypoints:\*\*\s*(.*)", text)
    if not match:
        return []
    entries = []
    for name, source in re.findall(r"`([^`]+)`\s+in\s+\[([^]]+)\]", match.group(1)):
        source = source.split(")", 1)[0]
        if source.startswith("../../../"):
            source = source[9:]
        source_path = ROOT / source
        entries.append(
            {
                "operation": re.sub(r"[^a-zA-Z0-9]+", "_", name).strip("_").lower(),
                "nativeSymbol": name,
                "sourcePath": source,
                "state": "source_implemented_not_product_composed",
                "authority": "none",
                "tests": [],
                "sourcePathExists": source_path.is_file(),
            }
        )
    return entries


def map_for(module: dict, source_base: dict, lanes: dict):
    mid = module["id"]
    roots = [x["path"] for x in module["rootBindings"]]
    operations = parse_entrypoints(mid)
    if not operations:
        # Keep the map explicit even where the dossier has not named a native
        # entrypoint.  This is a handoff blocker, not a production claim.
        operations = [
            {
                "operation": "native_mapping_pending",
                "nativeSymbol": None,
                "sourcePath": None,
                "state": "specified_target_native_mapping_pending",
                "authority": "none",
                "tests": [],
                "sourcePathExists": False,
            }
        ]
    return {
        "schema": "hepta.module-implementation-map.v3",
        "schemaVersion": 3,
        "sourceBase": source_base,
        "laneId": lanes[mid],
        "module": mid,
        "owner": module["owner"],
        "deputy": module["deputy"],
        "technicalGuide": module["technicalDocument"],
        "declaredRoots": roots,
        "resolvedRoots": [x for x in roots if (ROOT / x).exists()],
        "sourceRootPresent": all((ROOT / x).exists() for x in roots),
        "productionImplementation": False,
        "productCallerState": "not_composed",
        "productionWriterState": "not_established",
        "operations": operations,
        "repositoryControlledGaps": [
            "Bind every operation to an authenticated consumer callsite and owner store.",
            "Run exact-head and deterministic synthetic-merge tests before changing the claim boundary.",
        ],
        "externalEvidenceGates": [
            "independent semantic review",
            "product execution and target-host qualification",
            "operator acceptance, canary, promotion and release",
        ],
        "claimBoundary": {
            "nativeSourceMappingComplete": all(
                op["sourcePathExists"] and op["nativeSymbol"] for op in operations
            ),
            "sourceRootPresent": all((ROOT / x).exists() for x in roots),
            "productionImplementation": False,
            "productExecutionProved": False,
            "independentAcceptance": False,
            "activation": False,
            "release": False,
        },
    }


def normalize_for_write(value):
    # sourcePathExists is a derived field, retained only to make verification
    # failures actionable and regenerated on every run.
    return value


def generate():
    modules = load("docs/modules/MODULES.json")["modules"]
    lanes = lane_by_module()
    source_base = {"commit": git("rev-parse", "HEAD"), "tree": git("rev-parse", "HEAD^{tree}")}
    written = []
    for module in modules:
        path = ROOT / f"docs/modules/{module['id']}/IMPLEMENTATION_MAP.json"
        if path.exists():
            continue
        value = normalize_for_write(map_for(module, source_base, lanes))
        path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        written.append(str(path.relative_to(ROOT)))
    print(json.dumps({"generated": len(written), "maps": written}, ensure_ascii=False))


def verify():
    modules = load("docs/modules/MODULES.json")["modules"]
    lanes = lane_by_module()
    failures = []
    for module in modules:
        mid = module["id"]
        path = ROOT / f"docs/modules/{mid}/IMPLEMENTATION_MAP.json"
        if not path.is_file():
            failures.append(f"{mid}: missing map")
            continue
        try:
            row = json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:
            failures.append(f"{mid}: invalid JSON: {exc}")
            continue
        if row.get("module") != mid:
            failures.append(f"{mid}: identity")
        if row.get("laneId") != lanes.get(mid):
            failures.append(f"{mid}: lane")
        roots = [x["path"] for x in module["rootBindings"]]
        declared = row.get("declaredRoots", row.get("sourceRoot", []))
        if isinstance(declared, str):
            declared = [declared]
        if declared != roots:
            failures.append(f"{mid}: declared roots")
        ops = row.get("operations")
        if not isinstance(ops, list) or not ops:
            failures.append(f"{mid}: operations")
            continue
        if "sourceRootPresent" not in row or "productionImplementation" not in row:
            failures.append(f"{mid}: status model")
        for op in ops:
            if not (op.get("operation") or op.get("designOperation")):
                failures.append(f"{mid}: operation id")
            source = op.get("sourcePath") or (op.get("ownerEntrypoint") or {}).get("path")
            if source and not (ROOT / source).is_file():
                failures.append(f"{mid}: missing source {source}")
        boundary = row.get("claimBoundary") or row.get("completion")
        if not isinstance(boundary, dict):
            failures.append(f"{mid}: claim boundary")
    if failures:
        raise SystemExit("FAIL_HEPTA_IMPLEMENTATION_MAPS: " + "; ".join(failures))
    print(json.dumps({"status": "PASS_HEPTA_IMPLEMENTATION_MAPS", "modules": len(modules), "maps": len(modules), "productionImplementationProved": False}, sort_keys=True))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["generate", "verify"])
    args = parser.parse_args()
    generate() if args.command == "generate" else verify()


if __name__ == "__main__":
    main()
