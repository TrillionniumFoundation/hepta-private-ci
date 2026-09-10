"""Fail-closed repository-owned hardening for Lane G engineering control.

The V2 implementation deliberately stops before independent acceptance, merge,
activation, promotion, release, deployment, peer enrollment, credential
propagation, or runtime authority.  This module strengthens the boundaries that
must nevertheless be enforced by repository-owned source:

* every owner mutation starts with ``BEGIN IMMEDIATE``;
* assignment generations bind an immutable envelope/lease frontier;
* candidate checks are non-empty and execute in a detached local clone rather
  than a worktree sharing the source repository's Git directory;
* exact evidence must receive a separately signed candidate binding before it
  can create a review request or an eligible persisted decision; and
* external-owner consent plus sandbox parity are authenticated before a dormant
  assimilation proposal can be composed.
"""
from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import asdict, dataclass
import functools
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import time
from typing import Any

from . import assimilation as _assimilation
from . import candidate as _candidate
from . import control_plane as _control
from . import facade as _facade
from .evidence import EvidenceDecision, ExecutionReceipt, HmacTrustStore

_SHA1 = re.compile(r"[0-9a-f]{40}\Z")
_MAX_COMMAND_ARGUMENT_BYTES = 8_192
_MAX_COMMAND_BYTES = 65_536
_STORE_SCHEMA_VERSION = 3


# ---------------------------------------------------------------------------
# Stable fail-closed error identity
# ---------------------------------------------------------------------------

def _engineering_error_init(self: _control.EngineeringError, code: str) -> None:
    if not isinstance(code, str) or not code or len(code.encode("utf-8")) > 256:
        code = "invalid_engineering_error_code"
    ValueError.__init__(self, code)
    self.code = code


def _install_error_identity() -> None:
    # Evidence validation consumes ``error.code``.  The original ValueError
    # subclass did not retain it, turning malformed evidence into AttributeError.
    _control.EngineeringError.__init__ = _engineering_error_init  # type: ignore[method-assign]


# ---------------------------------------------------------------------------
# SQLite transaction and assignment-frontier hardening
# ---------------------------------------------------------------------------

_ORIGINAL_STORE_INIT = _control.EngineeringStore.__init__
_ORIGINAL_ISSUE_ENVELOPE = _control.EngineeringStore.issue_work_envelope
_ORIGINAL_ACQUIRE_LEASE = _control.EngineeringStore.acquire_path_lease
_ORIGINAL_TRANSITION_LEASE = _control.EngineeringStore.transition_path_lease
_ORIGINAL_SCHEDULE = _control.EngineeringStore.schedule_ready_packages
_ORIGINAL_RECORD_DECISION = _control.EngineeringStore.record_integration_decision


def _install_store_schema(store: _control.EngineeringStore) -> None:
    store.connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS engineering_schema_meta(
          singleton INTEGER PRIMARY KEY CHECK(singleton=1),
          schema_version INTEGER NOT NULL CHECK(schema_version>=1),
          updated_unix_ns INTEGER NOT NULL
        );
        CREATE TABLE IF NOT EXISTS assignment_generation_frontiers(
          generation_id TEXT PRIMARY KEY,
          envelope_id TEXT NOT NULL,
          envelope_revision INTEGER NOT NULL CHECK(envelope_revision>=1),
          source_commit TEXT NOT NULL,
          source_tree TEXT NOT NULL,
          frontier_digest TEXT NOT NULL,
          created_unix_ns INTEGER NOT NULL,
          FOREIGN KEY(generation_id)
            REFERENCES assignment_generations(generation_id)
            DEFERRABLE INITIALLY DEFERRED,
          FOREIGN KEY(envelope_id) REFERENCES work_envelopes(envelope_id)
        );
        """
    )
    now = time.time_ns()
    row = store.connection.execute(
        "SELECT schema_version FROM engineering_schema_meta WHERE singleton=1"
    ).fetchone()
    if row is not None and int(row[0]) > _STORE_SCHEMA_VERSION:
        raise _control.EngineeringError("unsupported_future_store_schema")
    store.connection.execute(
        "INSERT INTO engineering_schema_meta(singleton,schema_version,updated_unix_ns) "
        "VALUES(1,?,?) ON CONFLICT(singleton) DO UPDATE SET "
        "schema_version=excluded.schema_version,updated_unix_ns=excluded.updated_unix_ns",
        (_STORE_SCHEMA_VERSION, now),
    )
    store.connection.execute(f"PRAGMA user_version={_STORE_SCHEMA_VERSION}")
    store.connection.commit()


def _hardened_store_init(self: _control.EngineeringStore, database: str | Path) -> None:
    _ORIGINAL_STORE_INIT(self, database)
    try:
        _install_store_schema(self)
    except BaseException:
        self.connection.close()
        raise


def _run_immediate(
    store: _control.EngineeringStore,
    operation: Callable[[], Any],
) -> Any:
    connection = store.connection
    if connection.in_transaction:
        raise _control.EngineeringError("nested_engineering_transaction")
    connection.execute("BEGIN IMMEDIATE")
    try:
        value = operation()
    except BaseException:
        if connection.in_transaction:
            connection.rollback()
        raise
    if connection.in_transaction:
        connection.commit()
    return value


def _immediate_wrapper(method: Callable[..., Any]) -> Callable[..., Any]:
    @functools.wraps(method)
    def wrapped(self: _control.EngineeringStore, *args: Any, **kwargs: Any) -> Any:
        return _run_immediate(self, lambda: method(self, *args, **kwargs))

    return wrapped


def _lease_frontier(
    store: _control.EngineeringStore,
    envelope: Any,
    now_ns: int,
) -> str:
    rows = store.connection.execute(
        "SELECT lease_id,envelope_id,holder,paths_json,state,authority_epoch,"
        "fencing_token,revision,issued_unix_ns,expires_unix_ns,semantic_digest "
        "FROM path_leases WHERE state='active' AND expires_unix_ns>? "
        "ORDER BY fencing_token,lease_id",
        (now_ns,),
    ).fetchall()
    leases = []
    for row in rows:
        leases.append(
            {
                "leaseId": str(row["lease_id"]),
                "envelopeId": str(row["envelope_id"]),
                "holder": str(row["holder"]),
                "paths": json.loads(bytes(row["paths_json"]).decode("utf-8")),
                "state": str(row["state"]),
                "authorityEpoch": int(row["authority_epoch"]),
                "fencingToken": int(row["fencing_token"]),
                "revision": int(row["revision"]),
                "issuedUnixNs": int(row["issued_unix_ns"]),
                "expiresUnixNs": int(row["expires_unix_ns"]),
                "semanticDigest": str(row["semantic_digest"]),
            }
        )
    return _control.semantic_digest(
        {
            "envelopeId": str(envelope["envelope_id"]),
            "envelopeSemanticDigest": str(envelope["semantic_digest"]),
            "envelopeRevision": int(envelope["revision"]),
            "sourceCommit": str(envelope["source_commit"]),
            "sourceTree": str(envelope["source_tree"]),
            "activeLeases": leases,
        }
    )


def _hardened_schedule(
    self: _control.EngineeringStore,
    envelope_id: str,
    packages: Iterable[_control.WorkPackage],
    completed: Iterable[str],
    *,
    generation_id: str,
    now_ns: int | None = None,
) -> _control.ScheduleReceipt:
    _control.checked_id(generation_id, "generation_id")
    now = self._now(now_ns)

    def operation() -> _control.ScheduleReceipt:
        self._expire_leases(now)
        envelope = self._get_envelope(envelope_id, now)
        frontier = _lease_frontier(self, envelope, now)
        current = self.connection.execute(
            "SELECT frontier_digest FROM assignment_generation_frontiers "
            "WHERE generation_id=?",
            (generation_id,),
        ).fetchone()
        assignment_exists = self.connection.execute(
            "SELECT 1 FROM assignment_generations WHERE generation_id=?",
            (generation_id,),
        ).fetchone()
        if current is None and assignment_exists is not None:
            raise _control.EngineeringError("unbound_legacy_generation")
        if current is not None and str(current[0]) != frontier:
            raise _control.EngineeringError("generation_frontier_conflict")
        if current is None:
            self.connection.execute(
                "INSERT INTO assignment_generation_frontiers("
                "generation_id,envelope_id,envelope_revision,source_commit,source_tree,"
                "frontier_digest,created_unix_ns) VALUES(?,?,?,?,?,?,?)",
                (
                    generation_id,
                    envelope_id,
                    int(envelope["revision"]),
                    str(envelope["source_commit"]),
                    str(envelope["source_tree"]),
                    frontier,
                    now,
                ),
            )
        return _ORIGINAL_SCHEDULE(
            self,
            envelope_id,
            packages,
            completed,
            generation_id=generation_id,
            now_ns=now,
        )

    return _run_immediate(self, operation)


def assignment_frontier(
    store: _control.EngineeringStore,
    generation_id: str,
) -> Mapping[str, object]:
    _control.checked_id(generation_id, "generation_id")
    row = store.connection.execute(
        "SELECT * FROM assignment_generation_frontiers WHERE generation_id=?",
        (generation_id,),
    ).fetchone()
    if row is None:
        raise _control.EngineeringError("unknown_assignment_frontier")
    return {
        "generationId": str(row["generation_id"]),
        "envelopeId": str(row["envelope_id"]),
        "envelopeRevision": int(row["envelope_revision"]),
        "sourceCommit": str(row["source_commit"]),
        "sourceTree": str(row["source_tree"]),
        "frontierDigest": str(row["frontier_digest"]),
        "createdUnixNs": int(row["created_unix_ns"]),
    }


# ---------------------------------------------------------------------------
# Candidate sandbox hardening
# ---------------------------------------------------------------------------

def _run_bytes(
    argv: Sequence[str],
    *,
    cwd: Path,
    timeout: int = 60,
    check: bool = True,
    environment: Mapping[str, str] | None = None,
) -> bytes:
    try:
        result = subprocess.run(
            list(argv),
            cwd=cwd,
            env=dict(environment) if environment is not None else None,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        raise _control.EngineeringError("sandbox_process_failed") from None
    if check and result.returncode != 0:
        raise _control.EngineeringError("sandbox_process_failed")
    if len(result.stdout) > 4_194_304 or len(result.stderr) > 4_194_304:
        raise _control.EngineeringError("sandbox_process_output_limit")
    return result.stdout


def _git_bytes(root: Path, *args: str, check: bool = True) -> bytes:
    return _run_bytes(("git", "-C", str(root), *args), cwd=root, check=check)


def _git_text(root: Path, *args: str) -> str:
    try:
        return _git_bytes(root, *args).decode("utf-8", errors="strict").strip()
    except UnicodeDecodeError:
        raise _control.EngineeringError("git_output_not_utf8") from None


def _repository_status(root: Path) -> bytes:
    return _git_bytes(root, "status", "--porcelain=v1", "-z", "--untracked-files=all")


def _repository_refs_digest(root: Path) -> str:
    value = _git_bytes(
        root,
        "for-each-ref",
        "--format=%(refname)%00%(objectname)%00%(symref)",
    )
    return hashlib.sha256(value).hexdigest()


def _status_paths(root: Path) -> tuple[str, ...]:
    output = _repository_status(root)
    result: list[str] = []
    for record in output.split(b"\x00"):
        if not record:
            continue
        if len(record) < 4 or record[2:3] != b" ":
            raise _control.EngineeringError("invalid_git_status_record")
        try:
            status = record[:2].decode("ascii")
            path = record[3:].decode("utf-8", errors="strict")
        except UnicodeDecodeError:
            raise _control.EngineeringError("invalid_git_status_record") from None
        if "R" in status or "C" in status:
            raise _control.EngineeringError("unsupported_changed_entry")
        result.append(_control.canonical_repo_path(path))
    return tuple(sorted(set(result)))


def _read_old_blob(root: Path, relative: str, maximum: int) -> bytes:
    spec = f"HEAD:{relative}"
    size_result = subprocess.run(
        ["git", "-C", str(root), "cat-file", "-s", spec],
        cwd=root,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        timeout=30,
        check=False,
    )
    if size_result.returncode != 0:
        return b""
    try:
        size = int(size_result.stdout.decode("ascii").strip())
    except (UnicodeDecodeError, ValueError):
        raise _control.EngineeringError("invalid_git_blob_size") from None
    if size < 0 or size > maximum:
        raise _control.EngineeringError("diff_limit_exceeded")
    value = _git_bytes(root, "show", spec)
    if len(value) != size:
        raise _control.EngineeringError("git_blob_size_drift")
    return value


def _candidate_content_digest(root: Path, paths: Sequence[str]) -> str:
    rows: list[dict[str, object]] = []
    for relative in paths:
        target = root.joinpath(*relative.split("/"))
        if target.is_symlink():
            raise _control.EngineeringError("unsupported_changed_entry")
        if target.exists():
            if not target.is_file():
                raise _control.EngineeringError("unsupported_changed_entry")
            value = target.read_bytes()
            rows.append(
                {
                    "path": relative,
                    "present": True,
                    "size": len(value),
                    "digest": hashlib.sha256(value).hexdigest(),
                }
            )
        else:
            rows.append({"path": relative, "present": False})
    return _control.semantic_digest(rows)


def _validate_changed_budget(
    root: Path,
    paths: Sequence[str],
    maximum: int,
) -> None:
    total = 0
    for relative in paths:
        old = _read_old_blob(root, relative, maximum)
        target = root.joinpath(*relative.split("/"))
        new = b""
        if target.exists():
            if not target.is_file() or target.is_symlink():
                raise _control.EngineeringError("unsupported_changed_entry")
            if target.stat().st_size > maximum:
                raise _control.EngineeringError("diff_limit_exceeded")
            new = target.read_bytes()
        for value in (old, new):
            try:
                value.decode("utf-8", errors="strict")
            except UnicodeDecodeError:
                raise _control.EngineeringError("binary_change_rejected") from None
        total += len(old) + len(new)
        if total > maximum:
            raise _control.EngineeringError("diff_limit_exceeded")


def _validated_checks(
    checks: Iterable[Sequence[str]],
    source_root: Path,
) -> tuple[tuple[str, ...], ...]:
    raw = _control.bounded_tuple(checks, _candidate.MAX_CHECKS, "check_limit_exceeded")
    if not raw:
        raise _control.EngineeringError("mandatory_checks_missing")
    result: list[tuple[str, ...]] = []
    for check in raw:
        if isinstance(check, (str, bytes)) or not isinstance(check, Sequence) or not check:
            raise _control.EngineeringError("invalid_check")
        values = tuple(str(item) for item in check)
        encoded = 0
        for item in values:
            if not item or "\x00" in item:
                raise _control.EngineeringError("invalid_check")
            length = len(item.encode("utf-8"))
            if length > _MAX_COMMAND_ARGUMENT_BYTES:
                raise _control.EngineeringError("check_argument_limit")
            encoded += length
            candidate = Path(item)
            if candidate.is_absolute():
                try:
                    candidate.resolve().relative_to(source_root)
                except ValueError:
                    pass
                else:
                    raise _control.EngineeringError("source_path_in_check_argv")
        if encoded > _MAX_COMMAND_BYTES:
            raise _control.EngineeringError("check_command_limit")
        result.append(values)
    return tuple(result)


def hardened_sandbox_candidate(
    repository: str | Path,
    envelope: _candidate.CandidateEnvelope,
    candidate: _candidate.Candidate,
    checks: Iterable[Sequence[str]],
) -> tuple[_candidate.Candidate, _candidate.SandboxReceipt]:
    roots, protected = _candidate._validate_envelope(envelope)
    _control.checked_id(envelope.envelope_id, "envelope_id")
    if not isinstance(envelope.base_commit, str) or _SHA1.fullmatch(envelope.base_commit) is None:
        raise _control.EngineeringError("invalid_base_commit")
    if candidate.envelope_id != envelope.envelope_id or candidate.base_commit != envelope.base_commit:
        raise _control.EngineeringError("candidate_envelope_mismatch")
    if candidate.state not in {"drafted", "no_change"} or candidate.sandbox_receipt_digest is not None:
        raise _control.EngineeringError("invalid_candidate_state")
    expected_id, expected_digest = _candidate._candidate_identity(envelope, candidate.mutation)
    if candidate.candidate_id != expected_id or candidate.semantic_digest != expected_digest:
        raise _control.EngineeringError("candidate_identity_mismatch")

    source_root = Path(repository).resolve()
    check_values = _validated_checks(checks, source_root)
    source_commit = _git_text(source_root, "rev-parse", "HEAD")
    source_tree_before = _git_text(source_root, "rev-parse", "HEAD^{tree}")
    if source_commit != envelope.base_commit:
        raise _control.EngineeringError("source_head_drift")
    if _repository_status(source_root):
        raise _control.EngineeringError("source_repository_dirty")
    source_refs_before = _repository_refs_digest(source_root)
    started = time.monotonic_ns()

    with tempfile.TemporaryDirectory(prefix="hepta-lane-g-isolated-") as temporary:
        temporary_root = Path(temporary)
        clone = temporary_root / "candidate"
        clone_environment = {
            "PATH": os.environ.get("PATH", ""),
            "HOME": str(temporary_root / "clone-home"),
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_TERMINAL_PROMPT": "0",
        }
        Path(clone_environment["HOME"]).mkdir()
        _run_bytes(
            (
                "git",
                "clone",
                "--no-local",
                "--no-hardlinks",
                "--no-checkout",
                "--",
                str(source_root),
                str(clone),
            ),
            cwd=temporary_root,
            timeout=180,
            environment=clone_environment,
        )
        _git_bytes(clone, "remote", "remove", "origin")
        empty_hooks = temporary_root / "empty-hooks"
        empty_hooks.mkdir()
        _git_bytes(clone, "config", "core.hooksPath", str(empty_hooks))
        _git_bytes(clone, "config", "credential.helper", "")
        _git_bytes(clone, "checkout", "--detach", envelope.base_commit)
        if _git_text(clone, "rev-parse", "HEAD") != envelope.base_commit:
            raise _control.EngineeringError("sandbox_base_drift")

        _candidate._apply_mutation(clone, candidate.mutation)
        changed = _status_paths(clone)
        expected_paths = () if candidate.mutation.operation == "no_change" else (candidate.mutation.path,)
        if changed != expected_paths:
            raise _control.EngineeringError("candidate_changed_path_mismatch")
        if len(changed) > envelope.maximum_changed_files:
            raise _control.EngineeringError("changed_file_limit")
        if any(not _control.path_is_within(path, roots) for path in changed):
            raise _control.EngineeringError("sandbox_path_escape")
        if any(_control.path_is_within(path, protected) for path in changed):
            raise _control.EngineeringError("protected_path")
        _validate_changed_budget(clone, changed, envelope.maximum_diff_bytes)
        mutation_digest = _candidate_content_digest(clone, changed)

        prefix: list[str] = []
        network_isolated = False
        if envelope.require_network_isolation:
            unshare = shutil.which("unshare")
            if not sys.platform.startswith("linux") or unshare is None:
                raise _control.EngineeringError("network_isolation_unavailable")
            prefix = [unshare, "--net", "--"]
            network_isolated = True

        sandbox_home = temporary_root / "home"
        sandbox_tmp = temporary_root / "tmp"
        sandbox_home.mkdir()
        sandbox_tmp.mkdir()
        environment = {
            "PATH": os.environ.get("PATH", ""),
            "HOME": str(sandbox_home),
            "TMPDIR": str(sandbox_tmp),
            "TEMP": str(sandbox_tmp),
            "TMP": str(sandbox_tmp),
            "LANG": "C",
            "LC_ALL": "C",
            "NO_PROXY": "*",
            "HTTP_PROXY": "http://127.0.0.1:9",
            "HTTPS_PROXY": "http://127.0.0.1:9",
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_TERMINAL_PROMPT": "0",
            "PYTHONDONTWRITEBYTECODE": "1",
        }
        credential_count = sum(
            1
            for key in environment
            if any(token in key.upper() for token in ("TOKEN", "SECRET", "PASSWORD", "CREDENTIAL"))
        )
        results: list[tuple[str, int]] = []
        for check in check_values:
            label = hashlib.sha256(_control.canonical_json(check)).hexdigest()[:16]
            try:
                run = subprocess.run(
                    [*prefix, *check],
                    cwd=clone,
                    env=environment,
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    timeout=envelope.wall_time_seconds,
                    check=False,
                    preexec_fn=_candidate._resource_limiter(
                        envelope.memory_bytes,
                        envelope.processes,
                        envelope.wall_time_seconds,
                    )
                    if os.name == "posix"
                    else None,
                )
                code = run.returncode
            except subprocess.TimeoutExpired:
                code = 124
            except OSError:
                code = 127
            results.append((label, code))
            if code != 0:
                break

        post_changed = _status_paths(clone)
        if post_changed != changed or _candidate_content_digest(clone, post_changed) != mutation_digest:
            raise _control.EngineeringError("sandbox_candidate_mutated_by_check")
        _validate_changed_budget(clone, post_changed, envelope.maximum_diff_bytes)
        passed = len(results) == len(check_values) and all(code == 0 for _, code in results)

    source_tree_after = _git_text(source_root, "rev-parse", "HEAD^{tree}")
    if _git_text(source_root, "rev-parse", "HEAD") != envelope.base_commit:
        raise _control.EngineeringError("source_head_drift")
    if source_tree_after != source_tree_before:
        raise _control.EngineeringError("source_tree_mutated")
    if _repository_status(source_root):
        raise _control.EngineeringError("source_repository_dirty_after_sandbox")
    if _repository_refs_digest(source_root) != source_refs_before:
        raise _control.EngineeringError("source_refs_mutated")

    receipt = _candidate.SandboxReceipt(
        candidate.candidate_id,
        envelope.base_commit,
        source_tree_before,
        source_tree_after,
        tuple(results),
        credential_count,
        network_isolated,
        (time.monotonic_ns() - started) // 1_000_000,
        passed,
    )
    receipt_digest = _control.semantic_digest(asdict(receipt))
    return (
        _candidate.Candidate(
            candidate.candidate_id,
            candidate.envelope_id,
            candidate.base_commit,
            candidate.mutation,
            candidate.semantic_digest,
            "sandbox_tested" if passed else "rejected",
            changed,
            receipt_digest,
        ),
        receipt,
    )


def hardened_execute_candidate_sandbox(
    repository: str | Path,
    envelope: _candidate.CandidateEnvelope,
    candidate: _candidate.Candidate,
    checks: Iterable[Sequence[str]],
) -> tuple[_candidate.Candidate, _candidate.SandboxReceipt]:
    return hardened_sandbox_candidate(repository, envelope, candidate, checks)


# ---------------------------------------------------------------------------
# Candidate-bound evidence and independent-review transition
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class CandidateEvidenceBindingReceipt:
    candidate_id: str
    candidate_digest: str
    sandbox_receipt_digest: str
    base_commit: str
    evidence_digest: str
    source_execution_digest: str
    merge_execution_digest: str
    issuer: str
    signing_identity: str
    observed_unix_ns: int
    expires_unix_ns: int
    signature: str = ""


@dataclass(frozen=True)
class BoundEvidenceDecision:
    eligible_for_independent_review: bool
    reasons: tuple[str, ...]
    evidence_digest: str
    candidate_id: str
    candidate_digest: str
    sandbox_receipt_digest: str
    binding_receipt_digest: str
    candidate_bound: bool = True
    runtime_authority: bool = False
    merge_authority: bool = False
    activation_authority: bool = False
    promotion_authority: bool = False
    release_authority: bool = False


def _valid_window(observed: int, expires: int, now: int) -> bool:
    return (
        type(observed) is int
        and type(expires) is int
        and type(now) is int
        and observed <= now < expires
        and expires > observed
    )


def bind_candidate_evidence(
    candidate: _candidate.Candidate,
    sandbox: _candidate.SandboxReceipt,
    evidence: EvidenceDecision,
    source_execution: ExecutionReceipt,
    merge_execution: ExecutionReceipt,
    binding: CandidateEvidenceBindingReceipt,
    trust_store: HmacTrustStore,
    *,
    now_ns: int | None = None,
) -> BoundEvidenceDecision:
    now = time.time_ns() if now_ns is None else now_ns
    if type(now) is not int or now < 0:
        raise _control.EngineeringError("invalid_time")
    if evidence.eligible_for_independent_review is not True or evidence.reasons:
        raise _control.EngineeringError("evidence_not_eligible")
    for name in (
        "runtime_authority",
        "merge_authority",
        "activation_authority",
        "promotion_authority",
        "release_authority",
    ):
        if getattr(evidence, name, False) is not False:
            raise _control.EngineeringError("evidence_authority_delta")
    if candidate.state != "sandbox_tested" or not candidate.sandbox_receipt_digest:
        raise _control.EngineeringError("candidate_not_sandbox_tested")
    actual_sandbox_digest = _control.semantic_digest(asdict(sandbox))
    if (
        sandbox.candidate_id != candidate.candidate_id
        or sandbox.base_commit != candidate.base_commit
        or candidate.sandbox_receipt_digest != actual_sandbox_digest
        or sandbox.passed is not True
        or sandbox.authority_delta is not False
    ):
        raise _control.EngineeringError("sandbox_candidate_binding_mismatch")
    source_digest = _control.semantic_digest(asdict(source_execution))
    merge_digest = _control.semantic_digest(asdict(merge_execution))
    for value, label in (
        (candidate.semantic_digest, "candidate_digest"),
        (actual_sandbox_digest, "sandbox_receipt_digest"),
        (evidence.evidence_digest, "evidence_digest"),
        (source_digest, "source_execution_digest"),
        (merge_digest, "merge_execution_digest"),
    ):
        _control.checked_sha256(value, label)
    _control.checked_id(binding.candidate_id, "candidate_id")
    if (
        binding.candidate_id != candidate.candidate_id
        or binding.candidate_digest != candidate.semantic_digest
        or binding.sandbox_receipt_digest != actual_sandbox_digest
        or binding.base_commit != candidate.base_commit
        or binding.evidence_digest != evidence.evidence_digest
        or binding.source_execution_digest != source_digest
        or binding.merge_execution_digest != merge_digest
        or source_execution.commit != candidate.base_commit
    ):
        raise _control.EngineeringError("candidate_evidence_binding_mismatch")
    if binding.issuer != "ci_executor":
        raise _control.EngineeringError("candidate_binding_issuer_role")
    if not _valid_window(binding.observed_unix_ns, binding.expires_unix_ns, now):
        raise _control.EngineeringError("candidate_binding_stale")
    if not trust_store.verify(
        binding,
        binding.issuer,
        binding.signing_identity,
        binding.signature,
    ):
        raise _control.EngineeringError("candidate_binding_signature")
    binding_digest = _control.semantic_digest(asdict(binding))
    bound_digest = _control.semantic_digest(
        {
            "baseEvidenceDigest": evidence.evidence_digest,
            "candidateId": candidate.candidate_id,
            "candidateDigest": candidate.semantic_digest,
            "sandboxReceiptDigest": actual_sandbox_digest,
            "bindingReceiptDigest": binding_digest,
        }
    )
    return BoundEvidenceDecision(
        True,
        (),
        bound_digest,
        candidate.candidate_id,
        candidate.semantic_digest,
        actual_sandbox_digest,
        binding_digest,
    )


def hardened_request_independent_review(
    candidate: _candidate.Candidate,
    evidence: BoundEvidenceDecision,
    requested_role: str,
    *,
    now_ns: int | None = None,
) -> _facade.ReviewRequest:
    if not isinstance(evidence, BoundEvidenceDecision) or evidence.candidate_bound is not True:
        raise _control.EngineeringError("candidate_binding_required")
    if candidate.state != "sandbox_tested" or not candidate.sandbox_receipt_digest:
        raise _control.EngineeringError("candidate_not_sandbox_tested")
    if (
        evidence.eligible_for_independent_review is not True
        or evidence.reasons
        or evidence.candidate_id != candidate.candidate_id
        or evidence.candidate_digest != candidate.semantic_digest
        or evidence.sandbox_receipt_digest != candidate.sandbox_receipt_digest
    ):
        raise _control.EngineeringError("evidence_not_eligible")
    if requested_role not in {
        "independent_evaluator",
        "architecture_reviewer",
        "security_reviewer",
    }:
        raise _control.EngineeringError("invalid_review_role")
    now = time.time_ns() if now_ns is None else now_ns
    if type(now) is not int or now < 0:
        raise _control.EngineeringError("invalid_time")
    body = {
        "candidateId": candidate.candidate_id,
        "candidateDigest": candidate.semantic_digest,
        "sandboxReceiptDigest": candidate.sandbox_receipt_digest,
        "boundEvidenceDigest": evidence.evidence_digest,
        "bindingReceiptDigest": evidence.binding_receipt_digest,
        "requestedRole": requested_role,
        "createdUnixNs": now,
    }
    return _facade.ReviewRequest(
        _control.semantic_digest(body)[:32],
        candidate.candidate_id,
        evidence.evidence_digest,
        requested_role,
        now,
    )


def hardened_record_integration_decision(
    store: _control.EngineeringStore,
    decision_id: str,
    evidence: EvidenceDecision | BoundEvidenceDecision,
    *,
    now_ns: int | None = None,
) -> None:
    if evidence.eligible_for_independent_review is True:
        if not isinstance(evidence, BoundEvidenceDecision) or evidence.candidate_bound is not True:
            raise _control.EngineeringError("candidate_binding_required")
    store.record_integration_decision(
        decision_id,
        evidence.evidence_digest,
        evidence.eligible_for_independent_review,
        evidence.reasons,
        now_ns=now_ns,
    )


# ---------------------------------------------------------------------------
# Authenticated dormant assimilation composition
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class OwnerConsentAttestation:
    owner_principal: str
    target_identity_digest: str
    consent_payload_digest: str
    issuer: str
    signing_identity: str
    observed_unix_ns: int
    expires_unix_ns: int
    signature: str = ""


@dataclass(frozen=True)
class SandboxParityAttestation:
    sandbox_receipt_digest: str
    manifest_digest: str
    operations_digest: str
    issuer: str
    signing_identity: str
    observed_unix_ns: int
    expires_unix_ns: int
    signature: str = ""


@dataclass(frozen=True)
class AttestedSandboxParity:
    receipt: _assimilation.SandboxParityReceipt
    attestation: SandboxParityAttestation


def consent_payload_digest(receipt: _assimilation.OwnerConsentReceipt) -> str:
    value = _assimilation.validate_consent(receipt)
    return _control.semantic_digest(
        {
            "ownerPrincipal": value.owner_principal,
            "targetIdentityDigest": value.target_identity_digest,
            "allowedOperations": value.allowed_operations,
            "allowedRoots": value.allowed_roots,
            "observedUnixNs": value.observed_unix_ns,
            "expiresUnixNs": value.expires_unix_ns,
        }
    )


def hardened_prepare_assimilation_candidate(
    consent: _assimilation.OwnerConsentReceipt,
    observations: Mapping[str, str],
    omissions: Iterable[str],
    sandbox_factory: Callable[
        [_assimilation.ExternalManifestCandidate, tuple[_assimilation.TypedOperation, ...]],
        AttestedSandboxParity,
    ],
    *,
    trust_store: HmacTrustStore,
    consent_attestation: OwnerConsentAttestation,
    now_ns: int | None = None,
) -> _assimilation.AssimilationProposal:
    now = time.time_ns() if now_ns is None else now_ns
    if type(now) is not int or now < 0:
        raise _control.EngineeringError("invalid_time")
    value = _assimilation.validate_consent(consent, now_ns=now)
    payload_digest = _control.semantic_digest(
        {
            "ownerPrincipal": value.owner_principal,
            "targetIdentityDigest": value.target_identity_digest,
            "allowedOperations": value.allowed_operations,
            "allowedRoots": value.allowed_roots,
            "observedUnixNs": value.observed_unix_ns,
            "expiresUnixNs": value.expires_unix_ns,
        }
    )
    if value.receipt_digest != payload_digest:
        raise _control.EngineeringError("consent_payload_digest_mismatch")
    if (
        consent_attestation.owner_principal != value.owner_principal
        or consent_attestation.target_identity_digest != value.target_identity_digest
        or consent_attestation.consent_payload_digest != payload_digest
        or consent_attestation.issuer != value.owner_principal
    ):
        raise _control.EngineeringError("consent_attestation_mismatch")
    if not _valid_window(
        consent_attestation.observed_unix_ns,
        consent_attestation.expires_unix_ns,
        now,
    ):
        raise _control.EngineeringError("consent_attestation_stale")
    if not trust_store.verify(
        consent_attestation,
        consent_attestation.issuer,
        consent_attestation.signing_identity,
        consent_attestation.signature,
    ):
        raise _control.EngineeringError("consent_attestation_signature")

    manifest = _assimilation.build_manifest_candidate(
        value,
        observations,
        omissions,
        now_ns=now,
    )
    operations = _assimilation.synthesize_read_only_contracts(
        value,
        manifest,
        now_ns=now,
    )
    attested = sandbox_factory(manifest, operations)
    if not isinstance(attested, AttestedSandboxParity):
        raise _control.EngineeringError("sandbox_attestation_missing")
    sandbox = attested.receipt
    parity = attested.attestation
    sandbox_digest = _control.semantic_digest(asdict(sandbox))
    manifest_digest = _control.semantic_digest(asdict(manifest))
    operations_digest = _control.semantic_digest([asdict(item) for item in operations])
    if (
        parity.sandbox_receipt_digest != sandbox_digest
        or parity.manifest_digest != manifest_digest
        or parity.operations_digest != operations_digest
        or parity.issuer != sandbox.evaluator_principal
    ):
        raise _control.EngineeringError("sandbox_attestation_mismatch")
    if not _valid_window(parity.observed_unix_ns, parity.expires_unix_ns, now):
        raise _control.EngineeringError("sandbox_attestation_stale")
    if not trust_store.verify(
        parity,
        parity.issuer,
        parity.signing_identity,
        parity.signature,
    ):
        raise _control.EngineeringError("sandbox_attestation_signature")
    return _assimilation.propose_dormant_assimilation(
        value,
        manifest,
        operations,
        sandbox,
        now_ns=now,
    )


# ---------------------------------------------------------------------------
# Installation
# ---------------------------------------------------------------------------

def install_hardening() -> None:
    if getattr(_control.EngineeringStore, "_lane_g_hardening_installed", False):
        return
    _install_error_identity()
    _control.EngineeringStore.__init__ = _hardened_store_init  # type: ignore[method-assign]
    _control.EngineeringStore.issue_work_envelope = _immediate_wrapper(  # type: ignore[method-assign]
        _ORIGINAL_ISSUE_ENVELOPE
    )
    _control.EngineeringStore.acquire_path_lease = _immediate_wrapper(  # type: ignore[method-assign]
        _ORIGINAL_ACQUIRE_LEASE
    )
    _control.EngineeringStore.transition_path_lease = _immediate_wrapper(  # type: ignore[method-assign]
        _ORIGINAL_TRANSITION_LEASE
    )
    _control.EngineeringStore.schedule_ready_packages = _hardened_schedule  # type: ignore[method-assign]
    _control.EngineeringStore.record_integration_decision = _immediate_wrapper(  # type: ignore[method-assign]
        _ORIGINAL_RECORD_DECISION
    )
    _control.EngineeringStore.assignment_frontier = assignment_frontier  # type: ignore[attr-defined]

    _candidate.sandbox_candidate = hardened_sandbox_candidate
    _facade.sandbox_candidate = hardened_sandbox_candidate
    _facade.execute_candidate_sandbox = hardened_execute_candidate_sandbox
    _facade.request_independent_review = hardened_request_independent_review
    _facade.record_integration_decision = hardened_record_integration_decision
    _facade.prepare_assimilation_candidate = hardened_prepare_assimilation_candidate
    _control.EngineeringStore._lane_g_hardening_installed = True  # type: ignore[attr-defined]
