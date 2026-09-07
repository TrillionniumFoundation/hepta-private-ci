#!/usr/bin/env python3
"""Normalize and verify the bounded Hepta V8 source-closure candidate."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
import tomllib
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any

from hepta_module_doc_metadata import synchronize as synchronize_module_metadata

from hepta_source_registry_closure import normalize as normalize_source_registries
from hepta_source_registry_closure import verify as verify_source_registries

ROOT = Path(__file__).resolve().parents[1]
CARGO_MANIFEST = ROOT / "codex-rs" / "Cargo.toml"
QUALIFICATION_MANIFEST = ROOT / "qualification" / "gap-closure" / "MANIFEST.json"
QUALIFICATION_PLAN_AUDIT = ROOT / "qualification" / "gap-closure" / "PLAN_AUDIT.json"
STATIC_CANDIDATE_IDENTITY = "resolved_by_external_exact_candidate_receipt"

RUST_PACKAGES = {
    "hepta-bellman-operator": "codex-hepta-bellman-operator",
    "hepta-infer-worker-host": "codex-hepta-infer-worker-host",
    "hepta-intelligence-eval": "codex-hepta-intelligence-eval",
    "hepta-intuition": "codex-hepta-intuition",
    "hepta-learning-artifacts": "codex-hepta-learning-artifacts",
    "hepta-learning-ledger": "codex-hepta-learning-ledger",
    "hepta-ndu": "codex-hepta-ndu",
    "hepta-neuron": "codex-hepta-neuron",
    "hepta-objective": "codex-hepta-objective",
    "hepta-plasticity": "codex-hepta-plasticity",
    "hepta-prompt-optimizer": "codex-hepta-prompt-optimizer",
    "hepta-prompt-registry": "codex-hepta-prompt-registry",
}

REQUIRED_OTHER_FILES = (
    "apps/hepta-control-ui/package.json",
    "apps/hepta-control-ui/src/control.js",
    "apps/hepta-control-ui/test/control.test.js",
    "tools/hepta-engineering-control/hepta_engineering_control.py",
    "tools/hepta-engineering-control/test_hepta_engineering_control.py",
    "docs/readiness/GAP_CLOSURE_IMPLEMENTATION.md",
    "qualification/gap-closure/MANIFEST.json",
    "qualification/gap-closure/PLAN_AUDIT.json",
    "scripts/hepta_source_registry_closure.py",
    "scripts/test_hepta_gap_closure.py",
)

DENIED_AUTHORITY_FLAGS = (
    "runtime_authority",
    "production_writer",
    "production_activation",
    "effect_execution",
    "automatic_selection",
    "automatic_promotion",
    "automatic_merge",
    "release_authority",
    "physical_safety_qualified",
    "longitudinal_efficacy_qualified",
    "autonomous_propagation",
)

IDENTITY_RECEIPT_SCHEMA = "hepta.exact-source-identity-receipt.v1"
DOCUMENT_SET_SCHEMA = "hepta.canonical-document-set.v1"
DOCUMENT_SYSTEM_PATH = "docs/governance/DOCUMENT_SYSTEM.json"
IDENTITY_WORKFLOW_PATH = ".github/workflows/hepta-gap-closure.yml"
IDENTITY_VERIFIER_PATH = "scripts/hepta-gap-closure.py"
SOURCE_REGISTRY_VERIFIER_PATH = "scripts/hepta_source_registry_closure.py"
QUALIFICATION_MANIFEST_PATH = "qualification/gap-closure/MANIFEST.json"
QUALIFICATION_PLAN_AUDIT_PATH = "qualification/gap-closure/PLAN_AUDIT.json"
MAX_LINEAGE_COMMITS = 2048
MAX_RECEIPT_TTL_SECONDS = 604800
MAX_FUTURE_SKEW_SECONDS = 300
OID_RE = re.compile(r"^[0-9a-f]{40}$")
UTC_TIMESTAMP_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
STATIC_SOURCE_IDENTITY_POLICY: dict[str, Any] = {
    "canonical_document_set_digest_required": True,
    "canonical_repository_binding_required": True,
    "clean_worktree_required": True,
    "event_binding_required": True,
    "explicit_commit_checkout_required": True,
    "full_literal_git_oid_required": True,
    "maximum_ttl_seconds": MAX_RECEIPT_TTL_SECONDS,
    "merge_parent_order": ["base", "source"],
    "merge_tree_validation": "recomputed_with_git_merge_tree",
    "receipt_schema": IDENTITY_RECEIPT_SCHEMA,
    "receipt_storage": "external_artifact_only",
    "source_lineage_direct_parent_required": True,
    "source_range_merge_commits_forbidden": True,
    "source_range_nonempty": True,
    "verification_worktree_read_only": True,
    "workflow_path": IDENTITY_WORKFLOW_PATH,
}
DYNAMIC_IDENTITY_KEYS = frozenset(
    {
        "baseCommit",
        "baseTree",
        "base_commit",
        "base_tree",
        "candidateBranch",
        "candidateHead",
        "candidateTree",
        "candidate_branch",
        "candidate_commit",
        "candidate_head",
        "candidate_tree",
        "commit",
        "expectedCommit",
        "expected_commit",
        "headCommit",
        "headTree",
        "merge_commit",
        "merge_parents",
        "merge_tree",
        "mergeCandidate",
        "mergeParents",
        "mergeTree",
        "normalizedParent",
        "normalized_parent",
        "observedAt",
        "observed_at",
        "source_commit",
        "source_lineage",
        "source_lineage_digest",
        "source_parents",
        "source_tree",
        "sourceCommit",
        "sourceLineage",
        "sourceLineageDigest",
        "sourceParents",
        "sourceTree",
        "targetBranch",
        "target_branch",
        "tree",
    }
)


class ExactIdentityError(RuntimeError):
    """Raised when immutable Git identity checks fail."""


def static_identity_leaks(value: Any, location: str = "$") -> list[str]:
    """Find dynamic candidate tuple fields in a static qualification document."""

    leaks: list[str] = []
    if isinstance(value, dict):
        for key, child in value.items():
            child_location = f"{location}.{key}"
            if key in DYNAMIC_IDENTITY_KEYS:
                leaks.append(child_location)
            leaks.extend(static_identity_leaks(child, child_location))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            leaks.extend(static_identity_leaks(child, f"{location}[{index}]"))
    elif isinstance(value, str) and OID_RE.fullmatch(value) is not None:
        leaks.append(location + "=<git-oid>")
    return leaks


def validate_static_candidate_manifest(manifest: dict[str, Any]) -> list[str]:
    failures: list[str] = []
    if manifest.get("schema_version") != 2:
        failures.append("qualification manifest schema version is incorrect")
    if manifest.get("candidate_identity") != STATIC_CANDIDATE_IDENTITY:
        failures.append("qualification candidate identity policy is incorrect")
    if manifest.get("source_identity_policy") != STATIC_SOURCE_IDENTITY_POLICY:
        failures.append("qualification source identity policy is incorrect")
    leaks = static_identity_leaks(manifest)
    if leaks:
        failures.append(
            "qualification manifest embeds dynamic candidate identity: "
            + ", ".join(leaks)
        )
    return failures


def _identity_need(condition: bool, message: str) -> None:
    if not condition:
        raise ExactIdentityError(message)


def _identity_git_environment(
    extra_env: dict[str, str] | None = None,
) -> dict[str, str]:
    environment = {
        key: value for key, value in os.environ.items() if not key.startswith("GIT_")
    }
    environment.update(
        {
            "GIT_CONFIG_GLOBAL": os.devnull,
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_NO_LAZY_FETCH": "1",
            "GIT_OPTIONAL_LOCKS": "0",
            "GIT_TERMINAL_PROMPT": "0",
            "LC_ALL": "C",
        }
    )
    if extra_env:
        environment.update(extra_env)
    return environment


def _identity_git_process(
    repo: Path,
    *args: str,
    check: bool = True,
    input_text: str | None = None,
    extra_env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[bytes]:
    process = subprocess.run(
        [
            "git",
            "--no-replace-objects",
            "-c",
            "core.fsmonitor=false",
            "-c",
            "core.untrackedCache=false",
            "-C",
            str(repo),
            *args,
        ],
        input=input_text.encode("utf-8") if input_text is not None else None,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=_identity_git_environment(extra_env),
        check=False,
    )
    if check and process.returncode:
        detail = process.stderr.decode("utf-8", "replace").strip()
        raise ExactIdentityError("git " + " ".join(args) + ": " + detail)
    return process


def _identity_git(repo: Path, *args: str) -> str:
    return _identity_git_process(repo, *args).stdout.decode("utf-8").strip()


def _identity_canonical_json(value: Any) -> bytes:
    return json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def _identity_json_pairs(items: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in items:
        if key in result:
            raise ExactIdentityError("duplicate JSON key: " + key)
        result[key] = value
    return result


def _identity_json_constant(value: str) -> Any:
    raise ExactIdentityError("non-finite JSON number: " + value)


def _identity_load_json(raw: bytes, label: str) -> dict[str, Any]:
    try:
        value = json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=_identity_json_pairs,
            parse_constant=_identity_json_constant,
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ExactIdentityError(label + ": " + str(error)) from error
    _identity_need(isinstance(value, dict), label + " must contain an object")
    return value


def _identity_oid(value: str, label: str) -> str:
    _identity_need(
        isinstance(value, str) and OID_RE.fullmatch(value) is not None,
        label + " Git OID",
    )
    return value


def identity_require_repository_root(repo: Path) -> None:
    _identity_need(repo.is_dir(), "repository checkout is not a directory")
    observed = Path(_identity_git(repo, "rev-parse", "--show-toplevel")).resolve()
    _identity_need(
        observed == repo.resolve(), "repository path is not the checkout root"
    )


def identity_commit_tree(repo: Path, commit: str) -> str:
    commit = _identity_oid(commit, "commit")
    resolved = _identity_git(repo, "rev-parse", "--verify", commit + "^{commit}")
    _identity_need(resolved == commit, "commit identity drift")
    return _identity_oid(
        _identity_git(repo, "rev-parse", "--verify", commit + "^{tree}"),
        "tree",
    )


def identity_commit_parents(repo: Path, commit: str) -> list[str]:
    identity_commit_tree(repo, commit)
    raw = _identity_git_process(repo, "cat-file", "commit", commit).stdout
    header, separator, _message = raw.partition(b"\n\n")
    _identity_need(bool(separator), "commit object has no header separator")
    parents: list[str] = []
    for line in header.splitlines():
        if not line.startswith(b"parent "):
            continue
        try:
            parent = line.removeprefix(b"parent ").decode("ascii")
        except UnicodeDecodeError as error:
            raise ExactIdentityError("invalid commit parent encoding") from error
        parents.append(_identity_oid(parent, "parent"))
    return parents


def identity_source_lineage(repo: Path, base: str, source: str) -> list[str]:
    """Return a bounded contiguous single-parent stack from base to source."""

    base = _identity_oid(base, "base")
    source = _identity_oid(source, "source")
    identity_commit_tree(repo, base)
    identity_commit_tree(repo, source)
    _identity_need(base != source, "source must advance the base")
    reverse_lineage: list[str] = []
    current = source
    while current != base:
        _identity_need(
            len(reverse_lineage) < MAX_LINEAGE_COMMITS,
            "source lineage exceeds receipt capacity",
        )
        reverse_lineage.append(current)
        parents = identity_commit_parents(repo, current)
        if len(parents) > 1:
            raise ExactIdentityError("source stack contains a merge commit")
        _identity_need(parents, "base is not an ancestor of source")
        current = parents[0]
    reverse_lineage.reverse()
    return reverse_lineage


def identity_lineage_digest(lineage: list[str]) -> str:
    payload = b"hepta.source-lineage.v1\0" + b"\n".join(
        item.encode("ascii") for item in lineage
    )
    return hashlib.sha256(payload).hexdigest()


def identity_expected_merge_tree(repo: Path, base: str, source: str) -> str:
    identity_source_lineage(repo, base, source)
    object_path = Path(_identity_git(repo, "rev-parse", "--git-path", "objects"))
    if not object_path.is_absolute():
        object_path = (repo / object_path).resolve()
    _identity_need(object_path.is_dir(), "Git object directory is unavailable")
    with tempfile.TemporaryDirectory(prefix="hepta-merge-tree-") as temporary:
        scratch_git = Path(temporary) / "git"
        init = subprocess.run(
            ["git", "init", "--bare", "--quiet", str(scratch_git)],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=_identity_git_environment(),
            check=False,
        )
        _identity_need(init.returncode == 0, "cannot initialize merge-tree scratch")
        scratch_objects = scratch_git / "objects"
        process = _identity_git_process(
            repo,
            "merge-tree",
            "--write-tree",
            base,
            source,
            extra_env={
                "GIT_CONFIG_GLOBAL": os.devnull,
                "GIT_CONFIG_NOSYSTEM": "1",
                "GIT_DIR": str(scratch_git),
                "GIT_ALTERNATE_OBJECT_DIRECTORIES": str(object_path),
                "GIT_OBJECT_DIRECTORY": str(scratch_objects),
            },
        )
        output = process.stdout.decode("utf-8").strip()
    _identity_need(
        OID_RE.fullmatch(output) is not None,
        "merge-tree did not emit exactly one tree",
    )
    return output


def _identity_safe_repo_path(path: str, label: str) -> PurePosixPath:
    _identity_need(isinstance(path, str) and bool(path), label + " path")
    parsed = PurePosixPath(path)
    _identity_need(
        path == parsed.as_posix()
        and not parsed.is_absolute()
        and ".." not in parsed.parts
        and "." not in parsed.parts
        and "\\" not in path
        and "\0" not in path,
        "unsafe " + label + " path: " + path,
    )
    return parsed


def _identity_blob_at(repo: Path, commit: str, path: str) -> tuple[str, bytes]:
    _identity_safe_repo_path(path, "Git tree")
    record = _identity_git_process(
        repo,
        "ls-tree",
        "-z",
        commit,
        "--",
        ":(literal)" + path,
    ).stdout
    rows = [item for item in record.split(b"\0") if item]
    _identity_need(
        len(rows) == 1,
        "canonical path is missing or ambiguous: " + path,
    )
    try:
        metadata, observed_path = rows[0].split(b"\t", 1)
        mode, kind, oid = metadata.decode("ascii").split()
        decoded_path = observed_path.decode("utf-8")
    except (ValueError, UnicodeDecodeError) as error:
        raise ExactIdentityError("invalid Git tree record for " + path) from error
    _identity_need(decoded_path == path, "canonical path drift: " + path)
    _identity_need(
        kind == "blob" and mode in {"100644", "100755"},
        "canonical path is not a regular file: " + path,
    )
    _identity_oid(oid, "blob")
    raw = _identity_git_process(
        repo,
        "cat-file",
        "blob",
        oid,
    ).stdout
    return mode, raw


def identity_blob_sha256(repo: Path, commit: str, path: str) -> str:
    _, raw = _identity_blob_at(repo, commit, path)
    return hashlib.sha256(raw).hexdigest()


def _identity_document_system(repo: Path, commit: str) -> dict[str, Any]:
    _, raw_system = _identity_blob_at(repo, commit, DOCUMENT_SYSTEM_PATH)
    return _identity_load_json(raw_system, DOCUMENT_SYSTEM_PATH)


def identity_validate_repository(
    repo: Path,
    commit: str,
    repository_id: int,
    repository: str,
) -> None:
    system = _identity_document_system(repo, commit)
    canonical = system.get("repository")
    _identity_need(
        isinstance(canonical, dict),
        "canonical repository identity is missing",
    )
    _identity_need(
        type(canonical.get("id")) is int and canonical.get("id") == repository_id,
        "canonical repository id drift",
    )
    _identity_need(
        canonical.get("fullName") == repository,
        "canonical repository name drift",
    )


def identity_document_set_digest(repo: Path, commit: str) -> tuple[str, int]:
    identity_commit_tree(repo, commit)
    system = _identity_document_system(repo, commit)
    paths = system.get("canonicalPaths")
    _identity_need(
        isinstance(paths, list)
        and paths
        and all(isinstance(path, str) for path in paths),
        "canonical document paths",
    )
    _identity_need(len(paths) == len(set(paths)), "duplicate canonical document path")
    _identity_need(
        DOCUMENT_SYSTEM_PATH in paths,
        "document system must include itself in canonical paths",
    )
    normalized = []
    for path in paths:
        _identity_safe_repo_path(path, "canonical document")
        normalized.append(path)
    documents = []
    for path in sorted(normalized):
        mode, raw = _identity_blob_at(repo, commit, path)
        documents.append(
            {
                "mode": mode,
                "path": path,
                "sha256": hashlib.sha256(raw).hexdigest(),
            }
        )
    encoded = _identity_canonical_json(
        {
            "documents": documents,
            "schema": DOCUMENT_SET_SCHEMA,
        }
    )
    return hashlib.sha256(encoded).hexdigest(), len(documents)


def identity_require_clean_worktree(repo: Path) -> None:
    status = _identity_git_process(
        repo,
        "status",
        "--porcelain=v1",
        "-z",
        "--untracked-files=all",
    ).stdout
    _identity_need(
        status == b"",
        "working tree contains tracked, staged, or untracked changes",
    )


def identity_validate_event(
    event_name: str,
    event_path: str,
    repository_id: int,
    repository: str,
    base: str,
    source: str,
) -> dict[str, Any]:
    _identity_need(
        event_name in {"pull_request", "push"},
        "unsupported GitHub event",
    )
    _identity_need(bool(event_path), "GitHub event path is required")
    path = Path(event_path)
    _identity_need(path.is_file(), "GitHub event path is not a file")
    event = _identity_load_json(path.read_bytes(), "GitHub event")
    event_repository = event.get("repository")
    _identity_need(
        isinstance(event_repository, dict),
        "event repository identity is missing",
    )
    _identity_need(
        event_repository.get("full_name") == repository,
        "event repository name drift",
    )
    _identity_need(
        type(event_repository.get("id")) is int
        and event_repository.get("id") == repository_id,
        "event repository id drift",
    )

    if event_name == "pull_request":
        pull_request = event.get("pull_request")
        _identity_need(
            isinstance(pull_request, dict),
            "pull request event identity is missing",
        )
        number = event.get("number")
        _identity_need(
            type(number) is int and number > 0,
            "pull request number",
        )
        event_base = pull_request.get("base")
        event_source = pull_request.get("head")
        _identity_need(
            isinstance(event_base, dict) and event_base.get("sha") == base,
            "event base drift",
        )
        _identity_need(
            isinstance(event_source, dict) and event_source.get("sha") == source,
            "event source drift",
        )
        base_repository = event_base.get("repo")
        source_repository = event_source.get("repo")
        _identity_need(
            isinstance(base_repository, dict)
            and base_repository.get("full_name") == repository
            and type(base_repository.get("id")) is int
            and base_repository.get("id") == repository_id,
            "event base repository drift",
        )
        _identity_need(
            isinstance(source_repository, dict)
            and type(source_repository.get("id")) is int
            and source_repository["id"] > 0
            and isinstance(source_repository.get("full_name"), str)
            and "/" in source_repository["full_name"],
            "event source repository identity is missing",
        )
        base_ref = event_base.get("ref")
        source_ref = event_source.get("ref")
        _identity_need(
            isinstance(base_ref, str) and bool(base_ref),
            "event base ref",
        )
        _identity_need(
            isinstance(source_ref, str) and bool(source_ref),
            "event source ref",
        )
        action = event.get("action")
        _identity_need(
            isinstance(action, str) and bool(action),
            "pull request action",
        )
        merge_commit = pull_request.get("merge_commit_sha")
        _identity_need(
            merge_commit is None
            or (
                isinstance(merge_commit, str)
                and OID_RE.fullmatch(merge_commit) is not None
            ),
            "event merge commit",
        )
        return {
            "action": action,
            "baseRef": base_ref,
            "eventName": event_name,
            "mergeCommit": merge_commit,
            "pullRequestNumber": number,
            "sourceRef": source_ref,
            "sourceRepositoryFullName": source_repository["full_name"],
            "sourceRepositoryId": source_repository["id"],
        }

    _identity_need("pull_request" not in event, "push event shape drift")
    _identity_need(event.get("after") == source, "push source drift")
    _identity_need(event.get("before") == base, "push base drift")
    _identity_need(event.get("deleted") is False, "deleted push is unsupported")
    ref = event.get("ref")
    _identity_need(
        isinstance(ref, str) and ref.startswith("refs/heads/") and len(ref) > 11,
        "push branch ref",
    )
    return {
        "eventName": event_name,
        "ref": ref,
    }


def build_exact_identity_receipt(
    *,
    kind: str,
    repository_id: int,
    repository: str,
    base: str,
    source: str,
    expected: str,
    workflow_path: str,
    event_name: str,
    event_path: str,
    ttl_seconds: int = 86400,
    observed_at: str | None = None,
    repo: Path = ROOT,
) -> dict[str, Any]:
    repo = repo.resolve()
    identity_require_repository_root(repo)
    _identity_need(
        kind in {"source-head", "merge-candidate"},
        "unsupported identity kind",
    )
    _identity_need(type(repository_id) is int and repository_id > 0, "repository id")
    _identity_need(bool(repository) and "/" in repository, "repository full name")
    _identity_need(
        workflow_path == IDENTITY_WORKFLOW_PATH,
        "identity workflow path drift",
    )
    _identity_need(
        type(ttl_seconds) is int and 0 < ttl_seconds <= MAX_RECEIPT_TTL_SECONDS,
        "receipt TTL",
    )
    base = _identity_oid(base, "base")
    source = _identity_oid(source, "source")
    expected = _identity_oid(expected, "expected commit")
    event_path = str(
        _identity_external_path(
            event_path,
            repo,
            "GitHub event",
            require_file=True,
        )
    )
    event_identity = identity_validate_event(
        event_name,
        event_path,
        repository_id,
        repository,
        base,
        source,
    )
    identity_require_clean_worktree(repo)

    actual = _identity_git(repo, "rev-parse", "--verify", "HEAD")
    _identity_need(actual == expected, "checkout does not match expected commit")
    tree = identity_commit_tree(repo, actual)
    base_tree = identity_commit_tree(repo, base)
    source_tree = identity_commit_tree(repo, source)
    identity_validate_repository(repo, base, repository_id, repository)
    identity_validate_repository(repo, source, repository_id, repository)
    lineage = identity_source_lineage(repo, base, source)
    source_parents = identity_commit_parents(repo, source)

    merge_candidate = None
    merge_tree = None
    merge_parents = None
    if kind == "source-head":
        _identity_need(actual == source, "source-head checkout does not match source")
        _identity_need(
            event_identity["eventName"] in {"pull_request", "push"},
            "source-head event",
        )
    else:
        _identity_need(
            event_identity["eventName"] == "pull_request",
            "merge candidate requires a pull request event",
        )
        merge_candidate = actual
        merge_tree = tree
        merge_parents = identity_commit_parents(repo, actual)
        _identity_need(
            merge_parents == [base, source],
            "merge candidate parent order",
        )
        _identity_need(
            merge_tree == identity_expected_merge_tree(repo, base, source),
            "merge candidate tree mismatch",
        )

    document_digest, document_count = identity_document_set_digest(repo, actual)
    timestamp = observed_at or (
        datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )
    _identity_observed_at(timestamp)
    receipt = {
        "schema": IDENTITY_RECEIPT_SCHEMA,
        "kind": kind,
        "repositoryId": repository_id,
        "repositoryFullName": repository,
        "baseCommit": base,
        "baseTree": base_tree,
        "sourceCommit": source,
        "sourceTree": source_tree,
        "sourceParents": source_parents,
        "sourceLineage": lineage,
        "sourceLineageDigest": identity_lineage_digest(lineage),
        "mergeCandidate": merge_candidate,
        "mergeTree": merge_tree,
        "mergeParents": merge_parents,
        "commit": actual,
        "tree": tree,
        "expectedCommit": expected,
        "eventIdentity": event_identity,
        "documentSetDigest": document_digest,
        "documentCount": document_count,
        "workflowPath": workflow_path,
        "workflowSha256": identity_blob_sha256(repo, actual, workflow_path),
        "verifierPath": IDENTITY_VERIFIER_PATH,
        "verifierSha256": identity_blob_sha256(
            repo,
            actual,
            IDENTITY_VERIFIER_PATH,
        ),
        "sourceRegistryVerifierPath": SOURCE_REGISTRY_VERIFIER_PATH,
        "sourceRegistryVerifierSha256": identity_blob_sha256(
            repo,
            actual,
            SOURCE_REGISTRY_VERIFIER_PATH,
        ),
        "qualificationManifestPath": QUALIFICATION_MANIFEST_PATH,
        "qualificationManifestSha256": identity_blob_sha256(
            repo,
            actual,
            QUALIFICATION_MANIFEST_PATH,
        ),
        "qualificationPlanAuditPath": QUALIFICATION_PLAN_AUDIT_PATH,
        "qualificationPlanAuditSha256": identity_blob_sha256(
            repo,
            actual,
            QUALIFICATION_PLAN_AUDIT_PATH,
        ),
        "observedAt": timestamp,
        "ttlSeconds": ttl_seconds,
        "decision": "exact_identity_verified",
        "workingTreeClean": True,
        "authorityGranted": False,
    }
    identity_require_clean_worktree(repo)
    _identity_need(
        _identity_git(repo, "rev-parse", "--verify", "HEAD") == actual,
        "checkout changed during identity verification",
    )
    return receipt


def _identity_observed_at(value: Any) -> datetime:
    _identity_need(
        isinstance(value, str) and UTC_TIMESTAMP_RE.fullmatch(value) is not None,
        "receipt observation timestamp",
    )
    raw = value[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError as error:
        raise ExactIdentityError("invalid receipt observation timestamp") from error
    _identity_need(parsed.tzinfo is not None, "receipt observation timezone")
    return parsed.astimezone(timezone.utc)


def verify_exact_identity_receipt(
    payload: dict[str, Any],
    **identity: Any,
) -> dict[str, Any]:
    _identity_need(isinstance(payload, dict), "receipt must contain an object")
    _identity_need(
        payload.get("schema") == IDENTITY_RECEIPT_SCHEMA,
        "receipt schema",
    )
    _identity_need(payload.get("authorityGranted") is False, "receipt authority")
    _identity_need(
        payload.get("decision") == "exact_identity_verified",
        "receipt decision",
    )
    observed = _identity_observed_at(payload.get("observedAt"))
    ttl = payload.get("ttlSeconds")
    _identity_need(
        type(ttl) is int and 0 < ttl <= MAX_RECEIPT_TTL_SECONDS,
        "receipt TTL",
    )
    now = datetime.now(timezone.utc)
    _identity_need(
        (observed - now).total_seconds() <= MAX_FUTURE_SKEW_SECONDS,
        "receipt timestamp exceeds future skew",
    )
    _identity_need(
        (now - observed).total_seconds() <= ttl,
        "receipt is stale",
    )
    expected = build_exact_identity_receipt(
        observed_at=payload["observedAt"],
        ttl_seconds=ttl,
        **identity,
    )
    _identity_need(set(payload) == set(expected), "receipt field set")
    for key, value in expected.items():
        _identity_need(payload.get(key) == value, "receipt mismatch: " + key)
    return expected


def _identity_external_path(
    raw_path: str,
    repo: Path,
    label: str,
    *,
    require_file: bool,
) -> Path:
    _identity_need(bool(raw_path), label + " path is required")
    target = Path(raw_path).resolve()
    root = repo.resolve()
    try:
        target.relative_to(root)
    except ValueError:
        pass
    else:
        raise ExactIdentityError(label + " must be outside the checkout")
    if require_file:
        _identity_need(target.is_file(), label + " is not a file")
    return target


def read_exact_identity_receipt(
    input_path: str,
    repo: Path = ROOT,
) -> dict[str, Any]:
    source = _identity_external_path(
        input_path,
        repo,
        "receipt input",
        require_file=True,
    )
    return _identity_load_json(source.read_bytes(), "identity receipt")


def write_exact_identity_receipt(
    output: str,
    payload: dict[str, Any],
    repo: Path = ROOT,
) -> None:
    target = _identity_external_path(
        output,
        repo,
        "receipt output",
        require_file=False,
    )
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary_name: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            dir=target.parent,
            prefix="." + target.name + ".",
            suffix=".tmp",
            delete=False,
        ) as temporary:
            temporary.write(_identity_canonical_json(payload) + b"\n")
            temporary.flush()
            os.fsync(temporary.fileno())
            temporary_name = temporary.name
        Path(temporary_name).replace(target)
    finally:
        if temporary_name is not None:
            Path(temporary_name).unlink(missing_ok=True)


def normalize_workspace() -> bool:
    text = CARGO_MANIFEST.read_text(encoding="utf-8")
    missing = [member for member in RUST_PACKAGES if f'    "{member}",\n' not in text]
    if not missing:
        return False
    anchor = '    "hepta-evidence",\n'
    if anchor not in text:
        raise RuntimeError("workspace member insertion anchor is missing")
    insertion = "".join(f'    "{member}",\n' for member in missing)
    CARGO_MANIFEST.write_text(
        text.replace(anchor, anchor + insertion, 1), encoding="utf-8"
    )
    return True


def normalize_ndu_helpers() -> bool:
    changed = False
    digest_path = ROOT / "codex-rs" / "hepta-ndu" / "src" / "evaluation_digest.rs"
    digest_text = digest_path.read_text(encoding="utf-8")
    public_axis_helper = (
        "pub(crate) fn push_axis_values(bytes: &mut Vec<u8>, values: &[AxisValue])"
    )
    if public_axis_helper not in digest_text:
        private_axis_helper = (
            "fn push_axis_values(bytes: &mut Vec<u8>, values: &[AxisValue])"
        )
        if private_axis_helper not in digest_text:
            raise RuntimeError("NDU axis digest helper signature is missing")
        digest_text = digest_text.replace(private_axis_helper, public_axis_helper, 1)
        changed = True
    if "\nfn push_id(bytes: &mut Vec<u8>, value: &StableId)" not in digest_text:
        digest_text += (
            "\nfn push_id(bytes: &mut Vec<u8>, value: &StableId) {\n"
            "    let raw = value.as_str().as_bytes();\n"
            "    push_len(bytes, raw.len());\n"
            "    bytes.extend_from_slice(raw);\n"
            "}\n\n"
            "fn push_len(bytes: &mut Vec<u8>, value: usize) {\n"
            "    let converted = u32::try_from(value).unwrap_or(u32::MAX);\n"
            "    bytes.extend_from_slice(&converted.to_be_bytes());\n"
            "}\n"
        )
        changed = True
    digest_path.write_text(digest_text, encoding="utf-8")

    evaluator_path = ROOT / "codex-rs" / "hepta-ndu" / "src" / "evaluator.rs"
    evaluator_text = evaluator_path.read_text(encoding="utf-8")
    if "use crate::AxisLimit;\n" not in evaluator_text:
        anchor = "use crate::AxisDirection;\n"
        if anchor not in evaluator_text:
            raise RuntimeError("NDU AxisDirection import anchor is missing")
        evaluator_text = evaluator_text.replace(
            anchor, anchor + "use crate::AxisLimit;\n", 1
        )
        changed = True
    if "use crate::evaluation_digest::push_axis_values;\n" not in evaluator_text:
        anchor = "use crate::evaluation_digest::digest_profile;\n"
        if anchor not in evaluator_text:
            raise RuntimeError("NDU digest import anchor is missing")
        evaluator_text = evaluator_text.replace(
            anchor,
            anchor + "use crate::evaluation_digest::push_axis_values;\n",
            1,
        )
        changed = True
    public_normalizer = "pub(crate) fn normalize_axis_values(values: &mut [AxisValue])"
    if public_normalizer not in evaluator_text:
        private_normalizer = "fn normalize_axis_values(values: &mut [AxisValue])"
        if private_normalizer not in evaluator_text:
            raise RuntimeError("NDU axis normalizer signature is missing")
        evaluator_text = evaluator_text.replace(
            private_normalizer, public_normalizer, 1
        )
        changed = True
    evaluator_path.write_text(evaluator_text, encoding="utf-8")

    scoring_path = ROOT / "codex-rs" / "hepta-ndu" / "src" / "scoring.rs"
    scoring_text = scoring_path.read_text(encoding="utf-8")
    normalizer_import = "use crate::evaluator::normalize_axis_values;\n"
    if normalizer_import not in scoring_text:
        anchor = "use crate::mul_q32_ties_even;\n"
        if anchor not in scoring_text:
            raise RuntimeError("NDU scoring import anchor is missing")
        scoring_text = scoring_text.replace(anchor, anchor + normalizer_import, 1)
        scoring_path.write_text(scoring_text, encoding="utf-8")
        changed = True

    return changed


def normalize_source() -> bool:
    workspace_changed = normalize_workspace()
    ndu_changed = normalize_ndu_helpers()
    registry_changed = normalize_source_registries()
    metadata_changed = bool(synchronize_module_metadata(ROOT, write=True))
    return workspace_changed or ndu_changed or registry_changed or metadata_changed


def verify() -> list[str]:
    failures: list[str] = []
    try:
        workspace_manifest = tomllib.loads(CARGO_MANIFEST.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError) as error:
        return [f"cannot parse codex-rs/Cargo.toml: {error}"]

    workspace = workspace_manifest.get("workspace")
    members = (
        set(workspace.get("members", ())) if isinstance(workspace, dict) else set()
    )
    for root_name, package_name in RUST_PACKAGES.items():
        root = ROOT / "codex-rs" / root_name
        for relative in ("Cargo.toml", "BUILD.bazel", "src/lib.rs"):
            path = root / relative
            if not path.is_file():
                failures.append(f"missing source file: {path.relative_to(ROOT)}")
        test_files = tuple((root / "src").glob("*_tests.rs"))
        if not test_files:
            failures.append(
                f"missing focused Rust tests under: {root.relative_to(ROOT)}"
            )
        manifest_path = root / "Cargo.toml"
        if manifest_path.is_file():
            try:
                manifest = tomllib.loads(manifest_path.read_text(encoding="utf-8"))
            except (OSError, tomllib.TOMLDecodeError) as error:
                failures.append(
                    f"invalid manifest {manifest_path.relative_to(ROOT)}: {error}"
                )
            else:
                package = manifest.get("package")
                if not isinstance(package, dict) or package.get("name") != package_name:
                    failures.append(
                        f"package identity mismatch for {root_name}: expected {package_name}"
                    )
                lints = manifest.get("lints")
                if not isinstance(lints, dict) or lints.get("workspace") is not True:
                    failures.append(f"workspace lints are not enabled for {root_name}")
        if root_name not in members:
            failures.append(f"workspace member is missing: {root_name}")
        lib_path = root / "src" / "lib.rs"
        if lib_path.is_file() and "#![forbid(unsafe_code)]" not in lib_path.read_text(
            encoding="utf-8"
        ):
            failures.append(f"unsafe-code prohibition is missing: {root_name}")

    for relative in REQUIRED_OTHER_FILES:
        if not (ROOT / relative).is_file():
            failures.append(f"missing required file: {relative}")

    bootstrap = ROOT / "qualification" / "value-learning" / "bootstrap"
    if bootstrap.exists():
        failures.append("temporary value-learning bootstrap payload was not removed")

    if QUALIFICATION_MANIFEST.is_file():
        try:
            manifest = json.loads(QUALIFICATION_MANIFEST.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            failures.append(f"invalid qualification manifest: {error}")
        else:
            if not isinstance(manifest, dict):
                failures.append("qualification manifest must contain an object")
                manifest = {}
            failures.extend(validate_static_candidate_manifest(manifest))
            authority = manifest.get("authority")
            if not isinstance(authority, dict):
                failures.append("qualification authority posture is missing")
            else:
                for flag in DENIED_AUTHORITY_FLAGS:
                    if authority.get(flag) is not False:
                        failures.append(f"authority flag must remain false: {flag}")
            expected_roots = sorted(f"codex-rs/{name}" for name in RUST_PACKAGES)
            expected_roots.extend(
                ["apps/hepta-control-ui", "tools/hepta-engineering-control"]
            )
            if sorted(manifest.get("source_roots", ())) != sorted(expected_roots):
                failures.append("qualification source inventory is not closed-world")

    if QUALIFICATION_PLAN_AUDIT.is_file():
        try:
            plan_audit = json.loads(
                QUALIFICATION_PLAN_AUDIT.read_text(encoding="utf-8")
            )
        except (OSError, json.JSONDecodeError) as error:
            failures.append(f"invalid qualification plan audit: {error}")
        else:
            if not isinstance(plan_audit, dict):
                failures.append("qualification plan audit must contain an object")
            else:
                if plan_audit.get("candidateIdentity") != STATIC_CANDIDATE_IDENTITY:
                    failures.append(
                        "qualification plan audit candidate identity is stale"
                    )
                leaks = static_identity_leaks(plan_audit)
                if leaks:
                    failures.append(
                        "qualification plan audit embeds dynamic candidate identity: "
                        + ", ".join(leaks)
                    )

    failures.extend(verify_source_registries())

    # Source presence cannot hide stale guides or a broken full module index.
    document_check = subprocess.run(
        [sys.executable, str(ROOT / "scripts/hepta-module-docs.py"), "verify"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    if document_check.returncode:
        failures.append(
            "module document integrity: "
            + (document_check.stderr or document_check.stdout).strip()
        )

    for relative in (
        "tools/hepta-engineering-control/hepta_engineering_control.py",
        "tools/hepta-engineering-control/test_hepta_engineering_control.py",
        "scripts/hepta-gap-closure.py",
        "scripts/hepta_source_registry_closure.py",
    ):
        path = ROOT / relative
        if path.is_file():
            try:
                compile(path.read_text(encoding="utf-8"), str(path), "exec")
            except SyntaxError as error:
                failures.append(f"python syntax error in {relative}: {error}")

    return failures


def emit_status() -> None:
    print(
        json.dumps(
            {
                "authority_granted": False,
                "candidate_identity": STATIC_CANDIDATE_IDENTITY,
                "implemented_modules": sorted(RUST_PACKAGES),
                "status": "verified_source_inventory",
            },
            sort_keys=True,
        )
    )


def _add_identity_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--kind",
        required=True,
        choices=("source-head", "merge-candidate"),
    )
    parser.add_argument("--repository-id", required=True, type=int)
    parser.add_argument("--repository", required=True)
    parser.add_argument("--base", required=True)
    parser.add_argument("--source", required=True)
    parser.add_argument("--expected", required=True)
    parser.add_argument("--workflow-path", required=True)
    parser.add_argument("--event-name", required=True)
    parser.add_argument("--event-path", required=True)


def _identity_cli_arguments(args: argparse.Namespace) -> dict[str, Any]:
    return {
        "base": args.base,
        "event_name": args.event_name,
        "event_path": args.event_path,
        "expected": args.expected,
        "kind": args.kind,
        "repository": args.repository,
        "repository_id": args.repository_id,
        "source": args.source,
        "workflow_path": args.workflow_path,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("normalize")
    subparsers.add_parser("verify")
    receipt_parser = subparsers.add_parser("identity-receipt")
    _add_identity_arguments(receipt_parser)
    receipt_parser.add_argument("--output", required=True)
    receipt_parser.add_argument(
        "--ttl-seconds",
        type=int,
        default=86400,
    )
    verify_parser = subparsers.add_parser("identity-verify")
    _add_identity_arguments(verify_parser)
    verify_parser.add_argument("--input", required=True)
    args = parser.parse_args()

    try:
        changed = normalize_source() if args.command == "normalize" else False
    except (OSError, RuntimeError, ExactIdentityError) as error:
        print(error, file=sys.stderr)
        return 1

    failures = verify()
    if failures:
        for failure in failures:
            print(f"- {failure}", file=sys.stderr)
        return 1

    if args.command in {"identity-receipt", "identity-verify"}:
        try:
            identity = _identity_cli_arguments(args)
            if args.command == "identity-receipt":
                payload = build_exact_identity_receipt(
                    ttl_seconds=args.ttl_seconds,
                    **identity,
                )
                write_exact_identity_receipt(args.output, payload)
                result = "PASS_HEPTA_EXACT_SOURCE_IDENTITY_RECEIPT"
            else:
                payload = read_exact_identity_receipt(args.input)
                verify_exact_identity_receipt(payload, **identity)
                result = "PASS_HEPTA_EXACT_SOURCE_IDENTITY_VERIFY"
        except (ExactIdentityError, OSError) as error:
            print(f"exact source identity: {error}", file=sys.stderr)
            return 1
        print(
            json.dumps(
                {
                    "authority_granted": False,
                    "result": result,
                },
                sort_keys=True,
            )
        )
        return 0

    emit_status()
    if args.command == "normalize":
        print(json.dumps({"source_changed": changed}, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
