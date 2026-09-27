#!/usr/bin/env python3
"""Generate and verify one implementation map for every registered module.

Maps are source-navigation evidence. They deliberately distinguish a native
entrypoint from a composed production caller; an entrypoint never grants
runtime, effect, acceptance, promotion, or release authority.

Maps retain module-local navigation anchors and exact source observations.
Composed maps may additionally pin the tree/blob objects of their owners and
product callers; migration refreshes these objects without granting execution.
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
        checked_source_path(ROOT, rel).read_text(encoding="utf-8"),
        object_pairs_hook=unique_keys,
    )


def git(*args: str, input_text: str | None = None) -> str:
    # Read the checked-out repository, not ambient GIT_DIR, replacement objects,
    # user aliases, network-backed promisor objects or external diff drivers.
    env = {
        key: value for key, value in os.environ.items() if not key.startswith("GIT_")
    }
    env.update(
        GIT_CONFIG_NOSYSTEM="1",
        GIT_CONFIG_GLOBAL=os.devnull,
        GIT_NO_REPLACE_OBJECTS="1",
        GIT_NO_LAZY_FETCH="1",
        GIT_TERMINAL_PROMPT="0",
        GIT_OPTIONAL_LOCKS="0",
    )
    p = subprocess.run(
        ["git", "--literal-pathspecs", "-c", "core.fsmonitor=false", *args],
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
        input=input_text,
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
    guide = row.get("technicalGuide")
    if guide is not None:
        if not isinstance(guide, str) or not guide:
            raise ValueError("invalid technical guide evidence path")
        paths.add(guide)
    for caller in row.get("productCallers", []):
        if not isinstance(caller, dict):
            raise ValueError("product caller evidence requires a typed binding")
        for field in ("sourcePath", "path"):
            source = caller.get(field)
            if source is not None:
                if not isinstance(source, str) or not source:
                    raise ValueError("invalid product caller evidence path")
                paths.add(source)
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
                if isinstance(entry, dict):
                    path = entry.get("path", entry.get("sourcePath"))
                    if (
                        "path" in entry
                        and "sourcePath" in entry
                        and entry["path"] != entry["sourcePath"]
                    ):
                        raise ValueError(f"{key} has conflicting evidence paths")
                else:
                    path = entry
                if not isinstance(path, str) or not path:
                    raise ValueError(f"{key} evidence requires an explicit source path")
                if key == "tests" and ".rs::" in path:
                    source, identity = path.split(".rs::", 1)
                    path = source + ".rs"
                    if (
                        re.fullmatch(
                            r"[A-Za-z_][A-Za-z0-9_]*(?:::[A-Za-z_][A-Za-z0-9_]*)*",
                            identity,
                        )
                        is None
                    ):
                        raise ValueError("invalid Rust test identity")
                    local = checked_source_path(ROOT, path)
                    leaf = identity.rsplit("::", 1)[-1]
                    if (
                        not local.is_file()
                        or re.search(
                            rf"\bfn\s+{re.escape(leaf)}\s*\(",
                            local.read_text(encoding="utf-8"),
                        )
                        is None
                    ):
                        raise ValueError(
                            "Rust test identity does not name a source function"
                        )
                paths.add(path)
    for path in paths:
        local = checked_source_path(ROOT, path)
        if not local.exists():
            raise ValueError(f"missing mapped source/evidence: {path}")
    return sorted(paths)


class SourceDrift(ValueError):
    """Valid historical provenance that needs an explicit source rebind."""


def require_tracked_paths(commit: str, paths: list[str], *, historical=False) -> None:
    """Batch ordinary object queries; retain exact handling of newline paths.

    No tree inventory is scanned and no persistent cache can survive a checkout
    change. The batch format returns only types, never path names to parse.
    Missing historical evidence is drift; missing candidate evidence is invalid.
    """
    ordinary = [path for path in paths if "\n" not in path and "\r" not in path]
    unusual = [path for path in paths if "\n" in path or "\r" in path]
    if ordinary:
        queries = [f"{commit}:{path}" for path in ordinary]
        types = git(
            "cat-file",
            "--batch-check=%(objecttype)",
            input_text="\n".join(queries) + "\n",
        ).splitlines()
        if len(types) != len(queries):
            raise ValueError("ambiguous Git object query response")
        for path, query, kind in zip(ordinary, queries, types):
            if kind in {"blob", "tree"}:
                continue
            if historical and kind == query + " missing":
                raise SourceDrift(
                    f"source/evidence absent at historical anchor: {path}"
                )
            raise ValueError(f"untracked or invalid source/evidence: {path}")
    for path in unusual:
        try:
            kind = git("cat-file", "-t", f"{commit}:{path}")
        except subprocess.CalledProcessError as exc:
            if historical:
                raise SourceDrift(
                    f"source/evidence absent at historical anchor: {path!r}"
                ) from exc
            raise ValueError(f"untracked source/evidence: {path!r}") from exc
        if kind not in {"blob", "tree"}:
            raise ValueError(f"invalid source/evidence: {path!r}")


def verify_source_identity(
    row: dict, roots: list[str], candidate: dict[str, str], *, check_checkout=True
) -> list[str]:
    policy = row.get("sourceIdentityPolicy", "legacy_shared_batch")
    if policy not in {"legacy_shared_batch", "candidate_or_exact_observation_v1"}:
        raise ValueError(f"unknown source identity policy: {policy}")
    source = checked_identity(row.get("sourceBase"), candidate)
    mapping_mode = row.get("mappingSourceIdentityMode", "path_only")
    if mapping_mode not in {"path_only", "exact_blob"}:
        raise ValueError(f"unknown mapping source identity mode: {mapping_mode}")
    paths = evidence_paths(row, roots)
    # In exact-blob mode ``sourceBase`` is immutable integration provenance,
    # not the current-source observation. Currentness is proved independently
    # by every mapped HEAD blob plus ``observedAtHead`` over the complete
    # evidence/root set. Path-only maps retain the historical no-drift anchor.
    observations = [] if mapping_mode == "exact_blob" else [(source, paths)]
    if "observedAtHead" in row:
        observed = checked_identity(row["observedAtHead"], candidate)
        observed_paths = row.get("observedSourcePaths", roots)
        if (
            not isinstance(observed_paths, list)
            or not observed_paths
            or any(not isinstance(path, str) for path in observed_paths)
        ):
            raise ValueError("invalid observed source paths")
        if not set(roots).issubset(observed_paths):
            raise ValueError("observed source paths omit resolved roots")
        if policy == "candidate_or_exact_observation_v1" and any(
            source_root == "codex-rs" or source_root.startswith("codex-rs/")
            for source_root in roots
        ):
            required_workspace_inputs = {"codex-rs/Cargo.toml", "codex-rs/Cargo.lock"}
            missing_workspace_inputs = sorted(
                required_workspace_inputs.difference(observed_paths)
            )
            if missing_workspace_inputs:
                raise ValueError(
                    "observed source paths omit Rust workspace build inputs "
                    + ", ".join(missing_workspace_inputs)
                )
        observations.append((observed, sorted(set(paths + observed_paths))))
    else:
        observed = None
        if mapping_mode == "exact_blob":
            raise ValueError(
                "exact blob provenance requires an explicit current source observation"
            )
    if (
        policy == "candidate_or_exact_observation_v1"
        and mapping_mode != "exact_blob"
        and source not in (candidate, observed)
    ):
        raise ValueError("source base is neither candidate nor exact observed source")
    checked_paths = sorted({path for _, items in observations for path in items})
    for path in checked_paths:
        if not checked_source_path(ROOT, path).exists():
            raise ValueError(f"missing observed source/evidence: {path}")
    if check_checkout:
        require_clean_candidate(candidate, checked_paths)
    # Validate the candidate first: a missing path at both ends is not a rebind.
    require_tracked_paths(candidate["commit"], checked_paths)
    for identity, observed_paths in observations:
        if identity == candidate:
            continue
        require_tracked_paths(identity["commit"], observed_paths, historical=True)
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
                raise SourceDrift(
                    "mapped source/evidence changed after source observation: "
                    + changed
                )
    if check_checkout:
        require_clean_candidate(candidate, checked_paths)
    return checked_paths


def tracked_source_paths(row: dict) -> list[str]:
    """Use the canonical evidence inventory and retain explicit legacy witnesses.

    Source objects are an opt-in stronger binding, not permission to discard
    tests, delegates or caller paths when normalizing the old blobSha spelling.
    The map itself is excluded to avoid a cryptographic self-reference.
    """
    roots = row.get(
        "resolvedRoots", row.get("declaredRoots", row.get("sourceRoot", []))
    )
    if isinstance(roots, str):
        roots = [roots]
    paths = set(evidence_paths(row, roots))
    for entry in row.get("sourceObjects", []):
        if not isinstance(entry, dict) or not isinstance(entry.get("path"), str):
            raise ValueError("invalid explicit source object path")
        paths.add(entry["path"])
    own_map = f"docs/modules/{row.get('module')}/IMPLEMENTATION_MAP.json"
    if own_map in paths:
        raise ValueError("source object cannot bind its own implementation map")
    for path in paths:
        checked_source_path(ROOT, path)
    return sorted(paths)


def current_source_objects(row: dict) -> list[dict[str, str]]:
    """Bind each relevant path to the tree/blob present at the tested HEAD."""
    return [
        {"path": path, "object": git("rev-parse", f"HEAD:{path}")}
        for path in tracked_source_paths(row)
    ]


def validate_path_blob_manifest(row: dict, mid: str, failures: list[str]) -> None:
    """Validate a self-reference-safe exact source manifest against HEAD.

    Tracked implementation maps cannot contain their own future HEAD/tree
    identity without a fixed-point problem. This policy freezes mapped source
    files to Git blob identities and verifies the candidate checkout directly.
    """
    evidence = row.get("exactSourceEvidence")
    if (
        not isinstance(evidence, dict)
        or evidence.get("kind") != "path_blob_manifest_v1"
    ):
        failures.append(f"{mid}: exact source manifest")
        return
    entries = evidence.get("entries")
    if not isinstance(entries, list) or not entries:
        failures.append(f"{mid}: exact source manifest entries")
        return
    by_path: dict[str, str] = {}
    root = ROOT.resolve()
    for entry in entries:
        if not isinstance(entry, dict):
            failures.append(f"{mid}: exact source manifest entry")
            return
        path = entry.get("path")
        blob = entry.get("blobSha")
        if not (
            isinstance(path, str)
            and path
            and isinstance(blob, str)
            and bool(re.fullmatch(r"[0-9a-f]{40}", blob))
        ):
            failures.append(f"{mid}: exact source manifest entry")
            return
        if path in by_path:
            failures.append(f"{mid}: duplicate exact source path {path}")
            return
        candidate = checked_source_path(ROOT, path)
        try:
            candidate.relative_to(root)
        except ValueError:
            failures.append(f"{mid}: exact source path escape {path}")
            return
        if not candidate.is_file():
            failures.append(f"{mid}: missing exact source path {path}")
            return
        try:
            actual = git("rev-parse", f"HEAD:{path}")
        except subprocess.CalledProcessError:
            failures.append(f"{mid}: cannot resolve exact source path {path}")
            return
        if actual != blob:
            failures.append(f"{mid}: exact source blob drift {path}")
        by_path[path] = blob

    mapped_paths = {
        op.get("sourcePath")
        for op in row.get("operations", [])
        if isinstance(op, dict) and op.get("sourcePath")
    }
    missing = sorted(mapped_paths - set(by_path))
    if missing:
        failures.append(f"{mid}: exact source manifest omits mapped paths {missing}")


def _ephemeral_untracked_artifact(path: str) -> bool:
    """Ignore interpreter cache bytes without ignoring hidden source files."""
    parts = Path(path).parts
    return "__pycache__" in parts and path.endswith((".pyc", ".pyo"))


def require_clean_candidate(
    candidate: dict[str, str], paths: list[str] | None = None
) -> None:
    # This is a quiescent-checkout verifier, not a concurrent build attestor.
    # Untracked CI reports outside mapped roots are not source mutations.
    # status/diff trust index flags: assume-unchanged and skip-worktree can
    # conceal changed source AND the registries/maps that select that source.
    # Reject them before reading those inputs, without clearing user flags or
    # refreshing the index. NUL records keep unusual filenames unambiguous.
    hidden = [
        record[2:]
        for record in git("ls-files", "-v", "-z").split("\0")
        if record and (record[0] == "S" or record[0].islower())
    ]
    if hidden:
        raise ValueError(
            "candidate index hides tracked paths (assume-unchanged/skip-worktree): "
            + ", ".join(repr(path) for path in hidden[:5])
            + "; verify a full checkout without hidden index entries"
        )
    if current_source_base() != candidate or git(
        "status", "--porcelain=v1", "--untracked-files=no"
    ):
        raise ValueError(
            "candidate checkout changed or is dirty; commit source before verification"
        )
    if paths:
        dirty = git("status", "--porcelain=v1", "--untracked-files=all", "--", *paths)
        untracked = [
            path
            for path in git("ls-files", "--others", "-z", "--", *paths).split("\0")
            if path and not _ephemeral_untracked_artifact(path)
        ]
        if dirty or untracked:
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


EXECUTION_CLAIMS = frozenset(
    {
        "productionImplementation",
        "productExecutionProved",
        "independentAcceptance",
        "activation",
        "release",
    }
)
BOOLEAN_CLAIMS = EXECUTION_CLAIMS | {
    "nativeSourceMappingComplete",
    "implementedOperationMappingComplete",
    "ownedTargetProtocolSourceComplete",
    "sourceRootPresent",
}


def validate_claim_types(row: dict) -> bool:
    """Validate declared facts without coercing or issuing execution evidence."""
    if not isinstance(row, dict):
        raise ValueError("implementation map must be an object")
    claims = [row]
    for name in ("claimBoundary", "completion"):
        if name in row:
            value = row[name]
            if not isinstance(value, dict):
                raise ValueError(f"{name} must be an object")
            claims.append(value)
    for claim in claims:
        for name in BOOLEAN_CLAIMS.intersection(claim):
            if type(claim[name]) is not bool:
                raise ValueError(f"{name} must be boolean")
    return any(claim.get(name) is True for claim in claims for name in EXECUTION_CLAIMS)


def canonical_product_callers(callers: list) -> list[dict]:
    """Normalize legacy navigation spellings without inventing composition."""
    if not isinstance(callers, list):
        raise ValueError("product callers must be a list")
    result = []
    for caller in callers:
        if not isinstance(caller, dict):
            raise ValueError("product caller must be a typed binding")
        normalized = dict(caller)
        for canonical, legacy in (("sourcePath", "path"), ("nativeSymbol", "symbol")):
            if legacy in normalized:
                if (
                    canonical in normalized
                    and normalized[canonical] != normalized[legacy]
                ):
                    raise ValueError("conflicting product caller " + canonical)
                normalized[canonical] = normalized.pop(legacy)
        source = normalized.get("sourcePath")
        if (
            not isinstance(source, str)
            or not checked_source_path(ROOT, source).is_file()
        ):
            raise ValueError("missing product caller source")
        if "blobSha" in normalized:
            normalized["blobSha"] = git("rev-parse", f"HEAD:{source}")
        result.append(normalized)
    return result


def migrate_map(row: dict, module: dict, lanes: dict, source_base: dict) -> dict:
    """Upgrade legacy v1/v2 maps without discarding implementation evidence.

    v1 used ``sourceRoot`` and canonical operation fields directly; v2 wrapped
    the native anchor in ``ownerEntrypoint`` and called it ``designOperation``.
    v3 keeps every legacy field for compatibility while adding one stable
    operation vocabulary and top-level status/claim fields.
    """
    if validate_claim_types(row):
        # Rebinding navigation cannot transfer old executable evidence to new code.
        verify_source_identity(
            row, resolve_source_roots(ROOT, module), current_source_base()
        )
    roots = [x["path"] for x in module["rootBindings"]]
    declared = row.get("declaredRoots", row.get("sourceRoot", roots))
    if isinstance(declared, str):
        declared = [declared]
    # Keep a truthful root declaration even when an old hand-written map used
    # an obsolete spelling; the module registry is authoritative.
    declared = roots
    operations = []
    for original in row.get("operations", []):
        if not isinstance(original, dict):
            raise ValueError("invalid operation record")
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
        if row.get("mappingSourceIdentityMode") == "exact_blob" and source:
            op["sourceBlob"] = git("rev-parse", f"HEAD:{source}")
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
    if "productCallers" in migrated:
        migrated["productCallers"] = canonical_product_callers(
            migrated["productCallers"]
        )
    boundary = migrated.get("claimBoundary") or migrated.get("completion")
    if not isinstance(boundary, dict):
        boundary = {}
    implemented_mapping_complete = all(
        bool(op.get("sourcePathExists") and op.get("nativeSymbol")) for op in operations
    )
    migrated["claimBoundary"] = {
        **boundary,
        "implementedOperationMappingComplete": boundary.get(
            "implementedOperationMappingComplete", implemented_mapping_complete
        ),
        # Preserve a reviewed claim; migration must not manufacture one.
        "nativeSourceMappingComplete": boundary.get(
            "nativeSourceMappingComplete", False
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
    if (
        "observedAtHead" in migrated
        or migrated.get("sourceIdentityPolicy") == "candidate_or_exact_observation_v1"
        or migrated.get("mappingSourceIdentityMode") == "exact_blob"
    ):
        # A navigation-only migration must survive committing the map itself.
        # Without an explicit observation, a strong-policy sourceBase equal to
        # today's HEAD becomes invalid on the very next metadata-only commit.
        # Execution claims were verified against the old source above; this
        # generated observation grants no executable qualification.
        migrated["observedAtHead"] = {
            **migrated.get("observedAtHead", {}),
            **source_base,
        }
        observed_paths = set(migrated.get("observedSourcePaths", []))
        observed_paths.update(migrated["resolvedRoots"])
        if migrated.get(
            "sourceIdentityPolicy"
        ) == "candidate_or_exact_observation_v1" and any(
            root == "codex-rs" or root.startswith("codex-rs/")
            for root in migrated["resolvedRoots"]
        ):
            observed_paths.update({"codex-rs/Cargo.toml", "codex-rs/Cargo.lock"})
        migrated["observedSourcePaths"] = sorted(observed_paths)
    # ``sourceRoot`` is a v1 spelling.  Retain it as a compatibility alias so
    # downstream readers can migrate independently; v3 readers use roots.
    migrated["sourceRoot"] = declared
    if "sourceObjects" in row or migrated.get("productCallers"):
        # Named caller navigation must bind its exact source, tests and delegates.
        # Creating these Git objects is not evidence that the product executed.
        migrated["sourceObjects"] = current_source_objects(migrated)
    evidence = migrated.get("exactSourceEvidence")
    if isinstance(evidence, dict) and evidence.get("kind") == "path_blob_manifest_v1":
        evidence["entries"] = [
            {**entry, "blobSha": git("rev-parse", f"HEAD:{entry['path']}")}
            for entry in evidence.get("entries", [])
        ]
    return migrated


def migrate(selected_modules: list[str] | None = None):
    source_base = current_source_base()
    require_clean_candidate(source_base)
    modules = load("docs/modules/MODULES.json")["modules"]
    if not isinstance(modules, list) or not modules:
        raise ValueError("module registry must be nonempty")
    by_id = {m["id"]: m for m in modules}
    if len(by_id) != len(modules):
        raise ValueError("duplicate module identity")
    if selected_modules == []:
        raise ValueError("empty module selection")
    selected = set(by_id) if selected_modules is None else set(selected_modules)
    unknown = selected - set(by_id)
    if unknown:
        raise SystemExit("unknown modules: " + ", ".join(sorted(unknown)))
    lanes = lane_by_module()
    # Prepare and validate every selected map before writing any of them.
    # Invalid identities/evidence must not be silently laundered into HEAD.
    pending = []
    checked_paths: set[str] = set()
    for mid in sorted(selected):
        path = ROOT / f"docs/modules/{mid}/IMPLEMENTATION_MAP.json"
        if not path.is_file():
            raise SystemExit(f"{mid}: missing map")
        row = load(str(path.relative_to(ROOT)))
        if row.get("module", mid) != mid:
            raise SystemExit(f"{mid}: identity")
        anchor = checked_identity(row.get("sourceBase"), source_base)
        mapping_mode = row.get("mappingSourceIdentityMode", "path_only")
        migrated = migrate_map(row, by_id[mid], lanes, anchor)
        if "observedAtHead" in row:
            migrated["observedAtHead"] = row["observedAtHead"]
        resolved = migrated["resolvedRoots"]
        try:
            paths = verify_source_identity(
                migrated, resolved, source_base, check_checkout=False
            )
        except SourceDrift:
            if mapping_mode == "exact_blob":
                # Preserve immutable integration provenance. Rebind only the
                # explicit current-source observation and HEAD blob manifest.
                migrated["sourceBase"] = anchor
                migrated["observedAtHead"] = source_base
            else:
                migrated = migrate_map(row, by_id[mid], lanes, source_base)
            paths = verify_source_identity(
                migrated, resolved, source_base, check_checkout=False
            )
        checked_paths.update(paths)
        # Preserve original formatting and anchors when nothing changed. Even a
        # later prose commit must not trigger a global metadata refresh.
        if migrated != row:
            pending.append(
                (path, json.dumps(migrated, indent=2, ensure_ascii=False) + "\n")
            )
    require_clean_candidate(source_base, sorted(checked_paths))
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


def state_claims_binding(value: object) -> bool:
    return isinstance(value, str) and bool(value) and not value.startswith("not_")


def validate_closed_world_bindings(row: dict) -> None:
    """Check additional source markers without replacing exact blob identity."""
    for state_key, policy_key, bindings_key, path_key in (
        (
            "productCallerState",
            "productCallerBindingPolicy",
            "productCallerBindings",
            "callerPath",
        ),
        (
            "productionWriterState",
            "productionWriterBindingPolicy",
            "productionWriterBindings",
            "sourcePath",
        ),
    ):
        policy = row.get(policy_key)
        bindings = row.get(bindings_key, [])
        if policy not in (None, "closed_world"):
            raise ValueError(f"invalid {policy_key}")
        if not isinstance(bindings, list):
            raise ValueError(f"invalid {bindings_key}")
        if (
            policy == "closed_world"
            and state_claims_binding(row.get(state_key))
            and not bindings
        ):
            raise ValueError(f"{state_key} requires verified source bindings")
        for index, binding in enumerate(bindings):
            if not isinstance(binding, dict):
                raise ValueError(f"invalid {bindings_key}[{index}]")
            source, marker = binding.get(path_key), binding.get("mustContain")
            if not isinstance(source, str) or not isinstance(marker, str) or not marker:
                raise ValueError(f"invalid {bindings_key}[{index}] source/marker")
            path = checked_source_path(ROOT, source)
            if not path.is_file() or marker not in path.read_text(encoding="utf-8"):
                raise ValueError(
                    f"unresolved {bindings_key}[{index}] source binding: {source}"
                )


def validate_observed_source(
    row: dict, mid: str, resolved_roots: list[str], failures: list[str]
) -> None:
    """Compatibility report adapter over the sole strict identity verifier."""
    try:
        observation = dict(row)
        observation.setdefault("operations", [])
        verify_source_identity(observation, resolved_roots, current_source_base())
    except (
        ValueError,
        TypeError,
        KeyError,
        OSError,
        subprocess.CalledProcessError,
    ) as exc:
        failures.append(f"{mid}: {exc}")


def validate_operation_inventory(mid: str, ops: list[dict]) -> None:
    if mid != "learning.operator":
        return
    required = {
        "build_targets",
        "build_sensor_core",
        "evaluate_bellman_reference",
        "validate_applicability_certificate",
        "validate_applicability_with_signed_evidence_v2",
        "fit_tabular_operator",
        "fit_tabular_operator_strict_v2",
        "verify_tabular_operator_plan_v2",
        "fit_tabular_operator_verified_v2",
        "predict_tabular_operator",
        "encode_tabular_payload_v1",
        "load_pinned_tabular_operator_v1",
        "admit_operator_regularity",
        "admit_operator_regularity_with_signed_evidence_v2",
        "fit_transition_model",
        "verify_world_model_dataset_v2",
        "fit_transition_model_verified_v2",
        "predict_transition",
    }
    mapped = {op.get("operation") for op in ops if isinstance(op, dict)}
    missing = sorted(required - mapped)
    if missing:
        raise ValueError("public operation inventory incomplete: " + ", ".join(missing))


STATUS_BEGIN = "<!-- BEGIN GENERATED IMPLEMENTATION STATUS -->"
STATUS_END = "<!-- END GENERATED IMPLEMENTATION STATUS -->"


def plasticity_status_block(row: dict) -> str:
    lines = [
        STATUS_BEGIN,
        "## Generated implementation status",
        "",
        "This block is generated only from `IMPLEMENTATION_MAP.json`. Run",
        "`python3 scripts/hepta-implementation-maps.py sync-plasticity-status` after",
        "changing the map. Hand-written sections below explain semantics but do not",
        "override these machine status facts.",
        "",
        f"- Product caller: `{row['productCallerState']}`",
        f"- Production writer: `{row['productionWriterState']}`",
        f"- Production implementation: `{str(bool(row['productionImplementation'])).lower()}`",
        f"- Product execution proved: `{str(bool(row['claimBoundary']['productExecutionProved'])).lower()}`",
        f"- Independent acceptance: `{str(bool(row['claimBoundary']['independentAcceptance'])).lower()}`",
        f"- Activation: `{str(bool(row['claimBoundary']['activation'])).lower()}`",
        f"- Release: `{str(bool(row['claimBoundary']['release'])).lower()}`",
        "",
        "| Operation | State | Source | Tests |",
        "| --- | --- | --- | ---: |",
    ]
    for op in row["operations"]:
        lines.append(
            f"| `{op['operation']}` | `{op['state']}` | "
            f"`{op.get('sourcePath') or '-'}` | {len(op.get('tests') or [])} |"
        )
    lines.extend(["", "### Repository-controlled gaps", ""])
    lines.extend(f"- {gap}" for gap in row.get("repositoryControlledGaps", []))
    lines.extend(["", "### External evidence gates", ""])
    lines.extend(f"- {gate}" for gate in row.get("externalEvidenceGates", []))
    lines.extend(["", STATUS_END])
    return "\n".join(lines)


def plasticity_current_state_projection(row: dict) -> dict:
    return {
        "schema": "hepta.learning-plasticity-current-state.v1",
        "schemaVersion": 1,
        "module": row["module"],
        "generatedFrom": "docs/modules/learning.plasticity/IMPLEMENTATION_MAP.json",
        "sourceBase": row["sourceBase"],
        "current": {
            "sourceRootPresent": bool(row["sourceRootPresent"]),
            "productionImplementation": bool(row["productionImplementation"]),
            "productCallerState": row["productCallerState"],
            "productionWriterState": row["productionWriterState"],
            "claimBoundary": row["claimBoundary"],
        },
        "operations": [
            {
                "operation": op["operation"],
                "state": op["state"],
                "sourcePath": op.get("sourcePath"),
                "tests": op.get("tests") or [],
            }
            for op in row["operations"]
        ],
        "remainingToTarget": {
            "repositoryControlledGaps": row.get("repositoryControlledGaps", []),
            "externalEvidenceGates": row.get("externalEvidenceGates", []),
        },
    }


def sync_plasticity_status() -> None:
    map_path = ROOT / "docs/modules/learning.plasticity/IMPLEMENTATION_MAP.json"
    doc_path = ROOT / "docs/modules/learning.plasticity/CURRENT_IMPLEMENTATION.md"
    row = json.loads(map_path.read_text(encoding="utf-8"))
    expected = plasticity_status_block(row)
    text = doc_path.read_text(encoding="utf-8")
    pattern = re.compile(re.escape(STATUS_BEGIN) + r".*?" + re.escape(STATUS_END), re.S)
    if pattern.search(text):
        text = pattern.sub(expected, text, count=1)
    else:
        marker = "\n## Status matrix\n"
        if marker not in text:
            raise SystemExit(
                "learning.plasticity current implementation is missing Status matrix"
            )
        text = text.replace(marker, "\n" + expected + "\n" + marker, 1)
    doc_path.write_text(text, encoding="utf-8")
    (ROOT / "docs/modules/learning.plasticity/CURRENT_STATE.json").write_text(
        json.dumps(
            plasticity_current_state_projection(row),
            indent=2,
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )


def plasticity_status_matches() -> bool:
    row = load("docs/modules/learning.plasticity/IMPLEMENTATION_MAP.json")
    text = (
        ROOT / "docs/modules/learning.plasticity/CURRENT_IMPLEMENTATION.md"
    ).read_text(encoding="utf-8")
    expected = plasticity_status_block(row)
    pattern = re.compile(re.escape(STATUS_BEGIN) + r".*?" + re.escape(STATUS_END), re.S)
    match = pattern.search(text)
    if not (match and match.group(0) == expected):
        return False
    if not (ROOT / "docs/modules/learning.plasticity/CURRENT_STATE.json").is_file():
        return False
    try:
        current = json.loads(
            (ROOT / "docs/modules/learning.plasticity/CURRENT_STATE.json").read_text(
                encoding="utf-8"
            )
        )
    except Exception:
        return False
    return current == plasticity_current_state_projection(row)


def verify_plasticity_test_references(row: dict, failures: list[str]) -> None:
    for op in row.get("operations", []):
        tests = op.get("tests")
        if not isinstance(tests, list) or not tests:
            failures.append(
                f"learning.plasticity: {op.get('operation', '<unknown>')} has no focused test identity"
            )
            continue
        for test in tests:
            if not isinstance(test, str) or ".rs::" not in test:
                failures.append(f"learning.plasticity: invalid test identity {test!r}")
                continue
            source, test_path = test.split(".rs::", 1)
            source += ".rs"
            try:
                path = checked_source_path(ROOT, source)
            except ValueError as exc:
                failures.append(f"learning.plasticity: invalid test source {exc}")
                continue
            if not path.is_file():
                failures.append(f"learning.plasticity: missing test source {source}")
                continue
            leaf = test_path.rsplit("::", 1)[-1]
            source_text = path.read_text(encoding="utf-8")
            if re.search(rf"\bfn\s+{re.escape(leaf)}\s*\(", source_text) is None:
                failures.append(
                    f"learning.plasticity: test identity {test} does not name a function"
                )


def top_level_rust_source(text: str) -> str:
    """Mask comments/literals and nested items for the bounded source inventory.

    This is navigation, not compiler qualification. Unlike a raw pub-fn search,
    impl methods, test modules, doc strings and braces in literals cannot claim
    to be crate-root free-function exports.
    """
    output = list(text)
    i = depth = 0
    while i < len(text):
        end = None
        if text.startswith("//", i):
            end = text.find("\n", i)
            if end < 0:
                end = len(text)
        elif text.startswith("/*", i):
            end, nesting = i + 2, 1
            while end < len(text) and nesting:
                if text.startswith("/*", end):
                    nesting += 1
                    end += 2
                elif text.startswith("*/", end):
                    nesting -= 1
                    end += 2
                else:
                    end += 1
            if nesting:
                raise ValueError("unterminated Rust block comment")
        else:
            raw = re.match(r'(?:br|cr|r)(#{0,255})"', text[i:])
            if raw:
                closing = '"' + raw.group(1)
                close = text.find(closing, i + raw.end())
                if close < 0:
                    raise ValueError("unterminated Rust raw string")
                end = close + len(closing)
            elif text[i] == '"':
                end = i + 1
                while end < len(text):
                    if text[end] == "\\":
                        end += 2
                    elif text[end] == '"':
                        end += 1
                        break
                    else:
                        end += 1
            elif text[i] == "'":
                char = re.match(
                    r"'(?:\\(?:u\{[0-9A-Fa-f_]+\}|x[0-9A-Fa-f]{2}|.)|[^'\\\n])'",
                    text[i:],
                )
                if char:
                    end = i + char.end()
        if end is not None:
            output[i:end] = ["\n" if ch == "\n" else " " for ch in text[i:end]]
            i = end
            continue
        if text[i] == "{":
            depth += 1
        if depth:
            output[i] = "\n" if text[i] == "\n" else " "
        if text[i] == "}":
            depth -= 1
            if depth < 0:
                raise ValueError("unbalanced Rust item braces")
        i += 1
    if depth:
        raise ValueError("unbalanced Rust item braces")
    return "".join(output)


def public_rust_functions(root: str) -> set[str]:
    """Root public free functions and explicit single-name re-exports.

    The inventoried surface is source-level, including cfg-qualified exports;
    associated methods and private helpers are not independent operations.
    """
    src = checked_source_path(ROOT, root) / "src"
    lib = src / "lib.rs"
    if not lib.is_file():
        return set()
    text = top_level_rust_source(lib.read_text(encoding="utf-8"))
    declaration = r"\bpub\s+(?:(?:async|const|unsafe)\s+)*(?:extern\s+)?fn\s+([A-Za-z_][A-Za-z0-9_]*)\b"
    functions = set(re.findall(declaration, text))
    for module, name in re.findall(
        r"\bpub\s+use\s+([A-Za-z_][A-Za-z0-9_]*)::([A-Za-z_][A-Za-z0-9_]*)\s*;", text
    ):
        source = src / f"{module}.rs"
        if source.is_file() and name in re.findall(
            declaration, top_level_rust_source(source.read_text(encoding="utf-8"))
        ):
            functions.add(name)
    return functions


def verify(
    *,
    modules: list[str] | None = None,
    require_current_source: bool = True,
    expected_sha: str | None = None,
    expected_tree: str | None = None,
):
    """Verify current mapped bytes; the explicit flag remains a strict CLI alias.

    Exact-blob maps may retain an immutable provenance anchor only when their
    mapped HEAD blobs and explicit current-source observation both verify. No
    provenance record alone establishes currentness or execution qualification.
    """
    candidate = current_source_base()
    try:
        for value, label in (
            (expected_sha, "expected-sha"),
            (expected_tree, "expected-tree"),
        ):
            if value is not None and re.fullmatch(r"[0-9a-f]{40}", value) is None:
                raise ValueError(
                    f"--{label} must be an exact 40-character Git object id"
                )
        if expected_sha is not None and candidate["commit"] != expected_sha:
            raise ValueError(
                f"expected candidate SHA {expected_sha}, observed {candidate['commit']}"
            )
        if expected_tree is not None and candidate["tree"] != expected_tree:
            raise ValueError(
                f"expected candidate tree {expected_tree}, observed {candidate['tree']}"
            )
        require_clean_candidate(candidate)
        registered_modules = load("docs/modules/MODULES.json")["modules"]
        if not isinstance(registered_modules, list) or not registered_modules:
            raise ValueError("module registry must be nonempty")
        ids = [module["id"] for module in registered_modules]
        if len(set(ids)) != len(ids):
            raise ValueError("duplicate module identity")
        if modules is None:
            selected_modules = registered_modules
        else:
            if (
                not isinstance(modules, list)
                or not modules
                or any(
                    not isinstance(module_id, str) or not module_id
                    for module_id in modules
                )
            ):
                raise ValueError(
                    "module selection must be a nonempty list of module ids"
                )
            if len(set(modules)) != len(modules):
                raise ValueError("duplicate selected module identity")
            unknown = sorted(set(modules).difference(ids))
            if unknown:
                raise ValueError("unknown selected module: " + ", ".join(unknown))
            requested = set(modules)
            selected_modules = [
                module for module in registered_modules if module["id"] in requested
            ]
        lanes = lane_by_module()
    except (ValueError, OSError, subprocess.CalledProcessError) as exc:
        raise SystemExit(f"FAIL_HEPTA_IMPLEMENTATION_MAPS: {exc}") from exc
    failures = []
    source_bases = set()
    checked_paths: set[str] = set()
    candidate_bound_maps = 0
    exact_observed_fallback_maps = 0
    provenance_anchored_exact_blob_maps = 0
    for module in selected_modules:
        mid = module["id"]
        try:
            row = load(f"docs/modules/{mid}/IMPLEMENTATION_MAP.json")
            validate_claim_types(row)
            validate_closed_world_bindings(row)
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
            if (
                not isinstance(ops, list)
                or not ops
                or any(not isinstance(op, dict) for op in ops)
            ):
                raise ValueError("operations")
            if "sourceRootPresent" not in row or "productionImplementation" not in row:
                raise ValueError("status model")
            validate_operation_inventory(mid, ops)
            if row.get("closedWorldPublicFunctions") is True:
                exported = set()
                for root in resolved:
                    if (checked_source_path(ROOT, root) / "Cargo.toml").is_file():
                        exported.update(public_rust_functions(root))
                mapped = {
                    op.get("nativeSymbol")
                    for op in ops
                    if isinstance(op.get("nativeSymbol"), str)
                }
                if exported != mapped:
                    raise ValueError(
                        f"public function inventory differs: missing={sorted(exported - mapped)}, extra={sorted(mapped - exported)}"
                    )

            if mid == "learning.plasticity":
                verify_plasticity_test_references(row, failures)
                if not plasticity_status_matches():
                    raise ValueError(
                        "generated plasticity status differs from implementation map"
                    )
            mapping_mode = row.get("mappingSourceIdentityMode", "path_only")
            if mapping_mode not in {"path_only", "exact_blob"}:
                raise ValueError("mapping source identity mode")
            for op in ops:
                if not isinstance(op, dict) or not op.get("operation"):
                    raise ValueError("operation id")
                if "nativeSymbol" not in op or "sourcePath" not in op:
                    raise ValueError("canonical operation fields")
                source = op.get("sourcePath")
                if (
                    source is not None
                    and not checked_source_path(ROOT, source).is_file()
                ):
                    raise ValueError(f"missing source: {source}")
                if mapping_mode == "exact_blob":
                    source_blob = op.get("sourceBlob")
                    if (
                        not source
                        or not isinstance(source_blob, str)
                        or re.fullmatch(r"[0-9a-f]{40}", source_blob) is None
                    ):
                        raise ValueError(
                            f"invalid exact source blob: {op['operation']}"
                        )
                    if (
                        git("rev-parse", f"{candidate['commit']}:{source}")
                        != source_blob
                    ):
                        raise ValueError(f"source blob drift: {op['operation']}")
            checked_paths.update(
                verify_source_identity(row, resolved, candidate, check_checkout=False)
            )
            source_bases.add((row["sourceBase"]["commit"], row["sourceBase"]["tree"]))
            if row["sourceBase"] == candidate:
                candidate_bound_maps += 1
            elif mapping_mode == "exact_blob":
                provenance_anchored_exact_blob_maps += 1
            else:
                exact_observed_fallback_maps += 1
            boundary = row.get("claimBoundary") or row.get("completion")
            if not isinstance(boundary, dict):
                raise ValueError("claim boundary")
            implemented_mapping_complete = all(
                bool(op.get("sourcePathExists") and op.get("nativeSymbol"))
                for op in ops
            )
            if (
                "implementedOperationMappingComplete" in boundary
                and boundary["implementedOperationMappingComplete"]
                is not implemented_mapping_complete
            ):
                raise ValueError("implemented operation mapping claim drift")
            owned_protocols = row.get("ownedTargetProtocols")
            if owned_protocols is not None:
                if not isinstance(owned_protocols, list):
                    raise ValueError("owned target protocols")
                owned_source_complete = all(
                    isinstance(item, dict) and item.get("state") == "source_implemented"
                    for item in owned_protocols
                )
                if (
                    boundary.get("ownedTargetProtocolSourceComplete")
                    is not owned_source_complete
                ):
                    raise ValueError("owned target protocol source claim drift")
                if boundary.get("nativeSourceMappingComplete") is not (
                    implemented_mapping_complete and owned_source_complete
                ):
                    raise ValueError("native source mapping claim drift")
            status = row.get("status")
            if status is not None:
                if not isinstance(status, dict) or any(
                    not isinstance(status.get(field), bool)
                    for field in ("implemented", "composed", "qualified")
                ):
                    raise ValueError("invalid implemented/composed/qualified status")
                if status["composed"] != (
                    row.get("productCallerState") != "not_composed"
                ):
                    raise ValueError("composition status disagreement")
            if (
                row.get("exactSourceEvidence", {}).get("kind")
                == "path_blob_manifest_v1"
            ):
                manifest_failures = []
                validate_path_blob_manifest(row, mid, manifest_failures)
                if manifest_failures:
                    raise ValueError("; ".join(manifest_failures))
            source_objects = row.get("sourceObjects")
            if source_objects is not None:
                if not isinstance(source_objects, list) or not source_objects:
                    raise ValueError("source objects")
                if source_objects != current_source_objects(row):
                    raise ValueError("stale source objects")
            if row.get("productCallerState", "not_composed") != "not_composed":
                callers = row.get("productCallers")
                if not isinstance(callers, list) or not callers:
                    raise ValueError("composed map requires product callers")
                for caller in callers:
                    if not isinstance(caller, dict):
                        raise ValueError("invalid product caller")
                    source = caller.get("sourcePath")
                    symbol = caller.get("nativeSymbol")
                    if not isinstance(source, str):
                        raise ValueError("missing product caller source")
                    local = checked_source_path(ROOT, source)
                    if not local.is_file():
                        raise ValueError(f"missing product caller source {source}")
                    if isinstance(symbol, str) and symbol:
                        if symbol.rsplit("::", 1)[-1] not in local.read_text(
                            encoding="utf-8"
                        ):
                            raise ValueError(f"missing product caller symbol {symbol}")
                if source_objects is None:
                    if (
                        row.get("exactSourceEvidenceMode")
                        != "lane_a_runtime_head_tree_and_registered_callers"
                    ):
                        raise ValueError("composed map requires exact source objects")
                    if row.get("laneId") != "LANE-A-FOUNDATION":
                        raise ValueError(
                            "Lane A runtime source evidence mode used outside Lane A"
                        )
        except (
            ValueError,
            TypeError,
            KeyError,
            OSError,
            subprocess.CalledProcessError,
        ) as exc:
            failures.append(f"{mid}: {exc}")
    try:
        # Two global scans, not two scans per module. The documented contract
        # remains a quiescent checkout, never concurrent build attestation.
        require_clean_candidate(candidate, sorted(checked_paths))
    except (ValueError, subprocess.CalledProcessError) as exc:
        failures.append(str(exc))
    if failures:
        raise SystemExit("FAIL_HEPTA_IMPLEMENTATION_MAPS: " + "; ".join(failures))
    print(
        json.dumps(
            {
                "status": "PASS_HEPTA_IMPLEMENTATION_MAPS",
                "modules": len(selected_modules),
                "maps": len(selected_modules),
                "selectedModules": [module["id"] for module in selected_modules],
                "registryModules": len(registered_modules),
                "verificationScope": (
                    "module_subset" if modules is not None else "complete_registry"
                ),
                "productionImplementationProved": False,
                "candidateSource": candidate,
                "currentSourceIdentityRequired": True,
                "candidateBoundMaps": candidate_bound_maps,
                "exactObservedFallbackMaps": exact_observed_fallback_maps,
                "provenanceAnchoredExactBlobMaps": provenance_anchored_exact_blob_maps,
                "legacyProvenanceOnlyMaps": [],
                "sourceObservationCount": len(source_bases),
                "sourceBaseSemantics": "provenance_anchor_plus_exact_head_blobs_and_current_observation",
                "validationScope": "source_navigation_and_declared_evidence_not_build_or_execution",
            },
            sort_keys=True,
        )
    )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "command", choices=["generate", "migrate", "verify", "sync-plasticity-status"]
    )
    parser.add_argument(
        "--module",
        action="append",
        dest="modules",
        help="select this module (repeatable; migrate or verify only)",
    )
    parser.add_argument(
        "--require-current-source",
        action="store_true",
        help="Compatibility alias: verify always requires clean, exact mapped source; not execution qualification.",
    )
    parser.add_argument(
        "--expected-sha",
        help="Require verify to run at this exact committed candidate SHA.",
    )
    parser.add_argument(
        "--expected-tree",
        help="Require verify to run at this exact candidate tree.",
    )
    args = parser.parse_args()
    if args.require_current_source and args.command != "verify":
        parser.error("--require-current-source applies only to verify")
    if args.modules is not None and args.command not in {"migrate", "verify"}:
        parser.error("--module applies only to migrate or verify")
    if (
        args.expected_sha is not None or args.expected_tree is not None
    ) and args.command != "verify":
        parser.error("--expected-sha/--expected-tree apply only to verify")
    if args.command == "migrate":
        migrate(args.modules)
    else:
        {
            "generate": generate,
            "verify": lambda: verify(
                modules=args.modules,
                expected_sha=args.expected_sha,
                expected_tree=args.expected_tree,
            ),
            "sync-plasticity-status": sync_plasticity_status,
        }[args.command]()


if __name__ == "__main__":
    main()
