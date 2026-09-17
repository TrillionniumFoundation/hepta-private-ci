#!/usr/bin/env python3
"""Generate and verify one implementation map for every registered module.

Maps are source-navigation evidence. They deliberately distinguish a native
entrypoint from a composed product caller; an entrypoint never grants runtime,
effect, acceptance, promotion, or release authority.

`sourceBase` denotes the immutable repository candidate inspected immediately
before a map-generation/migration commit. It is refreshed by `migrate` instead
of preserving an arbitrarily old map base. Verification proves the referenced
commit/tree pair is real and remains an ancestor of the candidate being checked.
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


def _dossier_text(module: str) -> str:
    path = ROOT / f"qualification/module-execution-dossiers/detail/{module}.md"
    return path.read_text(encoding="utf-8") if path.exists() else ""


def _normalize_dossier_link(source: str) -> str:
    source = source.split(")", 1)[0]
    if source.startswith("../../../"):
        source = source[9:]
    return source


def parse_source_tests(module: str) -> list[dict[str, str]]:
    """Read explicitly named source-test paths from one module dossier.

    These are traceability references, not pass receipts. A command is emitted
    only when the dossier itself names one in a future structured extension;
    hand-maintained maps may retain richer kind/command metadata.
    """
    text = _dossier_text(module)
    match = re.search(r"^\s*-\s*\*\*Source tests:\*\*\s*(.*)$", text, re.M)
    if not match:
        return []
    tests = []
    seen = set()
    for source in re.findall(r"\[[^]]+\]\(([^)]+)\)", match.group(1)):
        source = _normalize_dossier_link(source)
        if source in seen:
            continue
        seen.add(source)
        tests.append({"path": source, "kind": "source_reference"})
    return tests


def parse_product_callers(module: str) -> list[dict[str, str]]:
    """Read explicitly named product callers from the module dossier."""
    text = _dossier_text(module)
    match = re.search(r"^\s*-\s*\*\*Product callers:\*\*\s*(.*)$", text, re.M)
    if not match:
        return []
    callers = []
    for source in re.findall(r"\[[^]]+\]\(([^)]+)\)", match.group(1)):
        source = _normalize_dossier_link(source)
        callers.append(
            {
                "path": source,
                "state": "source_composed_pending_exact_candidate_evidence",
            }
        )
    return callers


def parse_entrypoints(module: str):
    text = _dossier_text(module)
    match = re.search(r"\*\*Implemented entrypoints:\*\*\s*(.*)", text)
    if not match:
        return []
    tests = parse_source_tests(module)
    entries = []
    for name, source in re.findall(r"`([^`]+)`\s+in\s+\[([^]]+)\]", match.group(1)):
        source = _normalize_dossier_link(source)
        source_path = ROOT / source
        entries.append(
            {
                "operation": re.sub(r"[^a-zA-Z0-9]+", "_", name).strip("_").lower(),
                "nativeSymbol": name,
                "sourcePath": source,
                "state": "source_implemented_not_product_composed",
                "authority": "none",
                "tests": [dict(test) for test in tests],
                "sourcePathExists": source_path.is_file(),
            }
        )
    return entries


def map_for(module: dict, source_base: dict, lanes: dict):
    mid = module["id"]
    roots = [x["path"] for x in module["rootBindings"]]
    operations = parse_entrypoints(mid)
    product_callers = parse_product_callers(mid)
    if not operations:
        # Keep the map explicit even where the dossier has not named a native
        # entrypoint. This is a handoff blocker, not a production claim.
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
        "productCallerState": (
            "composed_source_caller_pending_evidence" if product_callers else "not_composed"
        ),
        "productionWriterState": "not_established",
        "productCallers": product_callers,
        "operations": operations,
        "repositoryControlledGaps": [
            "Bind every target operation that requires composition to its authenticated consumer callsite and owner store.",
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
    """Upgrade/normalize maps without discarding implementation evidence.

    v1 used ``sourceRoot`` and canonical operation fields directly; v2 wrapped
    the native anchor in ``ownerEntrypoint`` and called it ``designOperation``.
    v3 keeps every legacy field for compatibility while adding one stable
    operation vocabulary and top-level status/claim fields.

    Migration intentionally refreshes ``sourceBase`` to the current immutable
    candidate. Keeping an old map source identity after source/tests/callers have
    changed is stale evidence, not compatibility.
    """
    roots = [x["path"] for x in module["rootBindings"]]
    declared = row.get("declaredRoots", row.get("sourceRoot", roots))
    if isinstance(declared, str):
        declared = [declared]
    # Keep a truthful root declaration even when an old hand-written map used
    # an obsolete spelling; the module registry is authoritative.
    declared = roots
    dossier_tests = parse_source_tests(module["id"])
    product_callers = row.get("productCallers") or parse_product_callers(module["id"])
    operations = []
    for original in row.get("operations", []):
        op = dict(original)
        name = op.get("operation") or op.get("designOperation") or "native_mapping_pending"
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
        if "tests" not in op or not op["tests"]:
            op["tests"] = [dict(test) for test in dossier_tests]
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
            # Always bind the migrated map to the candidate being inspected.
            "sourceBase": source_base,
            "laneId": row.get("laneId") or lanes[module["id"]],
            "module": module["id"],
            "owner": row.get("owner", module["owner"]),
            "deputy": row.get("deputy", module["deputy"]),
            "technicalGuide": row.get("technicalGuide", module["technicalDocument"]),
            "declaredRoots": declared,
            "resolvedRoots": resolve_source_roots(ROOT, module),
            "sourceRootPresent": all((ROOT / x).exists() for x in declared),
            "productionImplementation": bool(row.get("productionImplementation", False)),
            "productCallerState": row.get(
                "productCallerState",
                "composed_source_caller_pending_evidence"
                if product_callers
                else "not_composed",
            ),
            "productCallers": product_callers,
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
            "Bind every target operation that requires composition to its authenticated consumer callsite and owner store.",
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
    # ``sourceRoot`` is a v1 spelling. Retain it as a compatibility alias so
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
        migrated = migrate_map(row, module, lanes, source_base)
        path.write_text(
            json.dumps(migrated, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )
        changed.append(str(path.relative_to(ROOT)))
    print(json.dumps({"migrated": len(changed), "maps": changed}, ensure_ascii=False))


def generate():
    modules = load("docs/modules/MODULES.json")["modules"]
    lanes = lane_by_module()
    source_base = current_source_base()
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


def _verify_source_base(mid: str, source_base: object, failures: list[str], identities: set):
    if (
        not isinstance(source_base, dict)
        or not source_base.get("commit")
        or not source_base.get("tree")
    ):
        failures.append(f"{mid}: source base")
        return
    commit = source_base["commit"]
    tree = source_base["tree"]
    identities.add((commit, tree))
    try:
        observed_tree = git("rev-parse", f"{commit}^{{tree}}")
    except subprocess.CalledProcessError:
        failures.append(f"{mid}: unknown source-base commit {commit}")
        return
    if observed_tree != tree:
        failures.append(f"{mid}: source-base tree mismatch")
    ancestor = subprocess.run(
        ["git", "merge-base", "--is-ancestor", commit, "HEAD"],
        cwd=ROOT,
        text=True,
        capture_output=True,
    )
    if ancestor.returncode != 0:
        failures.append(f"{mid}: source base is not an ancestor of HEAD")


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
        _verify_source_base(mid, row.get("sourceBase"), failures, source_bases)
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
            tests = op.get("tests", [])
            if not isinstance(tests, list):
                failures.append(f"{mid}: tests must be a list")
            for test in tests if isinstance(tests, list) else []:
                if not isinstance(test, dict) or not test.get("path"):
                    failures.append(f"{mid}: invalid test traceability")
                    continue
                if not (ROOT / test["path"]).is_file():
                    failures.append(f"{mid}: missing test {test['path']}")
        for caller in row.get("productCallers", []):
            if not isinstance(caller, dict) or not caller.get("path"):
                failures.append(f"{mid}: invalid product caller")
                continue
            if not (ROOT / caller["path"]).is_file():
                failures.append(f"{mid}: missing product caller {caller['path']}")
        boundary = row.get("claimBoundary") or row.get("completion")
        if not isinstance(boundary, dict):
            failures.append(f"{mid}: claim boundary")
    # Historical maps may legitimately bind different source candidates. What
    # matters is that every referenced commit/tree is real and ancestral; new
    # `migrate` runs refresh all maps to one current source base.
    if failures:
        raise SystemExit("FAIL_HEPTA_IMPLEMENTATION_MAPS: " + "; ".join(failures))
    print(
        json.dumps(
            {
                "status": "PASS_HEPTA_IMPLEMENTATION_MAPS",
                "modules": len(modules),
                "maps": len(modules),
                "sourceBaseIdentities": len(source_bases),
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
