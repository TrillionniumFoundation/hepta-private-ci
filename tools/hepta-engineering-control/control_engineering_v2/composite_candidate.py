"""Atomic multi-file candidate grammar for Lane G.

The original single-mutation Candidate API remains as a compatibility surface.
Product orchestration uses CompositeCandidate when a coherent change spans more
than one file. The complete mutation batch is identity-bound and sandboxed as
one workspace state.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import asdict, dataclass
import hashlib
from pathlib import Path
import tempfile
import time

from . import candidate as _candidate
from .control_plane import EngineeringError, bounded_tuple, canonical_json, path_is_within, semantic_digest
from .oracle_policy import is_oracle_path
from .sandbox_control import sandbox_admission, run_with_infrastructure_retries

MAX_MUTATIONS_PER_CANDIDATE = 100


@dataclass(frozen=True)
class CompositeCandidate:
    candidate_id: str
    envelope_id: str
    base_commit: str
    mutations: tuple[_candidate.Mutation, ...]
    semantic_digest: str
    state: str
    changed_paths: tuple[str, ...]
    sandbox_receipt_digest: str | None
    runtime_authority: bool = False
    merge_authority: bool = False
    selection_authority: bool = False
    release_authority: bool = False


def _normalize_batch(values: Iterable[_candidate.Mutation]) -> tuple[_candidate.Mutation, ...]:
    raw = bounded_tuple(
        values, MAX_MUTATIONS_PER_CANDIDATE, "mutation_batch_limit_exceeded"
    )
    if not raw or any(not isinstance(value, _candidate.Mutation) for value in raw):
        raise EngineeringError("invalid_mutation_batch")
    normalized = tuple(value.normalized() for value in raw)
    if any(value.operation == "no_change" for value in normalized):
        if len(normalized) != 1:
            raise EngineeringError("invalid_no_change_batch")
        return normalized
    paths = [value.path for value in normalized]
    if len(paths) != len(set(paths)):
        raise EngineeringError("duplicate_mutation_path")
    if any(is_oracle_path(path) for path in paths):
        raise EngineeringError("protected_oracle_path")
    return normalized


def _identity(
    envelope: _candidate.CandidateEnvelope,
    mutations: tuple[_candidate.Mutation, ...],
) -> tuple[str, str]:
    roots, protected = _candidate._validate_envelope(envelope)
    policy = asdict(envelope)
    policy["allowed_paths"] = roots
    policy["protected_paths"] = protected
    digest = semantic_digest(
        {
            "profile": "hepta.engineering.composite-candidate.v1",
            "envelope": policy,
            "mutations": [asdict(value) for value in mutations],
        }
    )
    return digest[:32], digest


def generate_composite_candidates(
    envelope: _candidate.CandidateEnvelope,
    mutation_batches: Iterable[Iterable[_candidate.Mutation]],
) -> tuple[CompositeCandidate, ...]:
    roots, protected = _candidate._validate_envelope(envelope)
    batches = bounded_tuple(
        mutation_batches,
        envelope.maximum_candidates - 1,
        "candidate_limit_exceeded",
    )
    normalized_batches = [_normalize_batch(batch) for batch in batches]
    result: list[CompositeCandidate] = []
    seen: set[str] = set()
    for mutations in ((_candidate.Mutation("no_change"),), *normalized_batches):
        if mutations[0].operation != "no_change":
            for mutation in mutations:
                if not path_is_within(mutation.path, roots):
                    raise EngineeringError("path_outside_candidate_envelope")
                if path_is_within(mutation.path, protected):
                    raise EngineeringError("protected_path")
                if is_oracle_path(mutation.path):
                    raise EngineeringError("protected_oracle_path")
        candidate_id, digest = _identity(envelope, mutations)
        if digest in seen:
            continue
        seen.add(digest)
        result.append(
            CompositeCandidate(
                candidate_id,
                envelope.envelope_id,
                envelope.base_commit,
                mutations,
                digest,
                "no_change" if mutations[0].operation == "no_change" else "drafted",
                ()
                if mutations[0].operation == "no_change"
                else tuple(sorted(value.path for value in mutations)),
                None,
            )
        )
    return tuple(result)


def _sandbox_once(
    repository: str | Path,
    envelope: _candidate.CandidateEnvelope,
    candidate: CompositeCandidate,
    checks: Iterable[Sequence[str]],
) -> tuple[CompositeCandidate, _candidate.SandboxReceipt]:
    roots, protected = _candidate._validate_envelope(envelope)
    mutations = _normalize_batch(candidate.mutations)
    expected_id, expected_digest = _identity(envelope, mutations)
    declared_paths = (
        ()
        if mutations[0].operation == "no_change"
        else tuple(sorted(value.path for value in mutations))
    )
    expected_state = "no_change" if mutations[0].operation == "no_change" else "drafted"
    if (
        candidate.envelope_id != envelope.envelope_id
        or candidate.base_commit != envelope.base_commit
        or candidate.candidate_id != expected_id
        or candidate.semantic_digest != expected_digest
        or candidate.changed_paths != declared_paths
        or candidate.state != expected_state
        or candidate.sandbox_receipt_digest is not None
        or any(
            (
                candidate.runtime_authority,
                candidate.merge_authority,
                candidate.selection_authority,
                candidate.release_authority,
            )
        )
    ):
        raise EngineeringError("candidate_envelope_mismatch")

    raw_checks = bounded_tuple(checks, _candidate.MAX_CHECKS, "check_limit_exceeded")
    if not raw_checks:
        raise EngineeringError("invalid_check")
    check_values: list[tuple[str, ...]] = []
    for check in raw_checks:
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
            or sum(len(item.encode("utf-8")) for item in check)
            > _candidate.MAX_COMMAND_BYTES
        ):
            raise EngineeringError("invalid_check")
        check_values.append(tuple(check))
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

    with tempfile.TemporaryDirectory(prefix="hepta-lane-g-composite-") as temporary_name:
        temporary = Path(temporary_name)
        workspace = temporary / "candidate"
        _candidate._materialize_exact_tree(root, envelope.base_commit, workspace)
        base_manifest = _candidate._tree_manifest(workspace)
        for mutation in mutations:
            _candidate._apply_mutation(workspace, mutation)
        candidate_manifest = _candidate._tree_manifest(workspace)
        changed = _candidate._changed_paths(base_manifest, candidate_manifest)
        if changed != declared_paths:
            raise EngineeringError("sandbox_path_escape")
        if len(changed) > envelope.maximum_changed_files:
            raise EngineeringError("changed_file_limit")
        if any(not path_is_within(path, roots) for path in changed):
            raise EngineeringError("sandbox_path_escape")
        if any(path_is_within(path, protected) for path in changed):
            raise EngineeringError("protected_path")
        if any(is_oracle_path(path) for path in changed):
            raise EngineeringError("protected_oracle_path")
        if (
            _candidate._changed_byte_budget(base_manifest, candidate_manifest, changed)
            > envelope.maximum_diff_bytes
        ):
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
            if any(
                token in key.upper()
                for token in ("TOKEN", "SECRET", "KEY", "PASSWORD", "CREDENTIAL")
            )
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
        if source_boundary_after != source_boundary_before:
            raise EngineeringError("source_tree_mutated")
        post_manifest = _candidate._tree_manifest(workspace)
        state_after = _candidate._manifest_digest(post_manifest)
        if post_manifest != candidate_manifest or state_after != state_before:
            raise EngineeringError("source_tree_mutated")
        source_after = _candidate._git(root, "rev-parse", f"{envelope.base_commit}^{{tree}}")
        if source_after != source_tree:
            raise EngineeringError("source_tree_mutated")
        passed = len(results) == len(check_values) and all(code == 0 for _, code in results)
        receipt = _candidate.SandboxReceipt(
            candidate.candidate_id,
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
        state = (
            "sandbox_tested"
            if passed and filesystem_isolated and network_isolated
            else "fixture_tested"
            if passed
            else "rejected"
        )
        return (
            CompositeCandidate(
                candidate.candidate_id,
                envelope.envelope_id,
                envelope.base_commit,
                mutations,
                candidate.semantic_digest,
                state,
                changed,
                receipt_digest,
            ),
            receipt,
        )


def sandbox_composite_candidate(
    repository: str | Path,
    envelope: _candidate.CandidateEnvelope,
    candidate: CompositeCandidate,
    checks: Iterable[Sequence[str]],
) -> tuple[CompositeCandidate, _candidate.SandboxReceipt]:
    with sandbox_admission():
        return run_with_infrastructure_retries(
            lambda: _sandbox_once(repository, envelope, candidate, checks)
        )
