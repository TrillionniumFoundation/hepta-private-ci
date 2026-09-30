#!/usr/bin/env python3
"""Exact Git-object hardening for the compact.engine qualification kernel."""
from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

_LEGACY = Path(__file__).with_name("compact_engine_qualification_legacy.py")
_SPEC = importlib.util.spec_from_file_location("_compact_engine_qualification_legacy", _LEGACY)
if _SPEC is None or _SPEC.loader is None:  # pragma: no cover
    raise RuntimeError(f"cannot load qualification kernel: {_LEGACY}")
_legacy = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = _legacy
_SPEC.loader.exec_module(_legacy)
for _name, _value in vars(_legacy).items():
    if not _name.startswith("__"):
        globals()[_name] = _value

_legacy_verify = _legacy.verify_implementation_map
_legacy_build = _legacy.build_readiness_manifest
_legacy_test_inputs = _legacy._test_inputs
QUALIFICATION_PROFILE_INPUTS = tuple(dict.fromkeys((
    *_legacy.QUALIFICATION_PROFILE_INPUTS,
    Path("scripts/compact_engine_qualification_legacy.py"),
    Path("scripts/test_compact_engine_qualification_legacy.py"),
)))
_legacy.QUALIFICATION_PROFILE_INPUTS = QUALIFICATION_PROFILE_INPUTS


def _test_inputs(root: Path) -> list[Path]:
    return sorted(set((*_legacy_test_inputs(root), Path(
        "scripts/test_compact_engine_qualification_legacy.py"
    ))))


_legacy._test_inputs = _test_inputs


def _test_path(value: str) -> str:
    return Path(value.split(".rs::", 1)[0] + ".rs").as_posix() \
        if ".rs::" in value else Path(value).as_posix()


def _paths(row: dict[str, Any]) -> list[str]:
    result = {
        MAP_PATH.as_posix(), AGENTD_HOST.as_posix(), CRATE_ROOT.as_posix(),
        "codex-rs/Cargo.toml", "codex-rs/Cargo.lock",
        *(p.as_posix() for p in MIGRATION_INPUTS),
        *(p.as_posix() for p in DOCUMENTATION_INPUTS),
        *(p.as_posix() for p in QUALIFICATION_PROFILE_INPUTS),
    }
    for key in ("technicalGuide", "recoveryProtocol", "qualificationWorkflow", "capacityWorkflow"):
        value = row.get(key)
        if isinstance(value, str) and value:
            result.add(value)
    for key in ("declaredRoots", "resolvedRoots", "sourceRoot", "observedSourcePaths"):
        for value in row.get(key, []):
            if isinstance(value, str) and value:
                result.add(value)
    for operation in row.get("operations", []):
        if not isinstance(operation, dict):
            continue
        value = operation.get("sourcePath")
        if isinstance(value, str) and value:
            result.add(value)
        for value in operation.get("tests", []):
            if isinstance(value, str) and value:
                result.add(_test_path(value))
        for value in operation.get("delegatedCallees", []):
            if isinstance(value, str) and value and ("/" in value or value.endswith(".rs")):
                result.add(value)
    for caller in row.get("productCallers", []):
        if isinstance(caller, dict) and isinstance(caller.get("sourcePath"), str):
            result.add(caller["sourcePath"])
    verifier = row.get("qualificationVerifier", {})
    if isinstance(verifier, dict):
        for key in ("path", "tests", "workflow"):
            if isinstance(verifier.get(key), str) and verifier[key]:
                result.add(verifier[key])
    exact = row.get("exactSourceEvidence", {})
    if isinstance(exact, dict):
        for entry in exact.get("entries", []):
            if isinstance(entry, dict) and isinstance(entry.get("path"), str):
                result.add(entry["path"])
    for entry in row.get("sourceObjects", []):
        if isinstance(entry, dict) and isinstance(entry.get("path"), str):
            result.add(entry["path"])
    return sorted(Path(value).as_posix() for value in result)


def _object(root: Path, path: str, revision: str = "HEAD") -> dict[str, str]:
    checked_repo_path(root, path)
    if revision == "HEAD":
        dirty = run_git(root, "status", "--porcelain=v1", "--untracked-files=all", "--", path)
        if dirty:
            raise QualificationError(f"mapped source path is dirty or untracked: {path}: {dirty}")
    oid = run_git(root, "rev-parse", f"{revision}:{path}")
    kind = run_git(root, "cat-file", "-t", oid)
    if _SHA_RE.fullmatch(oid) is None or kind not in {"blob", "tree"}:
        raise QualificationError(f"invalid Git object for {path}: {oid} ({kind})")
    return {"path": path, "object": oid, "type": kind}


def _exact(root: Path, path: Any, expected: Any, field: str, revision: str = "HEAD") -> None:
    if not isinstance(path, str) or not path:
        raise QualificationError(f"{field} path is missing")
    if not isinstance(expected, str) or _SHA_RE.fullmatch(expected) is None:
        raise QualificationError(f"{field} for {path} is not a 40-character object SHA")
    actual = _object(root, path, revision)
    if actual["object"] != expected:
        raise QualificationError(f"{field} mismatch for {path}: {expected} != {actual['object']}")


def _source_manifest(root: Path, row: dict[str, Any]) -> dict[str, Any]:
    if row.get("mappingSourceIdentityMode") != "exact_blob":
        raise QualificationError("mappingSourceIdentityMode must be exact_blob")
    observed = row.get("observedAtHead")
    if not isinstance(observed, dict):
        raise QualificationError("observedAtHead must be an object")
    commit, tree = observed.get("commit"), observed.get("tree")
    if not isinstance(commit, str) or _SHA_RE.fullmatch(commit) is None:
        raise QualificationError("observedAtHead.commit is invalid")
    if not isinstance(tree, str) or _SHA_RE.fullmatch(tree) is None:
        raise QualificationError("observedAtHead.tree is invalid")
    run_git(root, "cat-file", "-e", f"{commit}^{{commit}}")
    actual_tree = run_git(root, "rev-parse", f"{commit}^{{tree}}")
    if actual_tree != tree:
        raise QualificationError(f"observedAtHead tree mismatch: {tree} != {actual_tree}")
    run_git(root, "merge-base", "--is-ancestor", commit, "HEAD")

    declared: dict[str, str] = {}
    def record(path: Any, oid: Any, field: str) -> None:
        if isinstance(path, str) and path in declared and declared[path] != oid:
            raise QualificationError(f"conflicting object identities for {path}")
        _exact(root, path, oid, field)
        _exact(root, path, oid, f"{field} at observedAtHead", commit)
        declared[path] = oid

    operations = row.get("operations")
    if not isinstance(operations, list) or not operations:
        raise QualificationError("implementation map operations must be non-empty")
    for operation in operations:
        if not isinstance(operation, dict):
            raise QualificationError("implementation map operation must be an object")
        record(operation.get("sourcePath"), operation.get("sourceBlob"), "operation sourceBlob")

    exact = row.get("exactSourceEvidence")
    if not isinstance(exact, dict) or exact.get("kind") != "path_blob_manifest_v1":
        raise QualificationError("exactSourceEvidence must be path_blob_manifest_v1")
    entries = exact.get("entries")
    if not isinstance(entries, list) or not entries:
        raise QualificationError("exactSourceEvidence.entries must be non-empty")
    seen: set[str] = set()
    for entry in entries:
        if not isinstance(entry, dict) or not isinstance(entry.get("path"), str):
            raise QualificationError("exactSourceEvidence entry is invalid")
        path = entry["path"]
        if path in seen:
            raise QualificationError(f"duplicate exactSourceEvidence path: {path}")
        seen.add(path)
        record(path, entry.get("blobSha"), "exactSourceEvidence.blobSha")
        if _object(root, path)["type"] != "blob":
            raise QualificationError(f"exactSourceEvidence path is not a blob: {path}")

    objects = row.get("sourceObjects")
    if not isinstance(objects, list) or not objects:
        raise QualificationError("sourceObjects must be non-empty")
    seen.clear()
    for entry in objects:
        if not isinstance(entry, dict) or not isinstance(entry.get("path"), str):
            raise QualificationError("sourceObjects entry is invalid")
        path = entry["path"]
        if path in seen:
            raise QualificationError(f"duplicate sourceObjects path: {path}")
        seen.add(path)
        record(path, entry.get("object"), "sourceObjects.object")

    payload = {
        "schema": "hepta.compact-engine-source-object-manifest.v1",
        "head_commit": run_git(root, "rev-parse", "HEAD"),
        "head_tree": run_git(root, "rev-parse", "HEAD^{tree}"),
        "observed_commit": commit,
        "observed_tree": tree,
        "objects": [_object(root, path) for path in _paths(row)],
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    payload["manifest_sha256"] = hashlib.sha256(canonical).hexdigest()
    return payload


def verify_implementation_map(root: Path, output: Path | None = None) -> dict[str, Any]:
    report = _legacy_verify(root, None)
    row = load_json(checked_repo_path(root, MAP_PATH))
    enforced = row.get("mappingSourceIdentityMode") == "exact_blob"
    source = _source_manifest(root, row) if enforced else None
    report.update({
        "schema": "hepta.compact-engine-implementation-map-verification.v2",
        "source_identity_enforced": enforced,
        "source_identity_verified": source is not None,
        "source_object_manifest_hash": source["manifest_sha256"] if source else None,
        "source_object_manifest": source,
    })
    if output is not None:
        dump_json(output, report)
    return report


def build_readiness_manifest(root: Path, artifacts: Path, output: Path, **kwargs: Any) -> dict[str, Any]:
    manifest = _legacy_build(root, artifacts, output, **kwargs)
    errors = list(manifest.get("generation_errors", []))
    try:
        row = load_json(checked_repo_path(root, MAP_PATH))
    except QualificationError:
        row = {}
    enforced = row.get("schema") == "hepta.module-implementation-map.v3" \
        and row.get("mappingSourceIdentityMode") == "exact_blob"
    source = None
    if enforced:
        try:
            source = _source_manifest(root, row)
        except QualificationError as exc:
            errors.append(f"source identity verification failed: {exc}")
    manifest["source_identity_enforced"] = enforced
    manifest["source_identity_verified"] = source is not None
    manifest["source_object_manifest"] = source
    manifest["source_object_manifest_hash"] = source["manifest_sha256"] if source else None

    event = kwargs["event_name"]
    workflow = kwargs["workflow_sha"]
    source_sha = kwargs["source_head_sha"]
    final = kwargs["final_merge_sha"]
    final_main = event == "push" and kwargs["postmerge_result"] == "success" \
        and bool(final) and final == workflow == source_sha
    github_merge = manifest.get("github_merge_sha")
    merge_source = "workflow_input" if github_merge else None
    if final_main and not github_merge:
        github_merge, merge_source = workflow, "main_push_workflow_sha"
    manifest["github_merge_sha"] = github_merge
    manifest["github_merge_sha_source"] = merge_source
    if errors or (enforced and source is None):
        manifest["requiredLanesPassed"] = False
    manifest["mergeReady"] = bool(
        event == "pull_request" and manifest.get("requiredLanesPassed") is True
        and github_merge == workflow and not errors
    )
    manifest["productionQualified"] = bool(
        final_main and manifest.get("requiredLanesPassed") is True
        and github_merge == workflow and source is not None and not errors
    )
    boundary = manifest.setdefault("claim_boundary", {})
    if isinstance(boundary, dict):
        boundary["exact_source_identity"] = source is not None
        boundary["single_github_merge_sha"] = bool(github_merge and github_merge == workflow)
    manifest["generation_errors"] = sorted(set(str(error) for error in errors))
    dump_json(output, manifest)
    return manifest


_legacy.verify_implementation_map = verify_implementation_map
_legacy.build_readiness_manifest = build_readiness_manifest


def main(argv: list[str] | None = None) -> int:
    return _legacy.main(argv)


if __name__ == "__main__":
    raise SystemExit(main())
