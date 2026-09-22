#!/usr/bin/env python3
"""Generate and verify one implementation map for every registered module.

Maps are source-navigation evidence. They deliberately distinguish a native
entrypoint from a composed production caller; an entrypoint never grants
runtime, effect, acceptance, promotion, or release authority.

``sourceBase`` is historical provenance unless an explicit policy binds it. A map
that claims product composition additionally carries ``sourceObjects``: exact
Git object identities for its declared owner roots, native entrypoints and
product callers. This avoids the self-reference problem of requiring a JSON file
to contain the commit/tree hash of the commit that contains that same JSON file,
while still making mapped source/test/caller changes fail verification.
Unwitnessed legacy maps are explicitly navigation-only, not exact-source proof.
Use --require-current-source when every map must carry a current witness.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
from pathlib import Path

from hepta_module_source_roots import _pairs as unique_keys
from hepta_module_source_roots import _path as checked_source_path
from hepta_module_source_roots import resolve_source_roots

ROOT = Path(__file__).resolve().parents[1]


def current_source_base() -> dict[str, str]:
    """Return the immutable source identity used by generated maps."""
    return {"commit": git("rev-parse", "HEAD"), "tree": git("rev-parse", "HEAD^{tree}")}


def load(rel: str):
    return json.loads(
        (ROOT / rel).read_text(encoding="utf-8"), object_pairs_hook=unique_keys
    )


def git(*args: str) -> str:
    # Observe this checkout, never ambient Git redirection, replacement objects,
    # user configuration, network-backed object fetches or an fsmonitor hook.
    # Keep the explicit :(literal) pathspecs below: a global literal-pathspecs
    # flag would interpret their magic prefix as part of the filename.
    env = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
    env.update(
        GIT_CONFIG_NOSYSTEM="1",
        GIT_CONFIG_GLOBAL=os.devnull,
        GIT_NO_REPLACE_OBJECTS="1",
        GIT_NO_LAZY_FETCH="1",
        GIT_TERMINAL_PROMPT="0",
        GIT_OPTIONAL_LOCKS="0",
    )
    p = subprocess.run(
        ["git", "--no-replace-objects", "-c", "core.fsmonitor=false", *args],
        cwd=ROOT, env=env, text=True, capture_output=True, check=True,
    )
    return p.stdout.strip()


def checked_map_source(row: dict, path: str) -> None:
    """Reject escaped, symlinked and recursively self-inclusive source paths."""
    checked_source_path(ROOT, path)
    map_path = f"docs/modules/{row['module']}/IMPLEMENTATION_MAP.json"
    if map_path == path or map_path.startswith(path + "/"):
        raise ValueError("recursive implementation-map source binding")


def tracked_source_paths(row: dict) -> list[str]:
    """Bind declared/resolved roots and all explicitly mapped source/test paths.

    A root tree already covers its descendants. Test *names* are not file paths
    and are not mistaken for proof that the named tests actually executed.
    """
    paths: set[str] = set()

    def add(path):
        checked_map_source(row, path)
        paths.add(path)

    def collect(value, *, test_names=False):
        if isinstance(value, dict):
            for key, child in value.items():
                if key in {"path", "sourcePath", "testPath"} and child is not None:
                    add(child)
                elif isinstance(child, (dict, list)):
                    collect(child, test_names=key == "tests")
        elif isinstance(value, list):
            for child in value:
                if test_names and isinstance(child, str) and "/" in child:
                    add(child.split("::", 1)[0])
                else:
                    collect(child, test_names=test_names)

    declared = row.get("declaredRoots", row.get("sourceRoot", []))
    if isinstance(declared, str):
        declared = [declared]
    for field in (declared, row.get("resolvedRoots", [])):
        if not isinstance(field, list):
            raise ValueError("source roots must be lists")
        for path in field:
            add(path)
    for field in ("operations", "productCallers", "tests", "delegatedCallees"):
        collect(row.get(field, []), test_names=field == "tests")
    return sorted(paths)


def current_source_objects(row: dict) -> list[dict[str, str]]:
    """Bind mapped paths to Git, not to a recursively committed candidate SHA."""
    return [
        {"path": path, "object": git("rev-parse", "--verify", f"HEAD:{path}")}
        for path in tracked_source_paths(row)
    ]


def verify_source_identity(row: dict) -> bool:
    """Verify an explicit witness; legacy provenance alone returns False.

    This verifies only the declared source-navigation surface. It is not a
    complete build-input closure, symbol/API completeness, test result or grant.
    CI must bind its toolchain, build inputs and execution results separately.
    """
    def identity(value):
        if not isinstance(value, dict) or any(
            not isinstance(value.get(key), str)
            or re.fullmatch(r"[0-9a-f]{40}", value[key]) is None
            for key in ("commit", "tree")
        ):
            raise ValueError("invalid source commit/tree identity")
        return {key: value[key] for key in ("commit", "tree")}

    def require_clean(paths):
        specs = [f":(literal){path}" for path in paths]
        # These index flags can hide worktree edits from diff/status. Reject
        # them within witnessed roots rather than mutating the caller's index.
        for entry in git("ls-files", "-v", "-z", "--", *specs).split("\0"):
            if entry and (entry[0] == "S" or entry[0].islower()):
                raise ValueError("mapped source has an opaque Git index flag")
        for extra in ([], ["--cached"]):
            if git(
                "diff", "--no-ext-diff", "--no-textconv", "--name-only", *extra,
                "HEAD", "--", *specs,
            ):
                raise ValueError("mapped source differs from tested HEAD")
        if git("ls-files", "--others", "--exclude-standard", "--", *specs):
            raise ValueError("untracked mapped source is not bound to HEAD")

    def covered(path, observations):
        return any(path == root or path.startswith(root + "/") for root in observations)

    baseline = identity(row.get("sourceBase"))
    policy = row.get("sourceIdentityPolicy", "legacy_shared_batch")
    if policy not in {
        "legacy_shared_batch", "candidate_or_exact_observation_v1", "source_objects_v1"
    }:
        raise ValueError("unknown source identity policy")
    required = tracked_source_paths(row)
    objects = row.get("sourceObjects")
    observed = row.get("observedAtHead")
    witnessed = False
    if objects is not None:
        if not isinstance(objects, list) or not objects or not required:
            raise ValueError("source objects require a nonempty mapped source set")
        actual = {item["path"]: item["object"] for item in current_source_objects(row)}
        seen = set()
        for item in objects:
            if not isinstance(item, dict) or set(item) != {"path", "object"}:
                raise ValueError("invalid source object record")
            path, digest = item["path"], item["object"]
            checked_map_source(row, path)
            if (
                path in seen or not isinstance(digest, str)
                or re.fullmatch(r"[0-9a-f]{40}", digest) is None
            ):
                raise ValueError("duplicate or invalid source object")
            seen.add(path)
            expected = actual.get(path) or git("rev-parse", "--verify", f"HEAD:{path}")
            if digest != expected:
                raise ValueError(f"stale source object: {path}")
        if not all(covered(path, seen) for path in required):
            raise ValueError("source objects omit mapped source/test/caller paths")
        require_clean(sorted(seen | set(required)))
        witnessed = True
    if observed is not None:
        observed = identity(observed)
        commit = observed["commit"]
        if (
            git("cat-file", "-t", commit) != "commit"
            or git("rev-parse", f"{commit}^{{tree}}") != observed["tree"]
        ):
            raise ValueError("observed commit/tree mismatch")
        git("merge-base", "--is-ancestor", commit, "HEAD")
        paths = row.get("observedSourcePaths", required)
        if not isinstance(paths, list) or not paths:
            raise ValueError("observed source paths must be a nonempty list")
        for path in paths:
            checked_map_source(row, path)
            git("rev-parse", "--verify", f"{commit}:{path}")
            git("rev-parse", "--verify", f"HEAD:{path}")
        if not all(covered(path, paths) for path in required):
            raise ValueError("observation omits mapped source/test/caller paths")
        specs = [f":(literal){path}" for path in paths]
        if git(
            "diff", "--no-ext-diff", "--no-textconv", "--name-only",
            commit, "HEAD", "--", *specs,
        ):
            raise ValueError("source drift since exact observation")
        require_clean(paths)
        witnessed = True
    if policy == "candidate_or_exact_observation_v1":
        candidate = current_source_base()
        if baseline == candidate:
            if not required:
                raise ValueError("candidate has no mapped source")
            current_source_objects(row)
            require_clean(required)
            witnessed = True
        elif baseline != observed:
            raise ValueError("source base is neither candidate nor exact observation")
    elif policy == "source_objects_v1" and objects is None:
        raise ValueError("source-object policy requires exact source objects")
    return witnessed


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
            "nativeSourceMappingComplete": False,
            "listedEntrypointsPresent": all(
                bool(op["sourcePathExists"] and op["nativeSymbol"]) for op in operations
            ),
            "sourceRootPresent": all((ROOT / x).exists() for x in roots),
            "productionImplementation": False,
            "productExecutionProved": False,
            "independentAcceptance": False,
            "activation": False,
            "release": False,
        },
    }



def validate_claim_booleans(row: dict) -> None:
    """Never turn strings, integers or containers into positive evidence claims."""
    fields = {
        "sourceRootPresent", "productionImplementation", "nativeSourceMappingComplete",
        "listedEntrypointsPresent", "productExecutionProved", "independentAcceptance",
        "activation", "release", "implemented", "composed", "qualified",
    }
    records = [("map", row)]
    for key in ("claimBoundary", "completion", "status"):
        if key in row:
            if not isinstance(row[key], dict):
                raise ValueError(f"{key} must be an object")
            records.append((key, row[key]))
    for label, record in records:
        for key in fields.intersection(record):
            if type(record[key]) is not bool:
                raise ValueError(f"{label}.{key} must be boolean")


def selected_modules(module_ids: list[str] | None = None) -> list[dict]:
    """Keep the default global; explicit local work cannot silently select nothing."""
    modules = load("docs/modules/MODULES.json")["modules"]
    if not isinstance(modules, list) or not modules:
        raise ValueError("module registry must be a nonempty list")
    seen = set()
    for module in modules:
        mid = module.get("id") if isinstance(module, dict) else None
        if not isinstance(mid, str) or not mid or "/" in mid or "\\" in mid:
            raise ValueError("invalid module identity")
        # Do not allow module identities to escape their canonical directory.
        if mid in {".", ".."}:
            raise ValueError("invalid module identity")
        if mid in seen:
            raise ValueError(f"duplicate module identity: {mid}")
        seen.add(mid)
    if module_ids is None:
        return modules
    if not isinstance(module_ids, list) or not module_ids:
        raise ValueError("empty module selection")
    if any(not isinstance(mid, str) for mid in module_ids):
        raise ValueError("invalid module selection")
    requested = set(module_ids)
    unknown = requested - seen
    if unknown:
        raise ValueError("unknown module: " + ", ".join(sorted(unknown)))
    return [module for module in modules if module["id"] in requested]


def migrate_map(row: dict, module: dict, lanes: dict, source_base: dict) -> dict:
    """Upgrade legacy v1/v2 maps without discarding implementation evidence.

    v1 used ``sourceRoot`` and canonical operation fields directly; v2 wrapped
    the native anchor in ``ownerEntrypoint`` and called it ``designOperation``.
    v3 keeps every legacy field for compatibility while adding one stable
    operation vocabulary and top-level status/claim fields. Source witnesses
    are preserved, never refreshed: a schema migration is not a new execution.
    """
    validate_claim_booleans(row)
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
        "nativeSourceMappingComplete": (
            boundary.get("nativeSourceMappingComplete") is True
        ),
        "listedEntrypointsPresent": all(
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
    # ``sourceRoot`` is a v1 spelling. Retain it as a compatibility alias so
    # downstream readers can migrate independently; v3 readers use roots.
    migrated["sourceRoot"] = declared
    # Keep sourceObjects, observedAtHead and their full input set unchanged.
    # Rehashing here would pair newly edited source with old execution claims,
    # and could silently discard additional owner-declared evidence inputs.
    # Verification must continue to reject an obsolete witness after migration.
    return migrated


def migrate(module_ids: list[str] | None = None):
    modules = selected_modules(module_ids)
    lanes = lane_by_module()
    source_base = current_source_base()
    updates = []
    # Validate and render every selected map before changing any file. This
    # prevents a bad later map from leaving a partly normalized working tree.
    for module in modules:
        mid = module["id"]
        path = checked_source_path(ROOT, f"docs/modules/{mid}/IMPLEMENTATION_MAP.json")
        if not path.is_file():
            raise ValueError(f"{mid}: missing map; use generate first")
        text = path.read_text(encoding="utf-8")
        row = json.loads(text, object_pairs_hook=unique_keys)
        if not isinstance(row, dict) or row.get("module", mid) != mid:
            raise ValueError(f"{mid}: map identity mismatch")
        migrated = migrate_map(row, module, lanes, source_base)
        rendered = json.dumps(migrated, indent=2, ensure_ascii=False) + "\n"
        if rendered != text:
            updates.append((path, rendered))
    for path, rendered in updates:
        path.write_text(rendered, encoding="utf-8")
    print(json.dumps({
        "migrated": len(updates),
        "maps": [str(path.relative_to(ROOT)) for path, _ in updates],
    }, ensure_ascii=False))


def generate(module_ids: list[str] | None = None):
    modules = selected_modules(module_ids)
    lanes = lane_by_module()
    source_base = current_source_base()
    updates = []
    for module in modules:
        path = checked_source_path(
            ROOT, f"docs/modules/{module['id']}/IMPLEMENTATION_MAP.json"
        )
        if path.exists():
            continue
        value = map_for(module, source_base, lanes)
        updates.append((path, json.dumps(value, indent=2, ensure_ascii=False) + "\n"))
    for path, rendered in updates:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(rendered, encoding="utf-8")
    print(json.dumps({
        "generated": len(updates),
        "maps": [str(path.relative_to(ROOT)) for path, _ in updates],
    }, ensure_ascii=False))


def verify(
    require_current_source: bool = False, *, module_ids: list[str] | None = None
):
    modules = selected_modules(module_ids)
    lanes = lane_by_module()
    failures = []
    witnessed_modules = []
    historical_only = []
    for module in modules:
        mid = module["id"]
        path = ROOT / f"docs/modules/{mid}/IMPLEMENTATION_MAP.json"
        if not path.is_file():
            failures.append(f"{mid}: missing map")
            continue
        try:
            row = json.loads(
                path.read_text(encoding="utf-8"), object_pairs_hook=unique_keys
            )
            if not isinstance(row, dict):
                raise ValueError("map must be an object")
            validate_claim_booleans(row)
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
            if not isinstance(op, dict):
                failures.append(f"{mid}: invalid operation record")
                continue
            if not op.get("operation"):
                failures.append(f"{mid}: operation id")
            if "nativeSymbol" not in op or "sourcePath" not in op:
                failures.append(f"{mid}: canonical operation fields")
            source = op.get("sourcePath")
            if source is not None:
                try:
                    if not checked_source_path(ROOT, source).is_file():
                        failures.append(f"{mid}: missing source {source}")
                except ValueError as exc:
                    failures.append(f"{mid}: invalid source: {exc}")
        boundary = row.get("claimBoundary") or row.get("completion")
        if not isinstance(boundary, dict):
            failures.append(f"{mid}: claim boundary")

        status = row.get("status")
        if status is not None:
            if not isinstance(status, dict) or any(
                not isinstance(status.get(field), bool)
                for field in ("implemented", "composed", "qualified")
            ):
                failures.append(f"{mid}: invalid implemented/composed/qualified status")
            elif status["composed"] != (row.get("productCallerState") != "not_composed"):
                failures.append(f"{mid}: composition status disagreement")

        composed = row.get("productCallerState") != "not_composed"
        if composed:
            callers = row.get("productCallers")
            if not isinstance(callers, list) or not callers:
                failures.append(f"{mid}: composed map requires product callers")
            else:
                for caller in callers:
                    try:
                        if not isinstance(caller, dict) or not checked_source_path(
                            ROOT, caller.get("sourcePath")
                        ).is_file():
                            raise ValueError("product caller must name a source file")
                    except ValueError as exc:
                        failures.append(f"{mid}: invalid product caller: {exc}")
        try:
            witnessed = verify_source_identity(row)
        except (
            ValueError, TypeError, KeyError, OSError, subprocess.CalledProcessError
        ) as exc:
            failures.append(f"{mid}: source identity: {exc}")
            witnessed = False
        if witnessed:
            witnessed_modules.append(mid)
        else:
            historical_only.append(mid)
        claims_execution = any(
            isinstance(value, dict) and any(value.get(key) is True for key in (
                "productionImplementation", "productExecutionProved", "qualified",
                "composed", "activation", "release",
            ))
            for value in (row, boundary, status)
        )
        if (composed or claims_execution or require_current_source) and not witnessed:
            failures.append(
                f"{mid}: current source witness required; historical sourceBase is not proof"
            )

    if failures:
        raise SystemExit("FAIL_HEPTA_IMPLEMENTATION_MAPS: " + "; ".join(failures))
    print(
        json.dumps(
            {
                "status": "PASS_HEPTA_IMPLEMENTATION_MAPS",
                "modules": len(modules),
                "maps": len(modules),
                "moduleSelection": "all_registered" if module_ids is None else "explicit",
                "selectedModules": [module["id"] for module in modules],
                "productionImplementationProved": False,
                "validationScope": "navigation_and_explicit_source_witnesses_not_execution",
                "candidate": current_source_base(),
                "sourceWitnessedModules": witnessed_modules,
                "historicalOnlyModules": historical_only,
            },
            sort_keys=True,
        )
    )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["generate", "migrate", "verify"])
    parser.add_argument(
        "--module", dest="module_ids", action="append", metavar="MODULE_ID",
        help="limit to named registered modules; repeatable; default checks all modules",
    )
    parser.add_argument(
        "--require-current-source", action="store_true",
        help="reject navigation-only maps when an exact-source claim is required",
    )
    args = parser.parse_args()
    try:
        if args.command == "verify":
            verify(
                require_current_source=args.require_current_source,
                module_ids=args.module_ids,
            )
        else:
            if args.require_current_source:
                parser.error("--require-current-source applies only to verify")
            {"generate": generate, "migrate": migrate}[args.command](
                module_ids=args.module_ids
            )
    except (ValueError, KeyError, OSError, subprocess.CalledProcessError) as exc:
        parser.exit(1, f"FAIL_HEPTA_IMPLEMENTATION_MAPS: {exc}\n")


if __name__ == "__main__":
    main()
