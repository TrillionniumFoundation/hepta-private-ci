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


def source_identity_paths() -> list[str]:
    """Return canonical paths whose mutation changes implementation-map source truth."""
    modules = load("docs/modules/MODULES.json")["modules"]
    paths = {"docs/modules/MODULES.json", "docs/modules/SOURCE_BINDINGS.json", "codex-rs/Cargo.lock"}
    for module in modules:
        paths.update(binding["path"] for binding in module["rootBindings"])
        paths.update(resolve_source_roots(ROOT, module))
    return sorted(paths)


def current_source_base() -> dict[str, str]:
    """Derive the latest canonical source snapshot without self-referential doc commits."""
    commit = git("log", "-1", "--format=%H", "HEAD", "--", *source_identity_paths())
    if not commit:
        raise SystemExit("FAIL_HEPTA_IMPLEMENTATION_MAPS: no canonical source commit")
    return {"commit": commit, "tree": git("rev-parse", f"{commit}^{{tree}}")}


def load(rel: str):
    return json.loads((ROOT / rel).read_text(encoding="utf-8"))


def git(*args: str) -> str:
    p = subprocess.run(
        ["git", *args], cwd=ROOT, text=True, capture_output=True, check=True
    )
    return p.stdout.strip()


def validate_observed_source(
    row: dict, mid: str, resolved_roots: list[str], failures: list[str]
) -> None:
    """Validate an optional exact product-source observation against HEAD.

    sourceBase remains historical batch provenance. observedAtHead is stronger:
    when present, every declared observed source path must be byte-unchanged
    from that exact commit through the current candidate. This permits later
    documentation-only projection commits without making the observation float.
    """
    observed = row.get("observedAtHead")
    if observed is None:
        return
    if not isinstance(observed, dict):
        failures.append(f"{mid}: observed source identity")
        return
    commit, tree = observed.get("commit"), observed.get("tree")
    if not (
        isinstance(commit, str)
        and bool(re.fullmatch(r"[0-9a-f]{40}", commit))
        and isinstance(tree, str)
        and bool(re.fullmatch(r"[0-9a-f]{40}", tree))
    ):
        failures.append(f"{mid}: observed source identity")
        return
    try:
        if git("rev-parse", f"{commit}^{{tree}}") != tree:
            failures.append(f"{mid}: observed source tree")
            return
        git("merge-base", "--is-ancestor", commit, "HEAD")
    except subprocess.CalledProcessError:
        failures.append(f"{mid}: observed source is not current history")
        return

    paths = row.get("observedSourcePaths", resolved_roots)
    if not (
        isinstance(paths, list)
        and paths
        and all(isinstance(path, str) and path for path in paths)
    ):
        failures.append(f"{mid}: observed source paths")
        return
    if not set(resolved_roots).issubset(set(paths)):
        failures.append(f"{mid}: observed source paths omit resolved roots")
        return
    root = ROOT.resolve()
    for path in paths:
        candidate = (ROOT / path).resolve()
        try:
            candidate.relative_to(root)
        except ValueError:
            failures.append(f"{mid}: observed source path escape {path}")
            return
        if not candidate.exists():
            failures.append(f"{mid}: missing observed source path {path}")
            return
    try:
        changed = git("diff", "--name-only", commit, "HEAD", "--", *paths)
    except subprocess.CalledProcessError:
        failures.append(f"{mid}: observed source diff failed")
        return
    if changed:
        failures.append(f"{mid}: observed source drift since {commit}")

def lane_by_module():
    return {
        m: lane["id"]
        for lane in load("docs/readiness/READINESS.json")["implementationLanes"]
        for m in lane["modules"]
    }


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


def verify():
    modules = load("docs/modules/MODULES.json")["modules"]
    lanes = lane_by_module()
    candidate_source_base = current_source_base()
    failures = []
    source_bases = set()
    candidate_bound_maps = 0
    exact_observed_fallback_maps = 0
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
            policy = row.get("sourceIdentityPolicy", "legacy_shared_batch")
            if policy not in {"legacy_shared_batch", "candidate_or_exact_observation_v1"}:
                failures.append(f"{mid}: unknown source identity policy")
            elif policy == "legacy_shared_batch":
                source_bases.add((source_base["commit"], source_base["tree"]))
            elif source_base == candidate_source_base:
                candidate_bound_maps += 1
            else:
                observed = row.get("observedAtHead")
                observed_identity = (
                    {
                        "commit": observed.get("commit"),
                        "tree": observed.get("tree"),
                    }
                    if isinstance(observed, dict)
                    else None
                )
                if source_base == observed_identity:
                    # validate_observed_source below proves that this exact
                    # owner-source commit/tree is in current history and every
                    # declared observed path is byte-unchanged through HEAD.
                    exact_observed_fallback_maps += 1
                else:
                    failures.append(
                        f"{mid}: source base is neither current candidate nor exact observed source"
                    )
        roots = [x["path"] for x in module["rootBindings"]]
        declared = row.get("declaredRoots", row.get("sourceRoot", []))
        if isinstance(declared, str):
            declared = [declared]
        if declared != roots:
            failures.append(f"{mid}: declared roots")
        try:
            resolved_roots = resolve_source_roots(ROOT, module)
            if row.get("resolvedRoots") != resolved_roots:
                failures.append(f"{mid}: resolved source roots")
            validate_observed_source(row, mid, resolved_roots, failures)
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
                "candidateBoundMaps": candidate_bound_maps,
                "exactObservedFallbackMaps": exact_observed_fallback_maps,
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
