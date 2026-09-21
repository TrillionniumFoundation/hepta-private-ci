#!/usr/bin/env python3
"""Generate and verify one implementation map for every registered module.

Maps are source-navigation evidence.  They deliberately distinguish a native
entrypoint from a composed production caller; an entrypoint never grants
runtime, effect, acceptance, promotion, or release authority.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
from pathlib import Path

from hepta_module_source_roots import _path as checked_source_path
from hepta_module_source_roots import resolve_source_roots

ROOT = Path(__file__).resolve().parents[1]


def current_source_base() -> dict[str, str]:
    """Return the exact Git anchor used when regenerating maps.

    A committed blob cannot contain the SHA/tree of the commit that hashes that
    same blob without a cryptographic self-reference. Maps therefore store the
    exact candidate at which their mapped source/evidence was rebound, while
    verification proves that no mapped path changed between that anchor and
    the candidate HEAD. Qualification emits the current candidate HEAD/tree
    separately.
    """
    return {"commit": git("rev-parse", "HEAD"), "tree": git("rev-parse", "HEAD^{tree}")}


def unique_keys(items):
    result = {}
    for key, value in items:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def load(rel: str):
    return json.loads(
        (ROOT / rel).read_text(encoding="utf-8"), object_pairs_hook=unique_keys
    )


def git(*args: str) -> str:
    # Read the checked-out repository, not ambient GIT_DIR, replacement objects,
    # user aliases, network-backed promisor objects or external diff drivers.
    env = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
    env.update(
        GIT_CONFIG_NOSYSTEM="1",
        GIT_CONFIG_GLOBAL=os.devnull,
        GIT_NO_REPLACE_OBJECTS="1",
        GIT_NO_LAZY_FETCH="1",
        GIT_TERMINAL_PROMPT="0",
    )
    p = subprocess.run(
        ["git", "--literal-pathspecs", "-c", "core.fsmonitor=false", *args],
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=True,
    )
    return p.stdout.strip()


def checked_identity(value, candidate: dict[str, str]) -> dict[str, str]:
    if not isinstance(value, dict) or any(
        not isinstance(value.get(key), str)
        or not re.fullmatch(r"[0-9a-f]{40}", value[key])
        for key in ("commit", "tree")
    ):
        raise ValueError("source identity requires literal commit/tree SHA-1 values")
    commit, tree = value["commit"], value["tree"]
    if git("cat-file", "-t", commit) != "commit":
        raise ValueError("source identity does not identify a commit")
    if git("rev-parse", f"{commit}^{{tree}}") != tree:
        raise ValueError("source tree mismatch")
    git("merge-base", "--is-ancestor", commit, candidate["commit"])
    return {"commit": commit, "tree": tree}


def evidence_paths(row: dict, resolved_roots: list[str]) -> list[str]:
    paths = set(resolved_roots)
    for root in row.get("declaredRoots", []):
        # Alias declarations are source selection inputs, not ownership transfers.
        alias = checked_source_path(ROOT, root) / "BINDING.json"
        if alias.is_file():
            paths.add(str(alias.relative_to(ROOT)))
    for op in row["operations"]:
        source = op.get("sourcePath")
        if source is not None:
            paths.add(source)
        owner = op.get("ownerEntrypoint")
        if owner is not None:
            if not isinstance(owner, dict) or not owner.get("path"):
                raise ValueError("invalid owner entrypoint path")
            paths.add(owner["path"])
        for key in ("tests", "delegatedCallees"):
            entries = op.get(key, [])
            if not isinstance(entries, list):
                raise ValueError(f"{key} must be a list")
            for entry in entries:
                path = entry.get("path") if isinstance(entry, dict) else entry
                if not isinstance(path, str) or not path:
                    raise ValueError(f"{key} evidence requires an explicit source path")
                paths.add(path)
    for path in paths:
        local = checked_source_path(ROOT, path)
        if not local.exists():
            raise ValueError(f"missing mapped source/evidence: {path}")
    return sorted(paths)


def verify_source_identity(row: dict, roots: list[str], candidate: dict[str, str]) -> None:
    policy = row.get("sourceIdentityPolicy", "legacy_shared_batch")
    if policy not in {"legacy_shared_batch", "candidate_or_exact_observation_v1"}:
        raise ValueError(f"unknown source identity policy: {policy}")
    source = checked_identity(row.get("sourceBase"), candidate)
    paths = evidence_paths(row, roots)
    observations = [(source, paths)]
    if "observedAtHead" in row:
        observed = checked_identity(row["observedAtHead"], candidate)
        observed_paths = row.get("observedSourcePaths", roots)
        if not isinstance(observed_paths, list) or not observed_paths or any(
            not isinstance(path, str) for path in observed_paths
        ):
            raise ValueError("invalid observed source paths")
        if not set(roots).issubset(observed_paths):
            raise ValueError("observed source paths omit resolved roots")
        observations.append((observed, sorted(set(paths + observed_paths))))
    else:
        observed = None
    if policy == "candidate_or_exact_observation_v1" and source not in (
        candidate, observed
    ):
        raise ValueError("source base is neither candidate nor exact observed source")
    checked_paths = sorted({path for _, items in observations for path in items})
    require_clean_candidate(candidate, checked_paths)
    for identity, observed_paths in observations:
        for path in observed_paths:
            local = checked_source_path(ROOT, path)
            if not local.exists():
                raise ValueError(f"missing observed source/evidence: {path}")
            # Missing paths at BOTH revisions must not pass as an empty diff.
            for commit in (identity["commit"], candidate["commit"]):
                if git("cat-file", "-t", f"{commit}:{path}") not in {"blob", "tree"}:
                    raise ValueError(f"untracked source/evidence: {path}")
        if observed_paths:
            changed = git(
                "diff",
                "--no-ext-diff",
                "--no-textconv",
                "--name-only",
                identity["commit"],
                candidate["commit"],
                "--",
                *observed_paths,
            )
            if changed:
                raise ValueError(
                    "mapped source/evidence changed after source observation: " + changed
                )

    require_clean_candidate(candidate, checked_paths)


def require_clean_candidate(
    candidate: dict[str, str], paths: list[str] | None = None
) -> None:
    # This is a quiescent-checkout verifier, not a concurrent build attestor.
    # Untracked CI reports outside mapped roots are not source mutations.
    if current_source_base() != candidate or git(
        "status", "--porcelain=v1", "--untracked-files=no"
    ):
        raise ValueError(
            "candidate checkout changed or is dirty; commit source before verification"
        )
    if paths and git(
        "status", "--porcelain=v1", "--untracked-files=all", "--", *paths
    ):
        raise ValueError("mapped source checkout contains uncommitted evidence")


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
            # Navigation cannot prove a closed public API or executable tests.
            "nativeSourceMappingComplete": False,
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
            "productCallerState": row.get("productCallerState", "not_composed"),
            "productionWriterState": row.get("productionWriterState", "not_established"),
            "operations": operations,
        }
    )
    boundary = migrated.get("claimBoundary") or migrated.get("completion")
    if not isinstance(boundary, dict):
        boundary = {}
    migrated["claimBoundary"] = {
        **boundary,
        # Preserve a reviewed claim; migration must not manufacture one.
        "nativeSourceMappingComplete": boundary.get("nativeSourceMappingComplete", False),
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
    if "observedAtHead" in migrated:
        migrated["observedAtHead"] = {**migrated["observedAtHead"], **source_base}
    # ``sourceRoot`` is a v1 spelling.  Retain it as a compatibility alias so
    # downstream readers can migrate independently; v3 readers use roots.
    migrated["sourceRoot"] = declared
    return migrated


def migrate(selected_modules: list[str] | None = None):
    modules = load("docs/modules/MODULES.json")["modules"]
    by_id = {m["id"]: m for m in modules}
    selected = set(by_id) if selected_modules is None else set(selected_modules)
    unknown = selected - set(by_id)
    if unknown:
        raise SystemExit("unknown modules: " + ", ".join(sorted(unknown)))
    lanes = lane_by_module()
    source_base = current_source_base()
    # Prepare all changes before writing, so a malformed/unknown module does
    # not leave a partially rebound batch. --module confines ordinary updates.
    pending = []
    for mid in sorted(selected):
        path = ROOT / f"docs/modules/{mid}/IMPLEMENTATION_MAP.json"
        if not path.is_file():
            raise SystemExit(f"{mid}: missing map")
        row = load(str(path.relative_to(ROOT)))
        if row.get("module", mid) != mid:
            raise SystemExit(f"{mid}: identity")
        migrated = migrate_map(row, by_id[mid], lanes, source_base)
        rendered = json.dumps(migrated, indent=2, ensure_ascii=False) + "\n"
        if rendered != path.read_text(encoding="utf-8"):
            pending.append((path, rendered))
    for path, rendered in pending:
        path.write_text(rendered, encoding="utf-8")
    print(
        json.dumps(
            {
                "migrated": len(pending),
                "maps": [str(p.relative_to(ROOT)) for p, _ in pending],
            },
            ensure_ascii=False,
        )
    )


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
    candidate = current_source_base()
    try:
        require_clean_candidate(candidate)
        modules = load("docs/modules/MODULES.json")["modules"]
        if not isinstance(modules, list) or not modules:
            raise ValueError("module registry must be nonempty")
        ids = [module["id"] for module in modules]
        if len(set(ids)) != len(ids):
            raise ValueError("duplicate module identity")
        lanes = lane_by_module()
    except (ValueError, OSError, subprocess.CalledProcessError) as exc:
        raise SystemExit(f"FAIL_HEPTA_IMPLEMENTATION_MAPS: {exc}") from exc
    failures = []
    source_bases = set()
    for module in modules:
        mid = module["id"]
        try:
            row = load(f"docs/modules/{mid}/IMPLEMENTATION_MAP.json")
            if (
                row.get("schema") != "hepta.module-implementation-map.v3"
                or row.get("schemaVersion") != 3
            ):
                raise ValueError("schema must be v3")
            if row.get("module") != mid or row.get("laneId") != lanes.get(mid):
                raise ValueError("module/lane identity")
            roots = [x["path"] for x in module["rootBindings"]]
            declared = row.get("declaredRoots", row.get("sourceRoot", []))
            if isinstance(declared, str):
                declared = [declared]
            if declared != roots:
                raise ValueError("declared roots")
            resolved = resolve_source_roots(ROOT, module)
            if row.get("resolvedRoots") != resolved:
                raise ValueError("resolved source roots")
            ops = row.get("operations")
            if not isinstance(ops, list) or not ops:
                raise ValueError("operations")
            if "sourceRootPresent" not in row or "productionImplementation" not in row:
                raise ValueError("status model")
            for op in ops:
                if not isinstance(op, dict) or not op.get("operation"):
                    raise ValueError("operation id")
                if "nativeSymbol" not in op or "sourcePath" not in op:
                    raise ValueError("canonical operation fields")
                source = op.get("sourcePath")
                if source is not None and not checked_source_path(ROOT, source).is_file():
                    raise ValueError(f"missing source: {source}")
            verify_source_identity(row, resolved, candidate)
            source_bases.add((row["sourceBase"]["commit"], row["sourceBase"]["tree"]))
            if not isinstance(row.get("claimBoundary") or row.get("completion"), dict):
                raise ValueError("claim boundary")
        except (
            ValueError, TypeError, KeyError, OSError, subprocess.CalledProcessError
        ) as exc:
            failures.append(f"{mid}: {exc}")
    try:
        require_clean_candidate(candidate)
    except (ValueError, subprocess.CalledProcessError) as exc:
        failures.append(str(exc))
    if failures:
        raise SystemExit("FAIL_HEPTA_IMPLEMENTATION_MAPS: " + "; ".join(failures))
    print(
        json.dumps(
            {
                "status": "PASS_HEPTA_IMPLEMENTATION_MAPS",
                "modules": len(modules),
                "maps": len(modules),
                "productionImplementationProved": False,
                "candidateSource": candidate,
                "sourceObservationCount": len(source_bases),
                "sourceBaseSemantics": "module_local_rebind_anchor_plus_no_mapped_source_drift",
                "validationScope": "source_navigation_and_declared_evidence_not_build_or_execution",
            },
            sort_keys=True,
        )
    )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["generate", "migrate", "verify"])
    parser.add_argument(
        "--module",
        action="append",
        dest="modules",
        help="rebind only this module (repeatable; migrate only)",
    )
    args = parser.parse_args()
    if args.modules is not None and args.command != "migrate":
        parser.error("--module applies only to migrate")
    if args.command == "migrate":
        migrate(args.modules)
    else:
        {"generate": generate, "verify": verify}[args.command]()


if __name__ == "__main__":
    main()
