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


def bound_package_roots(module_id: str) -> list[str]:
    registry = ROOT / "docs/modules/CARGO_BINDINGS.json"
    if not registry.is_file():
        return []
    rows = load("docs/modules/CARGO_BINDINGS.json").get("bindings", [])
    return sorted(
        {
            row["packagePath"]
            for row in rows
            if row.get("module") == module_id and row.get("packagePath")
        }
    )


def effective_source_roots(module: dict) -> list[str]:
    declared = [x["path"] for x in module["rootBindings"]]
    return sorted(set(declared) | set(bound_package_roots(module["id"])))


def current_source_root_trees(paths: list[str]) -> dict[str, str]:
    return {path: git("rev-parse", f"HEAD:{path}") for path in paths}


def source_base_tracks_paths(
    source_base: dict, paths: list[str], root_trees: object
) -> bool:
    """Verify current bound roots against immutable Git tree pins.

    Root-tree comparison works in shallow CI checkouts.  When the historical
    source-base commit is available locally, also verify its commit/tree pair,
    ancestry, and per-root tree identities.
    """
    commit = source_base.get("commit")
    tree = source_base.get("tree")
    if not commit or not tree or not paths or not isinstance(root_trees, dict):
        return False
    if set(root_trees) != set(paths):
        return False
    try:
        for path in paths:
            expected = root_trees.get(path)
            if not isinstance(expected, str) or not expected:
                return False
            if git("rev-parse", f"HEAD:{path}") != expected:
                return False
    except subprocess.CalledProcessError:
        return False

    available = subprocess.run(
        ["git", "cat-file", "-e", f"{commit}^{{commit}}"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    if available.returncode != 0:
        return True

    try:
        if git("rev-parse", f"{commit}^{{tree}}") != tree:
            return False
        for path in paths:
            if git("rev-parse", f"{commit}:{path}") != root_trees[path]:
                return False
    except subprocess.CalledProcessError:
        return False
    ancestor = subprocess.run(
        ["git", "merge-base", "--is-ancestor", commit, "HEAD"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    return ancestor.returncode == 0


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
    bound_roots = bound_package_roots(mid)
    effective_roots = effective_source_roots(module)
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
        "boundPackageRoots": bound_roots,
        "effectiveSourceRoots": effective_roots,
        "sourceFreshnessPolicy": "bound_root_tree_pins_match_current_head",
        "sourceRootTrees": current_source_root_trees(effective_roots),
        "resolvedRoots": resolve_source_roots(ROOT, module),
        "sourceRootPresent": all((ROOT / x).exists() for x in effective_roots),
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
            "sourceRootPresent": all((ROOT / x).exists() for x in effective_roots),
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
    bound_roots = bound_package_roots(module["id"])
    effective_roots = effective_source_roots(module)
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
    fresh_operations = parse_entrypoints(module["id"])
    known_symbols = {op.get("nativeSymbol") for op in operations}
    for fresh in fresh_operations:
        if fresh.get("nativeSymbol") not in known_symbols:
            fresh = dict(fresh)
            fresh.setdefault("designOperation", fresh["operation"])
            fresh.setdefault("mappingClass", "owner_native")
            fresh.setdefault("delegatedCallees", [])
            operations.append(fresh)
            known_symbols.add(fresh.get("nativeSymbol"))
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
            "sourceBase": source_base,
            "laneId": row.get("laneId") or lanes[module["id"]],
            "module": module["id"],
            "owner": row.get("owner", module["owner"]),
            "deputy": row.get("deputy", module["deputy"]),
            "technicalGuide": row.get("technicalGuide", module["technicalDocument"]),
            "declaredRoots": declared,
            "boundPackageRoots": bound_roots,
            "effectiveSourceRoots": effective_roots,
            "sourceFreshnessPolicy": "bound_root_tree_pins_match_current_head",
        "sourceRootTrees": current_source_root_trees(effective_roots),
            "resolvedRoots": resolve_source_roots(ROOT, module),
            "sourceRootPresent": all((ROOT / x).exists() for x in effective_roots),
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


def verify():
    modules = load("docs/modules/MODULES.json")["modules"]
    lanes = lane_by_module()
    failures = []
    freshness_verified = 0
    legacy_unverified = 0
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
        roots = [x["path"] for x in module["rootBindings"]]
        declared = row.get("declaredRoots", row.get("sourceRoot", []))
        if isinstance(declared, str):
            declared = [declared]
        if declared != roots:
            failures.append(f"{mid}: declared roots")
        policy = row.get("sourceFreshnessPolicy")
        if policy is not None:
            if policy != "bound_root_tree_pins_match_current_head":
                failures.append(f"{mid}: unknown source freshness policy")
            expected_bound = bound_package_roots(mid)
            expected_effective = effective_source_roots(module)
            if row.get("boundPackageRoots") != expected_bound:
                failures.append(f"{mid}: bound package roots")
            if row.get("effectiveSourceRoots") != expected_effective:
                failures.append(f"{mid}: effective source roots")
            if isinstance(source_base, dict) and source_base_tracks_paths(
                source_base, expected_effective, row.get("sourceRootTrees")
            ):
                freshness_verified += 1
            else:
                failures.append(f"{mid}: source base is stale for bound roots")
        else:
            legacy_unverified += 1
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
        actual_symbols = {op.get("nativeSymbol") for op in ops if op.get("nativeSymbol")}
        documented_symbols = {
            op.get("nativeSymbol")
            for op in parse_entrypoints(mid)
            if op.get("nativeSymbol")
        }
        if policy is not None and not documented_symbols.issubset(actual_symbols):
            missing = sorted(documented_symbols - actual_symbols)
            failures.append(f"{mid}: documented entrypoints missing from map {missing}")
        expected_effective = effective_source_roots(module)
        for op in ops:
            if not op.get("operation"):
                failures.append(f"{mid}: operation id")
            if "nativeSymbol" not in op or "sourcePath" not in op:
                failures.append(f"{mid}: canonical operation fields")
            source = op.get("sourcePath")
            if source and not (ROOT / source).is_file():
                failures.append(f"{mid}: missing source {source}")
            if policy is not None:
                if not isinstance(op.get("tests"), list) or not op.get("tests"):
                    failures.append(f"{mid}: operation lacks mapped tests {op.get('operation')}")
                if source and not any(
                    source == root or source.startswith(root + "/")
                    for root in expected_effective
                ):
                    failures.append(
                        f"{mid}: operation source outside effective roots {source}"
                    )
        boundary = row.get("claimBoundary") or row.get("completion")
        if not isinstance(boundary, dict):
            failures.append(f"{mid}: claim boundary")
    if failures:
        raise SystemExit("FAIL_HEPTA_IMPLEMENTATION_MAPS: " + "; ".join(failures))
    print(
        json.dumps(
            {
                "status": "PASS_HEPTA_IMPLEMENTATION_MAPS",
                "modules": len(modules),
                "maps": len(modules),
                "productionImplementationProved": False,
                "freshnessVerifiedMaps": freshness_verified,
                "legacyUnverifiedMaps": legacy_unverified,
            },
            sort_keys=True,
        )
    )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["generate", "migrate", "verify"])
    args = parser.parse_args()
    {"generate": generate, "migrate": migrate, "verify": verify}[args.command]()


if __name__ == "__main__":
    main()
