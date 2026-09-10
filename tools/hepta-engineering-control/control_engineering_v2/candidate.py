"""Bounded, no-self-accepting candidate generation for Lane G."""
from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import time
from collections.abc import Iterable, Sequence

try:
    import resource as _resource
except ImportError:  # Windows
    _resource = None

from .control_plane import (
    EngineeringError,
    bounded_tuple,
    canonical_json,
    canonical_repo_path,
    path_is_within,
    semantic_digest,
)

MAX_CANDIDATES = 32
MAX_CHANGED_FILES = 100
MAX_TEXT_DIFF_BYTES = 1_048_576
MAX_CHECKS = 64
PROTECTED_PREFIXES = (
    ".github/workflows",
    "docs/security",
    "docs/data/DATA_AUTHORITY.json",
    "docs/governance",
    "qualification",
)


@dataclass(frozen=True)
class Mutation:
    operation: str
    path: str = ""
    expected_text: str = ""
    replacement_text: str = ""

    def normalized(self) -> "Mutation":
        if self.operation == "no_change":
            if any((self.path, self.expected_text, self.replacement_text)):
                raise EngineeringError("invalid_no_change")
            return self
        if self.operation not in {"add_file", "replace_text", "delete_file"}:
            raise EngineeringError("unsupported_mutation")
        path = canonical_repo_path(self.path)
        for value in (self.expected_text, self.replacement_text):
            if (
                not isinstance(value, str)
                or "\x00" in value
                or len(value.encode("utf-8")) > MAX_TEXT_DIFF_BYTES
            ):
                raise EngineeringError("invalid_mutation_text")
        if self.operation == "add_file" and self.expected_text:
            raise EngineeringError("invalid_add_precondition")
        if self.operation == "delete_file" and self.replacement_text:
            raise EngineeringError("invalid_delete_replacement")
        if self.operation == "replace_text" and not self.expected_text:
            raise EngineeringError("empty_replace_precondition")
        return Mutation(self.operation, path, self.expected_text, self.replacement_text)


@dataclass(frozen=True)
class CandidateEnvelope:
    envelope_id: str
    base_commit: str
    allowed_paths: tuple[str, ...]
    protected_paths: tuple[str, ...] = PROTECTED_PREFIXES
    maximum_candidates: int = MAX_CANDIDATES
    maximum_changed_files: int = MAX_CHANGED_FILES
    maximum_diff_bytes: int = MAX_TEXT_DIFF_BYTES
    wall_time_seconds: int = 300
    memory_bytes: int = 1_073_741_824
    processes: int = 64
    require_network_isolation: bool = True


@dataclass(frozen=True)
class Candidate:
    candidate_id: str
    envelope_id: str
    base_commit: str
    mutation: Mutation
    semantic_digest: str
    state: str
    changed_paths: tuple[str, ...]
    sandbox_receipt_digest: str | None
    runtime_authority: bool = False
    merge_authority: bool = False
    selection_authority: bool = False
    release_authority: bool = False


@dataclass(frozen=True)
class SandboxReceipt:
    candidate_id: str
    base_commit: str
    source_tree_before: str
    source_tree_after: str
    check_results: tuple[tuple[str, int], ...]
    credential_environment_count: int
    network_isolated: bool
    duration_millis: int
    passed: bool
    authority_delta: bool = False


def _git(root: Path, *args: str, allow_failure: bool = False) -> str:
    try:
        result = subprocess.run(
            ["git", "-C", str(root), *args],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=60,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        raise EngineeringError("git_operation_failed") from None
    if result.returncode != 0 and not allow_failure:
        raise EngineeringError("git_operation_failed")
    return result.stdout.strip()


def _validate_envelope(envelope: CandidateEnvelope) -> tuple[tuple[str, ...], tuple[str, ...]]:
    if (
        type(envelope.maximum_candidates) is not int
        or not 1 <= envelope.maximum_candidates <= MAX_CANDIDATES
    ):
        raise EngineeringError("invalid_candidate_limit")
    if (
        type(envelope.maximum_changed_files) is not int
        or not 1 <= envelope.maximum_changed_files <= MAX_CHANGED_FILES
    ):
        raise EngineeringError("invalid_file_limit")
    if (
        type(envelope.maximum_diff_bytes) is not int
        or not 1 <= envelope.maximum_diff_bytes <= MAX_TEXT_DIFF_BYTES
    ):
        raise EngineeringError("invalid_diff_limit")
    if (
        type(envelope.wall_time_seconds) is not int
        or not 1 <= envelope.wall_time_seconds <= 3600
        or type(envelope.memory_bytes) is not int
        or not 64 * 1024 * 1024 <= envelope.memory_bytes <= 32 * 1024**3
        or type(envelope.processes) is not int
        or not 1 <= envelope.processes <= 1024
    ):
        raise EngineeringError("invalid_sandbox_budget")
    roots = tuple(sorted({canonical_repo_path(value) for value in envelope.allowed_paths}))
    protected = tuple(sorted({canonical_repo_path(value) for value in envelope.protected_paths}))
    if not roots:
        raise EngineeringError("empty_allowed_paths")
    return roots, protected


def _candidate_identity(envelope: CandidateEnvelope, mutation: Mutation) -> tuple[str, str]:
    digest = semantic_digest(
        {
            "envelopeId": envelope.envelope_id,
            "baseCommit": envelope.base_commit,
            "mutation": asdict(mutation),
        }
    )
    return digest[:32], digest


def generate_candidates(
    envelope: CandidateEnvelope,
    mutations: Iterable[Mutation],
) -> tuple[Candidate, ...]:
    roots, protected = _validate_envelope(envelope)
    raw = bounded_tuple(
        mutations,
        envelope.maximum_candidates - 1,
        "candidate_limit_exceeded",
    )
    if any(not isinstance(value, Mutation) for value in raw):
        raise EngineeringError("invalid_mutation")
    supplied = tuple(value.normalized() for value in raw)
    result: list[Candidate] = []
    seen: set[str] = set()
    for mutation in (Mutation("no_change"), *supplied):
        if mutation.operation != "no_change":
            if not path_is_within(mutation.path, roots):
                raise EngineeringError("path_outside_candidate_envelope")
            if path_is_within(mutation.path, protected):
                raise EngineeringError("protected_path")
        candidate_id, digest = _candidate_identity(envelope, mutation)
        if digest in seen:
            continue
        seen.add(digest)
        result.append(
            Candidate(
                candidate_id,
                envelope.envelope_id,
                envelope.base_commit,
                mutation,
                digest,
                "no_change" if mutation.operation == "no_change" else "drafted",
                () if mutation.operation == "no_change" else (mutation.path,),
                None,
            )
        )
    if not result or result[0].mutation.operation != "no_change":
        raise EngineeringError("no_change_missing")
    return tuple(result)


def _safe_target(worktree: Path, relative: str) -> Path:
    target = worktree.joinpath(*relative.split("/"))
    current = worktree
    for part in relative.split("/")[:-1]:
        current = current / part
        if current.is_symlink():
            raise EngineeringError("symlink_escape")
    try:
        target.resolve(strict=False).relative_to(worktree.resolve())
    except ValueError:
        raise EngineeringError("sandbox_path_escape") from None
    return target


def _apply_mutation(worktree: Path, mutation: Mutation) -> None:
    if mutation.operation == "no_change":
        return
    target = _safe_target(worktree, mutation.path)
    if mutation.operation == "add_file":
        if target.exists() or target.is_symlink():
            raise EngineeringError("add_target_exists")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(mutation.replacement_text, encoding="utf-8", newline="\n")
        return
    if not target.is_file() or target.is_symlink():
        raise EngineeringError("mutation_target_invalid")
    text = target.read_text(encoding="utf-8")
    if mutation.operation == "replace_text":
        if text.count(mutation.expected_text) != 1:
            raise EngineeringError("replace_precondition_failed")
        target.write_text(
            text.replace(mutation.expected_text, mutation.replacement_text, 1),
            encoding="utf-8",
            newline="\n",
        )
    else:
        if (
            mutation.expected_text
            and hashlib.sha256(text.encode("utf-8")).hexdigest()
            != mutation.expected_text
        ):
            raise EngineeringError("delete_precondition_failed")
        target.unlink()


def _changed_paths(worktree: Path) -> tuple[str, ...]:
    output = _git(worktree, "status", "--porcelain=v1", "--untracked-files=all")
    paths: list[str] = []
    for line in output.splitlines():
        if not line:
            continue
        value = line[3:]
        if " -> " in value:
            value = value.split(" -> ", 1)[1]
        paths.append(canonical_repo_path(value))
    return tuple(sorted(set(paths)))


def _changed_byte_budget(worktree: Path, paths: Sequence[str]) -> int:
    total = 0
    for relative in paths:
        target = _safe_target(worktree, relative)
        if target.exists():
            if not target.is_file() or target.is_symlink():
                raise EngineeringError("unsupported_changed_entry")
            total += target.stat().st_size
            try:
                target.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                raise EngineeringError("binary_change_rejected") from None
    return total


def _resource_limiter(memory_bytes: int, processes: int, wall_time: int):
    if _resource is None:
        return None

    def apply() -> None:
        limits = (
            ("RLIMIT_AS", memory_bytes, memory_bytes),
            ("RLIMIT_NPROC", processes, processes),
            ("RLIMIT_CPU", wall_time, wall_time + 1),
            ("RLIMIT_FSIZE", MAX_TEXT_DIFF_BYTES * 4, MAX_TEXT_DIFF_BYTES * 4),
            ("RLIMIT_NOFILE", 256, 256),
        )
        for name, requested_soft, requested_hard in limits:
            if not hasattr(_resource, name):
                continue
            resource_id = getattr(_resource, name)
            try:
                current_soft, current_hard = _resource.getrlimit(resource_id)
                infinity = getattr(_resource, "RLIM_INFINITY", -1)
                hard = requested_hard
                if current_hard != infinity:
                    hard = min(hard, current_hard)
                soft = min(requested_soft, hard)
                if current_soft != infinity and current_soft < soft:
                    soft = current_soft
                _resource.setrlimit(resource_id, (soft, hard))
            except (OSError, ValueError):
                # POSIX hosts expose different rlimit subsets and some hosted
                # macOS runners reject RLIMIT_AS/NPROC changes in preexec_fn.
                # Continue applying the remaining independent limits; wall-time
                # is additionally enforced by subprocess.run(timeout=...).
                continue

    return apply


def sandbox_candidate(
    repository: str | Path,
    envelope: CandidateEnvelope,
    candidate: Candidate,
    checks: Iterable[Sequence[str]],
) -> tuple[Candidate, SandboxReceipt]:
    roots, protected = _validate_envelope(envelope)
    if (
        candidate.envelope_id != envelope.envelope_id
        or candidate.base_commit != envelope.base_commit
    ):
        raise EngineeringError("candidate_envelope_mismatch")
    raw_checks = bounded_tuple(checks, MAX_CHECKS, "check_limit_exceeded")
    check_values: list[tuple[str, ...]] = []
    for check in raw_checks:
        if isinstance(check, (str, bytes)) or not isinstance(check, Sequence) or not check:
            raise EngineeringError("invalid_check")
        value = tuple(str(item) for item in check)
        if any(not item or "\x00" in item for item in value):
            raise EngineeringError("invalid_check")
        check_values.append(value)
    root = Path(repository).resolve()
    source_before = _git(root, "rev-parse", "HEAD^{tree}")
    start = time.monotonic_ns()
    worktree_added = False
    with tempfile.TemporaryDirectory(prefix="hepta-lane-g-") as temporary:
        worktree = Path(temporary) / "candidate"
        try:
            _git(root, "worktree", "add", "--detach", str(worktree), envelope.base_commit)
            worktree_added = True
            _apply_mutation(worktree, candidate.mutation)
            changed = _changed_paths(worktree)
            if len(changed) > envelope.maximum_changed_files:
                raise EngineeringError("changed_file_limit")
            if any(not path_is_within(path, roots) for path in changed):
                raise EngineeringError("sandbox_path_escape")
            if any(path_is_within(path, protected) for path in changed):
                raise EngineeringError("protected_path")
            if _changed_byte_budget(worktree, changed) > envelope.maximum_diff_bytes:
                raise EngineeringError("diff_limit_exceeded")
            prefix: list[str] = []
            network_isolated = False
            if envelope.require_network_isolation:
                unshare = shutil.which("unshare")
                if unshare is None or os.name != "posix":
                    raise EngineeringError("network_isolation_unavailable")
                prefix = [unshare, "--net", "--"]
                network_isolated = True
            sandbox_home = Path(temporary) / "home"
            sandbox_tmp = Path(temporary) / "tmp"
            sandbox_home.mkdir()
            sandbox_tmp.mkdir()
            environment = {
                "PATH": os.environ.get("PATH", ""),
                "HOME": str(sandbox_home),
                "TMPDIR": str(sandbox_tmp),
                "LANG": "C",
                "LC_ALL": "C",
                "NO_PROXY": "*",
                "HTTP_PROXY": "http://127.0.0.1:9",
                "HTTPS_PROXY": "http://127.0.0.1:9",
                "PYTHONDONTWRITEBYTECODE": "1",
            }
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
                label = hashlib.sha256(canonical_json(check)).hexdigest()[:16]
                try:
                    run = subprocess.run(
                        [*prefix, *check],
                        cwd=worktree,
                        env=environment,
                        stdin=subprocess.DEVNULL,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE,
                        timeout=envelope.wall_time_seconds,
                        check=False,
                        preexec_fn=_resource_limiter(
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
                results.append((label, code))
                if code != 0:
                    break
            passed = len(results) == len(check_values) and all(
                code == 0 for _, code in results
            )
            source_after = _git(root, "rev-parse", "HEAD^{tree}")
            if source_after != source_before:
                raise EngineeringError("source_tree_mutated")
            receipt = SandboxReceipt(
                candidate.candidate_id,
                envelope.base_commit,
                source_before,
                source_after,
                tuple(results),
                credential_count,
                network_isolated,
                (time.monotonic_ns() - start) // 1_000_000,
                passed,
            )
            receipt_digest = semantic_digest(asdict(receipt))
            return (
                Candidate(
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
        finally:
            if worktree_added:
                _git(
                    root,
                    "worktree",
                    "remove",
                    "--force",
                    str(worktree),
                    allow_failure=True,
                )
