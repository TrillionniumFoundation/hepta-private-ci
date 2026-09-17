#!/usr/bin/env python3
"""Generate and verify one implementation map for every registered module.

Maps are source-navigation evidence.  They deliberately distinguish a native
entrypoint from a composed production caller; an entrypoint never grants
runtime, effect, acceptance, promotion, or release authority.

Legacy v3 maps used one repository-wide ``sourceBase`` identity and therefore
could remain internally consistent after module source moved.  Newly generated
or migrated maps use ``module_source_snapshot`` instead: the verifier proves the
recorded commit/tree pair and rejects any later change under every resolved or
Cargo-bound source path.  Legacy maps may migrate incrementally without hiding
the stronger freshness claim on maps that have already opted in.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
from pathlib import Path, PurePosixPath

from hepta_module_source_roots import resolve_source_roots

ROOT = Path(__file__).resolve().parents[1]
LEGACY_SOURCE_SCOPE = "legacy_shared_snapshot"
MODULE_SOURCE_SCOPE = "module_source_snapshot"


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


def cargo_packages_by_module() -> dict[str, list[str]]:
    packages: dict[str, list[str]] = {}
    for binding in load("docs/modules/CARGO_BINDINGS.json")["bindings"]:
        packages.setdefault(binding["module"], []).append(binding["packagePath"])
    return {module: sorted(paths) for module, paths in packages.items()}


def source_paths_for(module: dict, cargo_packages: dict[str, list[str]]) -> list[str]:
    """Return all source paths whose post-snapshot drift invalidates a map."""
    return sorted(
        set(resolve_source_roots(ROOT, module))
        | set(cargo_packages.get(module["id"], []))
    )


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


def map_for(module: dict, source_base: dict, lanes: dict, cargo_packages: dict):
    mid = module["id"]
    roots = [x["path"] for x in module["rootBindings"]]
    resolved = resolve_source_roots(ROOT, module)
    bound_packages = cargo_packages.get(mid, [])
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
        "sourceBaseScope": MODULE_SOURCE_SCOPE,
        "sourceTrackedPaths": source_paths_for(module, cargo_packages),
        "cargoBoundPackages": bound_packages,
        "laneId": lanes[mid],
        "module": mid,
        "owner": module["owner"],
        "deputy": module["deputy"],
        "technicalGuide": module["technicalDocument"],
        "declaredRoots": roots,
        "resolvedRoots": resolved,
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
            "sourceFreshnessVerified": True,
            "sourceRootPresent": all((ROOT / x).exists() for x in roots),
            "productionImplementation": False,
            "productExecutionProved": False,
            "independentAcceptance": False,
            "activation": False,
            "release": False,
        },
    }


def migrate_map(
    row: dict,
    module: dict,
    lanes: dict,
    source_base: dict,
    cargo_packages: dict[str, list[str]],
) -> dict:
    """Upgrade a map and refresh its source snapshot instead of preserving staleness.

    v1 used ``sourceRoot`` and canonical operation fields directly; v2 wrapped
    the native anchor in ``ownerEntrypoint`` and called it ``designOperation``.
    v3 keeps every legacy field for compatibility while adding one stable
    operation vocabulary and top-level status/claim fields.  Migration is also
    a source re-attestation: it records the current immutable commit/tree and
    all resolved/Cargo-bound paths that must remain unchanged afterwards.
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
            # Migration must never preserve an obsolete source snapshot.
            "sourceBase": source_base,
            "sourceBaseScope": MODULE_SOURCE_SCOPE,
            "sourceTrackedPaths": source_paths_for(module, cargo_packages),
            "cargoBoundPackages": cargo_packages.get(module["id"], []),
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
        "sourceFreshnessVerified": True,
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
    cargo_packages = cargo_packages_by_module()
    source_base = current_source_base()
    changed = []
    for path in sorted((ROOT / "docs/modules").glob("*/IMPLEMENTATION_MAP.json")):
        row = json.loads(path.read_text(encoding="utf-8"))
        module = by_id.get(row.get("module") or path.parent.name)
        if module is None:
            continue
        migrated = migrate_map(row, module, lanes, source_base, cargo_packages)
        path.write_text(
            json.dumps(migrated, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )
        changed.append(str(path.relative_to(ROOT)))
    print(json.dumps({"migrated": len(changed), "maps": changed}, ensure_ascii=False))


def generate():
    modules = load("docs/modules/MODULES.json")["modules"]
    lanes = lane_by_module()
    cargo_packages = cargo_packages_by_module()
    source_base = current_source_base()
    written = []
    for module in modules:
        path = ROOT / f"docs/modules/{module['id']}/IMPLEMENTATION_MAP.json"
        if path.exists():
            continue
        value = map_for(module, source_base, lanes, cargo_packages)
        path.write_text(
            json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )
        written.append(str(path.relative_to(ROOT)))
    print(json.dumps({"generated": len(written), "maps": written}, ensure_ascii=False))


def valid_repo_path(path: str) -> bool:
    candidate = PurePosixPath(path)
    return bool(path) and not candidate.is_absolute() and ".." not in candidate.parts


def verify_source_snapshot(
    mid: str,
    source_base: dict,
    tracked_paths: list[str],
    failures: list[str],
) -> None:
    commit = source_base["commit"]
    tree = source_base["tree"]
    try:
        actual_tree = git("show", "-s", "--format=%T", commit)
    except subprocess.CalledProcessError:
        failures.append(f"{mid}: source snapshot commit is not resolvable")
        return
    if actual_tree != tree:
        failures.append(f"{mid}: source snapshot commit/tree mismatch")
        return
    if not tracked_paths or any(not valid_repo_path(path) for path in tracked_paths):
        failures.append(f"{mid}: source tracked paths")
        return
    try:
        changed = git("diff", "--name-only", f"{commit}..HEAD", "--", *tracked_paths)
    except subprocess.CalledProcessError:
        failures.append(f"{mid}: source freshness diff failed")
        return
    if changed:
        failures.append(
            f"{mid}: source changed after mapped snapshot ({', '.join(changed.splitlines()[:8])})"
        )


def verify():
    modules = load("docs/modules/MODULES.json")["modules"]
    lanes = lane_by_module()
    cargo_packages = cargo_packages_by_module()
    failures = []
    legacy_source_bases = set()
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
        valid_source_base = (
            isinstance(source_base, dict)
            and bool(source_base.get("commit"))
            and bool(source_base.get("tree"))
        )
        if not valid_source_base:
            failures.append(f"{mid}: source base")
        source_scope = row.get("sourceBaseScope", LEGACY_SOURCE_SCOPE)
        if valid_source_base and source_scope == MODULE_SOURCE_SCOPE:
            expected_packages = cargo_packages.get(mid, [])
            if row.get("cargoBoundPackages") != expected_packages:
                failures.append(f"{mid}: cargo-bound packages")
            tracked_paths = row.get("sourceTrackedPaths")
            expected_paths = source_paths_for(module, cargo_packages)
            if tracked_paths != expected_paths:
                failures.append(f"{mid}: source tracked paths differ from registry bindings")
            else:
                verify_source_snapshot(mid, source_base, tracked_paths, failures)
        elif valid_source_base and source_scope == LEGACY_SOURCE_SCOPE:
            legacy_source_bases.add((source_base["commit"], source_base["tree"]))
        elif source_scope not in {MODULE_SOURCE_SCOPE, LEGACY_SOURCE_SCOPE}:
            failures.append(f"{mid}: unknown source base scope")

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
        boundary = row.get("claimBoundary") or row.get("completion")
        if not isinstance(boundary, dict):
            failures.append(f"{mid}: claim boundary")
        elif boundary.get("sourceFreshnessVerified") is True and source_scope != MODULE_SOURCE_SCOPE:
            failures.append(f"{mid}: freshness claim requires module source snapshot")
    if len(legacy_source_bases) > 1:
        failures.append(
            f"maps: legacy shared source base drift ({len(legacy_source_bases)} identities)"
        )
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
    parser.add_argument("command", choices=["generate", "migrate", "verify"])
    args = parser.parse_args()
    {"generate": generate, "migrate": migrate, "verify": verify}[args.command]()


if __name__ == "__main__":
    main()
