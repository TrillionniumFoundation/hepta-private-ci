#!/usr/bin/env python3
"""Generate and verify one implementation map for every registered module.

Maps are source-navigation evidence.  They deliberately distinguish a native
entrypoint from a composed production caller; an entrypoint never grants
runtime, effect, acceptance, promotion, or release authority.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
from pathlib import Path

from hepta_module_source_roots import resolve_source_roots

ROOT = Path(__file__).resolve().parents[1]


def current_source_base() -> dict[str, str]:
    """Return the immutable source identity used by generated maps."""
    return {"commit": git("rev-parse", "HEAD"), "tree": git("rev-parse", "HEAD^{tree}")}


def load(rel: str):
    return json.loads((ROOT / rel).read_text(encoding="utf-8"))


def git(*args: str) -> str:
    p = subprocess.run(
        ["git", *args], cwd=ROOT, text=True, capture_output=True, check=True
    )
    return p.stdout.strip()


def lane_by_module():
    return {
        m: lane["id"]
        for lane in load("docs/readiness/READINESS.json")["implementationLanes"]
        for m in lane["modules"]
    }


def discover_tests_for_source(source: str | None) -> list[str]:
    """Return stable Rust test identities colocated with one native source."""
    if not source:
        return []
    source_path = ROOT / source
    if not source_path.is_file():
        return []
    candidates = {source_path}
    if source_path.suffix == ".rs":
        candidates.update(source_path.parent.glob("*tests.rs"))
        candidates.update(source_path.parent.glob("*_tests.rs"))
    pattern = re.compile(
        r"#\[(?:tokio::)?test(?:\([^\]]*\))?\]\s*(?:async\s+)?fn\s+([A-Za-z0-9_]+)"
    )
    tests: list[str] = []
    for candidate in sorted(candidates):
        text = candidate.read_text(encoding="utf-8")
        relative = candidate.relative_to(ROOT).as_posix()
        tests.extend(f"{relative}::{name}" for name in pattern.findall(text))
    return sorted(set(tests))


def discover_companion_tests_for_source(source: str | None) -> list[str]:
    """Return tests from the source file and its exact sibling test module.

    Product callers and persistence owners often live in large source
    directories; scanning every sibling test file would incorrectly attribute
    unrelated module evidence.  Exact companions keep the evidence bounded.
    """
    if not source:
        return []
    source_path = ROOT / source
    if not source_path.is_file():
        return []
    candidates = {source_path}
    if source_path.suffix == ".rs":
        companion = source_path.with_name(source_path.stem + "_tests.rs")
        if companion.is_file():
            candidates.add(companion)
    pattern = re.compile(
        r"#\[(?:tokio::)?test(?:\([^\]]*\))?\]\s*(?:async\s+)?fn\s+([A-Za-z0-9_]+)"
    )
    tests: list[str] = []
    for candidate in sorted(candidates):
        text = candidate.read_text(encoding="utf-8")
        relative = candidate.relative_to(ROOT).as_posix()
        tests.extend(f"{relative}::{name}" for name in pattern.findall(text))
    return sorted(set(tests))


def refresh_integration_evidence(row: dict) -> dict:
    """Discover tests for explicitly composed product callers and store owners."""
    refreshed = dict(row)
    tests: set[str] = set()
    for key in ("productCallers", "persistenceOwner"):
        for binding in row.get(key, []):
            source = binding.split("::", 1)[0]
            tests.update(discover_companion_tests_for_source(source))
    refreshed["integrationTests"] = sorted(tests)
    return refreshed


def refresh_operation_evidence(row: dict) -> dict:
    """Refresh source existence and test inventory without widening claims."""
    refreshed = dict(row)
    operations = []
    for original in row.get("operations", []):
        op = dict(original)
        source = op.get("sourcePath")
        op["sourcePathExists"] = bool(source and (ROOT / source).is_file())
        op["tests"] = discover_tests_for_source(source)
        operations.append(op)
    refreshed["operations"] = operations
    return refreshed


def parse_entrypoints(module: str):
    path = ROOT / f"qualification/module-execution-dossiers/detail/{module}.md"
    text = path.read_text(encoding="utf-8") if path.exists() else ""
    match = re.search(r"\*\*(?:Implemented|Canonical engine) entrypoints:\*\*\s*(.*)", text)
    if not match:
        return []
    entries = []
    # One source clause may name several entrypoints, for example:
    # `build_qualified_candidate` and `prove_compaction` in [qualified.rs](...).
    # Parse the source once, then bind every backticked symbol before that
    # source. Splitting on semicolons preserves the older one-symbol-per-source
    # dossier spelling as well.
    for clause in match.group(1).split(";"):
        source_match = re.search(r"\s+in\s+\[([^]]+)\]", clause)
        if not source_match:
            continue
        source = source_match.group(1)
        if source.startswith("../../../"):
            source = source[9:]
        source_path = ROOT / source
        names = re.findall(r"`([^`]+)`", clause[: source_match.start()])
        for name in names:
            entries.append(
                {
                    "operation": re.sub(r"[^a-zA-Z0-9]+", "_", name)
                    .strip("_")
                    .lower(),
                    "nativeSymbol": name,
                    "sourcePath": source,
                    "state": "source_implemented_not_product_composed",
                    "authority": "none",
                    "tests": discover_tests_for_source(source),
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
        "resolvedRoots": resolve_source_roots(ROOT, module),
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


def migrate_map(row: dict, module: dict, lanes: dict, source_base: dict) -> dict:
    """Upgrade legacy v1/v2 maps without discarding implementation evidence.

    v1 used ``sourceRoot`` and canonical operation fields directly; v2 wrapped
    the native anchor in ``ownerEntrypoint`` and called it ``designOperation``.
    v3 keeps every legacy field for compatibility while adding one stable
    operation vocabulary and top-level status/claim fields.
    """
    roots = [x["path"] for x in module["rootBindings"]]
    declared = row.get("declaredRoots", row.get("sourceRoot", roots))
    if isinstance(declared, str):
        declared = [declared]
    # Keep a truthful root declaration even when an old hand-written map used
    # an obsolete spelling; the module registry is authoritative.
    declared = roots
    operations = []
    for original in row.get("operations", []):
        op = dict(original)
        name = (
            op.get("operation") or op.get("designOperation") or "native_mapping_pending"
        )
        op.setdefault("operation", name)
        op.setdefault("designOperation", name)
        anchor = op.get("ownerEntrypoint") or {}
        if anchor:
            op.setdefault("nativeSymbol", anchor.get("symbol"))
            op.setdefault("sourcePath", anchor.get("path"))
            op.setdefault("mappingClass", "owner_native")
        else:
            op.setdefault("mappingClass", "owner_native")
        op.setdefault("delegatedCallees", [])
        op.setdefault("tests", [])
        source = op.get("sourcePath")
        op["sourcePathExists"] = bool(source and (ROOT / source).is_file())
        operations.append(op)
    if not operations:
        operations = [
            {
                "operation": "native_mapping_pending",
                "designOperation": "native_mapping_pending",
                "nativeSymbol": None,
                "sourcePath": None,
                "mappingClass": "owner_native",
                "delegatedCallees": [],
                "tests": [],
                "state": "specified_target_native_mapping_pending",
                "authority": "none",
                "sourcePathExists": False,
            }
        ]
    migrated = dict(row)
    migrated.update(
        {
            "schema": "hepta.module-implementation-map.v3",
            "schemaVersion": 3,
            "sourceBase": row.get("sourceBase") or source_base,
            "laneId": row.get("laneId") or lanes[module["id"]],
            "module": module["id"],
            "owner": row.get("owner", module["owner"]),
            "deputy": row.get("deputy", module["deputy"]),
            "technicalGuide": row.get("technicalGuide", module["technicalDocument"]),
            "declaredRoots": declared,
            "resolvedRoots": resolve_source_roots(ROOT, module),
            "sourceRootPresent": all((ROOT / x).exists() for x in declared),
            "productionImplementation": bool(
                row.get("productionImplementation", False)
            ),
            "productCallerState": row.get("productCallerState", "not_composed"),
            "productionWriterState": row.get(
                "productionWriterState", "not_established"
            ),
            "operations": operations,
        }
    )
    boundary = migrated.get("claimBoundary") or migrated.get("completion")
    if not isinstance(boundary, dict):
        boundary = {}
    migrated["claimBoundary"] = {
        **boundary,
        "nativeSourceMappingComplete": all(
            bool(op.get("sourcePathExists") and op.get("nativeSymbol"))
            for op in operations
        ),
        "sourceRootPresent": migrated["sourceRootPresent"],
        "productionImplementation": migrated["productionImplementation"],
        "productExecutionProved": bool(boundary.get("productExecutionProved", False)),
        "independentAcceptance": bool(boundary.get("independentAcceptance", False)),
        "activation": bool(boundary.get("activation", False)),
        "release": bool(boundary.get("release", False)),
    }
    migrated.setdefault(
        "repositoryControlledGaps",
        [
            "Bind every operation to an authenticated consumer callsite and owner store.",
            "Run exact-head and deterministic synthetic-merge tests before changing the claim boundary.",
        ],
    )
    migrated.setdefault(
        "externalEvidenceGates",
        [
            "independent semantic review",
            "product execution and target-host qualification",
            "operator acceptance, canary, promotion and release",
        ],
    )
    # ``sourceRoot`` is a v1 spelling.  Retain it as a compatibility alias so
    # downstream readers can migrate independently; v3 readers use roots.
    migrated["sourceRoot"] = declared
    return migrated


def migrate():
    modules = load("docs/modules/MODULES.json")["modules"]
    by_id = {m["id"]: m for m in modules}
    lanes = lane_by_module()
    source_base = current_source_base()
    changed = []
    for path in sorted((ROOT / "docs/modules").glob("*/IMPLEMENTATION_MAP.json")):
        row = json.loads(path.read_text(encoding="utf-8"))
        module = by_id.get(row.get("module") or path.parent.name)
        if module is None:
            continue
        if (
            row.get("schema") == "hepta.module-implementation-map.v3"
            and row.get("schemaVersion") == 3
        ):
            # Normalize existing v3 operations with compatibility aliases.
            migrated = migrate_map(row, module, lanes, source_base)
        else:
            migrated = migrate_map(row, module, lanes, source_base)
        path.write_text(
            json.dumps(migrated, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )
        changed.append(str(path.relative_to(ROOT)))
    print(json.dumps({"migrated": len(changed), "maps": changed}, ensure_ascii=False))


def generate():
    modules = load("docs/modules/MODULES.json")["modules"]
    lanes = lane_by_module()
    source_base = {
        "commit": git("rev-parse", "HEAD"),
        "tree": git("rev-parse", "HEAD^{tree}"),
    }
    written = []
    for module in modules:
        path = ROOT / f"docs/modules/{module['id']}/IMPLEMENTATION_MAP.json"
        if path.exists():
            continue
        value = map_for(module, source_base, lanes)
        path.write_text(
            json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )
        written.append(str(path.relative_to(ROOT)))
    print(json.dumps({"generated": len(written), "maps": written}, ensure_ascii=False))


def evidence(output: str):
    """Emit an exact-HEAD, non-authoritative implementation/test snapshot.

    Tracked implementation maps are documentation artifacts and therefore
    cannot contain the SHA of the commit that contains themselves. Exact-head
    identity is emitted at CI runtime instead, avoiding that self-reference
    while retaining one reproducible map/test artifact per candidate.
    """
    modules = load("docs/modules/MODULES.json")["modules"]
    lanes = lane_by_module()
    source_base = current_source_base()
    maps = []
    test_inventory: set[str] = set()
    for module in modules:
        path = ROOT / f"docs/modules/{module['id']}/IMPLEMENTATION_MAP.json"
        if path.is_file():
            row = json.loads(path.read_text(encoding="utf-8"))
            value = migrate_map(row, module, lanes, source_base)
            value["sourceBase"] = source_base
        else:
            value = map_for(module, source_base, lanes)
        value = refresh_operation_evidence(value)
        value = refresh_integration_evidence(value)
        value["sourceBase"] = source_base
        for operation in value["operations"]:
            test_inventory.update(operation.get("tests", []))
        test_inventory.update(value.get("integrationTests", []))
        maps.append(value)

    payload = {
        "schema": "hepta.exact-head-implementation-evidence.v1",
        "schemaVersion": 1,
        "sourceBase": source_base,
        "modules": maps,
        "testInventory": sorted(test_inventory),
        "productionImplementationProved": False,
        "independentAcceptanceProved": False,
        "releaseProved": False,
    }
    destination = ROOT / output
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    print(
        json.dumps(
            {
                "status": "PASS_HEPTA_EXACT_HEAD_IMPLEMENTATION_EVIDENCE",
                "output": (
                    str(destination.relative_to(ROOT))
                    if destination.is_relative_to(ROOT)
                    else str(destination)
                ),
                "sourceBase": source_base,
                "modules": len(maps),
                "tests": len(test_inventory),
            },
            sort_keys=True,
        )
    )


def verify():
    modules = load("docs/modules/MODULES.json")["modules"]
    lanes = lane_by_module()
    failures = []
    source_bases = set()
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
        if (
            row.get("schema") != "hepta.module-implementation-map.v3"
            or row.get("schemaVersion") != 3
        ):
            failures.append(f"{mid}: schema must be v3")
        if row.get("module") != mid:
            failures.append(f"{mid}: identity")
        if row.get("laneId") != lanes.get(mid):
            failures.append(f"{mid}: lane")
        source_base = row.get("sourceBase")
        if (
            not isinstance(source_base, dict)
            or not source_base.get("commit")
            or not source_base.get("tree")
        ):
            failures.append(f"{mid}: source base")
        else:
            source_bases.add((source_base["commit"], source_base["tree"]))
        roots = [x["path"] for x in module["rootBindings"]]
        declared = row.get("declaredRoots", row.get("sourceRoot", []))
        if isinstance(declared, str):
            declared = [declared]
        if declared != roots:
            failures.append(f"{mid}: declared roots")
        try:
            if row.get("resolvedRoots") != resolve_source_roots(ROOT, module):
                failures.append(f"{mid}: resolved source roots")
        except (ValueError, OSError) as exc:
            failures.append(f"{mid}: source alias: {exc}")
        ops = row.get("operations")
        if not isinstance(ops, list) or not ops:
            failures.append(f"{mid}: operations")
            continue
        if "sourceRootPresent" not in row or "productionImplementation" not in row:
            failures.append(f"{mid}: status model")
        for op in ops:
            if not op.get("operation"):
                failures.append(f"{mid}: operation id")
            if "nativeSymbol" not in op or "sourcePath" not in op:
                failures.append(f"{mid}: canonical operation fields")
            source = op.get("sourcePath")
            if source and not (ROOT / source).is_file():
                failures.append(f"{mid}: missing source {source}")
            if not isinstance(op.get("tests", []), list):
                failures.append(f"{mid}: operation tests must be a list")
        boundary = row.get("claimBoundary") or row.get("completion")
        if not isinstance(boundary, dict):
            failures.append(f"{mid}: claim boundary")
    if len(source_bases) != 1:
        failures.append(f"maps: source base drift ({len(source_bases)} identities)")
    if failures:
        raise SystemExit("FAIL_HEPTA_IMPLEMENTATION_MAPS: " + "; ".join(failures))
    print(
        json.dumps(
            {
                "status": "PASS_HEPTA_IMPLEMENTATION_MAPS",
                "modules": len(modules),
                "maps": len(modules),
                "productionImplementationProved": False,
            },
            sort_keys=True,
        )
    )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["generate", "migrate", "verify", "evidence"])
    parser.add_argument(
        "--output",
        default=".hepta-evidence/implementation-maps-exact-head.json",
        help="output path for the exact-head evidence artifact",
    )
    args = parser.parse_args()
    if args.command == "evidence":
        evidence(args.output)
    else:
        {"generate": generate, "migrate": migrate, "verify": verify}[args.command]()


if __name__ == "__main__":
    main()
