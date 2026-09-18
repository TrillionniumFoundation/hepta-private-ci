"""Atomic multi-file candidate grammar for Lane G.

This is the production-facing successor to the single-Mutation pilot. A bundle is
content-addressed as one unit, may change multiple files or rename a file, and is
qualified with the same metadata-free source materialization and strong sandbox
boundary as candidate.py.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import asdict, dataclass
import hashlib
import os
from pathlib import Path
import tempfile
import time

from . import candidate as _candidate
from .control_plane import (
    EngineeringError,
    bounded_tuple,
    canonical_repo_path,
    canonical_json,
    path_is_within,
    semantic_digest,
)

BUNDLE_PROFILE = "hepta.engineering.candidate-bundle.v1"
MAX_OPERATIONS = 100


@dataclass(frozen=True)
class PatchOperation:
    operation: str
    path: str = ""
    target_path: str = ""
    expected_text: str = ""
    replacement_text: str = ""

    def normalized(self) -> "PatchOperation":
        if self.operation not in {"add_file", "replace_text", "delete_file", "rename_file"}:
            raise EngineeringError("unsupported_mutation")
        path = canonical_repo_path(self.path)
        target = canonical_repo_path(self.target_path) if self.target_path else ""
        if self.operation == "rename_file":
            if not target or target == path or self.replacement_text:
                raise EngineeringError("invalid_rename")
            if self.expected_text and (
                len(self.expected_text) != 64
                or any(ch not in "0123456789abcdef" for ch in self.expected_text)
            ):
                raise EngineeringError("invalid_rename_precondition")
        else:
            if target:
                raise EngineeringError("invalid_mutation_target")
            _candidate.Mutation(
                self.operation,
                path,
                self.expected_text,
                self.replacement_text,
            ).normalized()
        return PatchOperation(
            self.operation,
            path,
            target,
            self.expected_text,
            self.replacement_text,
        )


@dataclass(frozen=True)
class CandidateBundle:
    candidate_id: str
    envelope_id: str
    base_commit: str
    operations: tuple[PatchOperation, ...]
    semantic_digest: str
    state: str
    changed_paths: tuple[str, ...]
    sandbox_receipt_digest: str | None
    runtime_authority: bool = False
    merge_authority: bool = False
    selection_authority: bool = False
    release_authority: bool = False


def _normalize_operations(
    envelope: _candidate.CandidateEnvelope,
    operations: Iterable[PatchOperation],
) -> tuple[PatchOperation, ...]:
    roots, protected = _candidate._validate_envelope(envelope)
    values = bounded_tuple(operations, min(MAX_OPERATIONS, envelope.maximum_changed_files), "changed_file_limit")
    normalized = tuple(item.normalized() for item in values)
    touched: set[str] = set()
    for item in normalized:
        paths = (item.path,) if not item.target_path else (item.path, item.target_path)
        for path in paths:
            if not path_is_within(path, roots):
                raise EngineeringError("path_outside_candidate_envelope")
            if path_is_within(path, protected) or _candidate.is_immutable_oracle_path(path):
                raise EngineeringError("protected_oracle_path")
            touched.add(path)
    if len(touched) > envelope.maximum_changed_files:
        raise EngineeringError("changed_file_limit")
    return normalized


def _identity(
    envelope: _candidate.CandidateEnvelope,
    operations: tuple[PatchOperation, ...],
) -> tuple[str, str]:
    roots, protected = _candidate._validate_envelope(envelope)
    policy = asdict(envelope)
    policy["allowed_paths"] = roots
    policy["protected_paths"] = protected
    digest = semantic_digest(
        {
            "profile": BUNDLE_PROFILE,
            "envelope": policy,
            "operations": [asdict(item) for item in operations],
        }
    )
    return digest[:32], digest


def _declared_paths(operations: tuple[PatchOperation, ...]) -> tuple[str, ...]:
    values: set[str] = set()
    for item in operations:
        values.add(item.path)
        if item.target_path:
            values.add(item.target_path)
    return tuple(sorted(values))


def generate_candidate_bundle(
    envelope: _candidate.CandidateEnvelope,
    operations: Iterable[PatchOperation],
) -> CandidateBundle:
    values = _normalize_operations(envelope, operations)
    candidate_id, digest = _identity(envelope, values)
    return CandidateBundle(
        candidate_id,
        envelope.envelope_id,
        envelope.base_commit,
        values,
        digest,
        "no_change" if not values else "drafted",
        _declared_paths(values),
        None,
    )


def _apply_rename(workspace: Path, operation: PatchOperation) -> None:
    source = _candidate._safe_target(workspace, operation.path)
    target = _candidate._safe_target(workspace, operation.target_path)
    if not source.exists() or source.is_symlink() or not source.is_file():
        raise EngineeringError("mutation_target_invalid")
    if target.exists() or target.is_symlink():
        raise EngineeringError("add_target_exists")
    if operation.expected_text:
        digest = hashlib.sha256(source.read_bytes()).hexdigest()
        if digest != operation.expected_text:
            raise EngineeringError("rename_precondition_failed")
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.replace(source, target)
    except OSError:
        raise EngineeringError("mutation_target_invalid") from None


def _apply_operations(workspace: Path, operations: tuple[PatchOperation, ...]) -> None:
    for operation in operations:
        if operation.operation == "rename_file":
            _apply_rename(workspace, operation)
        else:
            _candidate._apply_mutation(
                workspace,
                _candidate.Mutation(
                    operation.operation,
                    operation.path,
                    operation.expected_text,
                    operation.replacement_text,
                ),
            )


def _checks(values: Iterable[Sequence[str]]) -> tuple[tuple[str, ...], ...]:
    raw = bounded_tuple(values, _candidate.MAX_CHECKS, "check_limit_exceeded")
    if not raw:
        raise EngineeringError("invalid_check")
    result: list[tuple[str, ...]] = []
    for check in raw:
        if (
            isinstance(check, (str, bytes))
            or not isinstance(check, Sequence)
            or not check
            or len(check) > _candidate.MAX_COMMAND_ARGUMENTS
            or any(
                not isinstance(item, str)
                or not item
                or "\x00" in item
                or len(item.encode("utf-8")) > _candidate.MAX_COMMAND_ARGUMENT_BYTES
                for item in check
            )
        ):
            raise EngineeringError("invalid_check")
        if sum(len(item.encode("utf-8")) for item in check) > _candidate.MAX_COMMAND_BYTES:
            raise EngineeringError("invalid_check")
        result.append(tuple(check))
    return tuple(result)


def sandbox_candidate_bundle(
    repository: str | Path,
    envelope: _candidate.CandidateEnvelope,
    bundle: CandidateBundle,
    checks: Iterable[Sequence[str]],
) -> tuple[CandidateBundle, _candidate.SandboxReceipt]:
    roots, protected = _candidate._validate_envelope(envelope)
    operations = _normalize_operations(envelope, bundle.operations)
    expected_id, expected_digest = _identity(envelope, operations)
    if (
        bundle.envelope_id != envelope.envelope_id
        or bundle.base_commit != envelope.base_commit
        or bundle.candidate_id != expected_id
        or bundle.semantic_digest != expected_digest
        or bundle.changed_paths != _declared_paths(operations)
        or bundle.state != ("no_change" if not operations else "drafted")
        or bundle.sandbox_receipt_digest is not None
        or any(
            (
                bundle.runtime_authority,
                bundle.merge_authority,
                bundle.selection_authority,
                bundle.release_authority,
            )
        )
    ):
        raise EngineeringError("candidate_envelope_mismatch")
    check_values = _checks(checks)
    check_set_digest = semantic_digest(check_values)
    try:
        root = Path(repository).resolve(strict=True)
    except OSError:
        raise EngineeringError("git_operation_failed") from None
    if _candidate._git(root, "rev-parse", "HEAD") != envelope.base_commit:
        raise EngineeringError("source_head_drift")
    source_tree = _candidate._git(root, "rev-parse", f"{envelope.base_commit}^{{tree}}")
    if not _candidate._valid_sha1(source_tree):
        raise EngineeringError("invalid_git_identity")
    source_boundary_before = _candidate._source_boundary_digest(root)
    start = time.monotonic_ns()

    with tempfile.TemporaryDirectory(prefix="hepta-lane-g-bundle-") as temporary_name:
        temporary = Path(temporary_name)
        workspace = temporary / "candidate"
        _candidate._materialize_exact_tree(root, envelope.base_commit, workspace)
        base_manifest = _candidate._tree_manifest(workspace)
        _apply_operations(workspace, operations)
        candidate_manifest = _candidate._tree_manifest(workspace)
        changed = _candidate._changed_paths(base_manifest, candidate_manifest)
        if changed != bundle.changed_paths:
            raise EngineeringError("candidate_changed_paths_mismatch")
        if len(changed) > envelope.maximum_changed_files:
            raise EngineeringError("changed_file_limit")
        if any(not path_is_within(path, roots) for path in changed):
            raise EngineeringError("sandbox_path_escape")
        if any(
            path_is_within(path, protected) or _candidate.is_immutable_oracle_path(path)
            for path in changed
        ):
            raise EngineeringError("protected_oracle_path")
        if _candidate._changed_byte_budget(base_manifest, candidate_manifest, changed) > envelope.maximum_diff_bytes:
            raise EngineeringError("diff_limit_exceeded")

        state_before = _candidate._manifest_digest(candidate_manifest)
        sandbox_home = temporary / "home"
        sandbox_tmp = temporary / "tmp"
        sandbox_home.mkdir()
        sandbox_tmp.mkdir()
        bubblewrap: str | None = None
        filesystem_isolated = False
        network_isolated = False
        adapter = "fixture-only"
        if envelope.require_network_isolation:
            bubblewrap = _candidate._admit_bubblewrap(workspace, envelope)
            filesystem_isolated = True
            network_isolated = True
            adapter = "bubblewrap-unshare-all-ro-workspace-v2"
        environment = _candidate._fixture_environment(sandbox_home, sandbox_tmp)
        credential_count = sum(
            1
            for key in environment
            if any(token in key.upper() for token in ("TOKEN", "SECRET", "KEY", "PASSWORD", "CREDENTIAL"))
        )
        results: list[tuple[str, int]] = []
        for check in check_values:
            elapsed = (time.monotonic_ns() - start) / 1_000_000_000
            remaining = envelope.wall_time_seconds - elapsed
            if remaining <= 0:
                raise EngineeringError("sandbox_time_budget_exceeded")
            label = hashlib.sha256(canonical_json(check)).hexdigest()[:16]
            argv = (
                _candidate._bubblewrap_command(bubblewrap, workspace, check)
                if bubblewrap is not None
                else list(check)
            )
            code = _candidate._run_bounded(
                argv,
                cwd=None if bubblewrap is not None else workspace,
                environment=None if bubblewrap is not None else environment,
                timeout=remaining,
                memory_bytes=envelope.memory_bytes,
                processes=envelope.processes,
            )
            results.append((label, code))
            if _candidate._source_boundary_digest(root) != source_boundary_before:
                raise EngineeringError("source_tree_mutated")
            if _candidate._tree_manifest(workspace) != candidate_manifest:
                raise EngineeringError("source_tree_mutated")
            if code != 0:
                break

        source_boundary_after = _candidate._source_boundary_digest(root)
        post_manifest = _candidate._tree_manifest(workspace)
        state_after = _candidate._manifest_digest(post_manifest)
        if source_boundary_after != source_boundary_before or post_manifest != candidate_manifest:
            raise EngineeringError("source_tree_mutated")
        source_after = _candidate._git(root, "rev-parse", f"{envelope.base_commit}^{{tree}}")
        if source_after != source_tree:
            raise EngineeringError("source_tree_mutated")
        passed = len(results) == len(check_values) and all(code == 0 for _, code in results)
        receipt = _candidate.SandboxReceipt(
            bundle.candidate_id,
            envelope.base_commit,
            source_tree,
            source_after,
            tuple(results),
            credential_count,
            network_isolated,
            (time.monotonic_ns() - start) // 1_000_000,
            passed,
            False,
            filesystem_isolated,
            adapter,
            check_set_digest,
            state_before,
            state_after,
            source_boundary_before,
            source_boundary_after,
        )
        receipt_digest = semantic_digest(asdict(receipt))
        state = "sandbox_tested" if passed and filesystem_isolated and network_isolated else ("fixture_tested" if passed else "rejected")
        return (
            CandidateBundle(
                bundle.candidate_id,
                envelope.envelope_id,
                envelope.base_commit,
                operations,
                bundle.semantic_digest,
                state,
                changed,
                receipt_digest,
            ),
            receipt,
        )
