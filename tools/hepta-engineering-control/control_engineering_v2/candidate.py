"""Bounded, no-self-accepting candidate generation for Lane G.

The qualifying sandbox never exposes the caller checkout or shared Git metadata to
candidate commands.  It materializes an immutable Git archive into a metadata-free
workspace, records complete path/type/mode/content manifests, and executes checks in
a fail-closed Linux bubblewrap boundary.  Non-isolated execution is retained only as
an explicitly non-authoritative fixture mode and can never produce ``sandbox_tested``.
"""
from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import asdict, dataclass
import hashlib
import os
from pathlib import Path
import shutil
import signal
import stat
import subprocess
import sys
import tarfile
import tempfile
import time
import unicodedata
from typing import BinaryIO

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
MAX_CHECK_OUTPUT_BYTES = 1_048_576
MAX_GIT_OUTPUT_BYTES = 32 * 1_048_576
MAX_ARCHIVE_ENTRIES = 500_000
MAX_ARCHIVE_BYTES = 4 * 1024**3
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
    filesystem_isolated: bool = False
    isolation_adapter: str = ""
    check_set_digest: str = ""
    candidate_state_digest_before: str = ""
    candidate_state_digest_after: str = ""
    source_worktree_digest_before: str = ""
    source_worktree_digest_after: str = ""


ManifestEntry = tuple[str, int, int, str]
TreeManifest = dict[str, ManifestEntry]


def _resource_limiter(memory_bytes: int, processes: int, wall_time: int):
    if _resource is None:
        return None

    def apply() -> None:
        limits = (
            ("RLIMIT_AS", memory_bytes, memory_bytes),
            ("RLIMIT_NPROC", processes, processes),
            ("RLIMIT_CPU", wall_time, wall_time + 1),
            (
                "RLIMIT_FSIZE",
                MAX_CHECK_OUTPUT_BYTES * 2,
                MAX_CHECK_OUTPUT_BYTES * 2,
            ),
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
                continue

    return apply


def _terminate_process(process: subprocess.Popen[bytes]) -> None:
    try:
        if os.name == "posix":
            os.killpg(process.pid, signal.SIGKILL)
        else:
            process.kill()
    except (OSError, ProcessLookupError):
        pass
    try:
        process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait()


def _run_bounded(
    argv: Sequence[str],
    *,
    cwd: Path | None,
    environment: Mapping[str, str] | None,
    timeout: int,
    memory_bytes: int,
    processes: int,
) -> int:
    if not argv or any(not isinstance(item, str) or not item or "\x00" in item for item in argv):
        raise EngineeringError("invalid_check")
    with tempfile.TemporaryFile() as stdout_file, tempfile.TemporaryFile() as stderr_file:
        try:
            process = subprocess.Popen(
                list(argv),
                cwd=None if cwd is None else str(cwd),
                env=None if environment is None else dict(environment),
                stdin=subprocess.DEVNULL,
                stdout=stdout_file,
                stderr=stderr_file,
                start_new_session=True,
                preexec_fn=_resource_limiter(memory_bytes, processes, timeout)
                if os.name == "posix"
                else None,
            )
        except OSError:
            return 127
        timed_out = False
        try:
            process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            timed_out = True
            _terminate_process(process)
        stdout_file.flush()
        stderr_file.flush()
        output_overflow = (
            stdout_file.tell() > MAX_CHECK_OUTPUT_BYTES
            or stderr_file.tell() > MAX_CHECK_OUTPUT_BYTES
        )
        if timed_out:
            return 124
        if output_overflow:
            return 125
        return int(process.returncode)


def _git_bytes(
    root: Path,
    *args: str,
    allow_failure: bool = False,
    maximum_output: int = MAX_GIT_OUTPUT_BYTES,
) -> bytes:
    environment = dict(os.environ)
    environment.update(
        {
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_TERMINAL_PROMPT": "0",
            "LC_ALL": "C",
        }
    )
    try:
        result = subprocess.run(
            [
                "git",
                "-c",
                "core.hooksPath=/dev/null",
                "-c",
                "core.quotepath=false",
                "-C",
                str(root),
                *args,
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=environment,
            timeout=60,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        raise EngineeringError("git_operation_failed") from None
    if len(result.stdout) > maximum_output or len(result.stderr) > maximum_output:
        raise EngineeringError("git_operation_failed")
    if result.returncode != 0 and not allow_failure:
        raise EngineeringError("git_operation_failed")
    return result.stdout


def _git(root: Path, *args: str, allow_failure: bool = False) -> str:
    try:
        return _git_bytes(root, *args, allow_failure=allow_failure).decode("utf-8").rstrip(
            "\r\n"
        )
    except UnicodeDecodeError:
        raise EngineeringError("git_operation_failed") from None


def _validate_envelope(envelope: CandidateEnvelope) -> tuple[tuple[str, ...], tuple[str, ...]]:
    if (
        not isinstance(envelope.base_commit, str)
        or len(envelope.base_commit) != 40
        or any(character not in "0123456789abcdef" for character in envelope.base_commit)
    ):
        raise EngineeringError("invalid_git_identity")
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
        or type(envelope.require_network_isolation) is not bool
    ):
        raise EngineeringError("invalid_sandbox_budget")
    roots = tuple(sorted({canonical_repo_path(value) for value in envelope.allowed_paths}))
    protected = tuple(sorted({canonical_repo_path(value) for value in envelope.protected_paths}))
    if not roots:
        raise EngineeringError("empty_allowed_paths")
    aliases: dict[str, str] = {}
    for value in (*roots, *protected):
        alias = unicodedata.normalize("NFC", value).casefold()
        previous = aliases.setdefault(alias, value)
        if previous != value:
            raise EngineeringError("invalid_path")
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
    canonical = canonical_repo_path(relative)
    target = worktree.joinpath(*canonical.split("/"))
    current = worktree
    for part in canonical.split("/")[:-1]:
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
    try:
        text = target.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        raise EngineeringError("binary_change_rejected") from None
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


def _archive_member_path(name: str) -> str:
    value = name.rstrip("/")
    if not value:
        raise EngineeringError("sandbox_path_escape")
    return canonical_repo_path(value)


def _extract_regular_file(
    source: BinaryIO,
    target: Path,
    *,
    remaining_bytes: int,
) -> int:
    written = 0
    with target.open("xb") as destination:
        while True:
            chunk = source.read(1024 * 1024)
            if not chunk:
                break
            written += len(chunk)
            if written > remaining_bytes:
                raise EngineeringError("diff_limit_exceeded")
            destination.write(chunk)
    return written


def _extract_source_archive(root: Path, base_commit: str, destination: Path) -> None:
    environment = dict(os.environ)
    environment.update(
        {
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_TERMINAL_PROMPT": "0",
            "LC_ALL": "C",
        }
    )
    destination.mkdir(parents=True, exist_ok=False)
    with tempfile.TemporaryFile() as stderr_file:
        try:
            process = subprocess.Popen(
                [
                    "git",
                    "-c",
                    "core.hooksPath=/dev/null",
                    "-C",
                    str(root),
                    "archive",
                    "--format=tar",
                    base_commit,
                ],
                stdout=subprocess.PIPE,
                stderr=stderr_file,
                env=environment,
                start_new_session=True,
            )
        except OSError:
            raise EngineeringError("git_operation_failed") from None
        if process.stdout is None:
            _terminate_process(process)
            raise EngineeringError("git_operation_failed")
        entries = 0
        extracted_bytes = 0
        try:
            with tarfile.open(fileobj=process.stdout, mode="r|") as archive:
                for member in archive:
                    entries += 1
                    if entries > MAX_ARCHIVE_ENTRIES:
                        raise EngineeringError("changed_file_limit")
                    relative = _archive_member_path(member.name)
                    target = _safe_target(destination, relative)
                    target.parent.mkdir(parents=True, exist_ok=True)
                    if member.isdir():
                        target.mkdir(exist_ok=True)
                    elif member.isreg():
                        source = archive.extractfile(member)
                        if source is None:
                            raise EngineeringError("git_operation_failed")
                        extracted_bytes += _extract_regular_file(
                            source,
                            target,
                            remaining_bytes=MAX_ARCHIVE_BYTES - extracted_bytes,
                        )
                    elif member.issym():
                        link = member.linkname
                        if not link or "\x00" in link or os.path.isabs(link):
                            raise EngineeringError("sandbox_path_escape")
                        try:
                            (target.parent / link).resolve(strict=False).relative_to(
                                destination.resolve()
                            )
                        except ValueError:
                            raise EngineeringError("sandbox_path_escape") from None
                        target.symlink_to(link)
                    else:
                        raise EngineeringError("unsupported_changed_entry")
                    if not member.issym():
                        try:
                            target.chmod(member.mode & 0o777)
                        except OSError:
                            raise EngineeringError("git_operation_failed") from None
            try:
                return_code = process.wait(timeout=60)
            except subprocess.TimeoutExpired:
                _terminate_process(process)
                raise EngineeringError("git_operation_failed") from None
            if return_code != 0:
                raise EngineeringError("git_operation_failed")
        except Exception:
            if process.poll() is None:
                _terminate_process(process)
            raise


def _hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as source:
            while True:
                chunk = source.read(1024 * 1024)
                if not chunk:
                    break
                digest.update(chunk)
    except OSError:
        raise EngineeringError("unsupported_changed_entry") from None
    return digest.hexdigest()


def _tree_manifest(root: Path) -> TreeManifest:
    manifest: TreeManifest = {}
    stack = [root]
    total_bytes = 0
    aliases: dict[str, str] = {}
    while stack:
        directory = stack.pop()
        try:
            entries = sorted(os.scandir(directory), key=lambda item: item.name)
        except OSError:
            raise EngineeringError("unsupported_changed_entry") from None
        for entry in entries:
            path = Path(entry.path)
            try:
                relative = path.relative_to(root).as_posix()
            except ValueError:
                raise EngineeringError("sandbox_path_escape") from None
            canonical = canonical_repo_path(relative)
            alias = unicodedata.normalize("NFC", canonical).casefold()
            prior = aliases.setdefault(alias, canonical)
            if prior != canonical:
                raise EngineeringError("invalid_path")
            try:
                metadata = path.lstat()
            except OSError:
                raise EngineeringError("unsupported_changed_entry") from None
            mode = stat.S_IMODE(metadata.st_mode)
            if stat.S_ISLNK(metadata.st_mode):
                try:
                    link = os.readlink(path)
                except OSError:
                    raise EngineeringError("unsupported_changed_entry") from None
                manifest[canonical] = (
                    "symlink",
                    mode,
                    len(link.encode("utf-8")),
                    hashlib.sha256(link.encode("utf-8")).hexdigest(),
                )
            elif stat.S_ISDIR(metadata.st_mode):
                manifest[canonical] = ("directory", mode, 0, "")
                stack.append(path)
            elif stat.S_ISREG(metadata.st_mode):
                total_bytes += metadata.st_size
                if total_bytes > MAX_ARCHIVE_BYTES:
                    raise EngineeringError("diff_limit_exceeded")
                manifest[canonical] = (
                    "file",
                    mode,
                    metadata.st_size,
                    _hash_file(path),
                )
            else:
                raise EngineeringError("unsupported_changed_entry")
            if len(manifest) > MAX_ARCHIVE_ENTRIES:
                raise EngineeringError("changed_file_limit")
    return manifest


def _manifest_digest(manifest: Mapping[str, ManifestEntry]) -> str:
    digest = hashlib.sha256()
    for path in sorted(manifest):
        kind, mode, size, content_digest = manifest[path]
        digest.update(
            canonical_json(
                {
                    "path": path,
                    "kind": kind,
                    "mode": mode,
                    "size": size,
                    "digest": content_digest,
                }
            )
        )
        digest.update(b"\n")
    return digest.hexdigest()


def _changed_paths(before: Mapping[str, ManifestEntry], after: Mapping[str, ManifestEntry]) -> tuple[str, ...]:
    return tuple(
        sorted(
            path
            for path in set(before) | set(after)
            if before.get(path) != after.get(path)
        )
    )


def _changed_byte_budget(
    before: Mapping[str, ManifestEntry],
    after: Mapping[str, ManifestEntry],
    paths: Sequence[str],
) -> int:
    total = 0
    for path in paths:
        total += len(path.encode("utf-8"))
        for manifest in (before, after):
            entry = manifest.get(path)
            if entry is not None:
                total += entry[2]
    return total


def _source_boundary_digest(root: Path) -> str:
    status = _git_bytes(root, "status", "--porcelain=v2", "-z", "--untracked-files=all")
    if status:
        raise EngineeringError("source_tree_mutated")
    identity = _git_bytes(root, "rev-parse", "HEAD", "HEAD^{tree}")
    return hashlib.sha256(identity + b"\x00" + status).hexdigest()


def _fixture_environment(home: Path, temporary: Path) -> dict[str, str]:
    return {
        "PATH": os.environ.get("PATH", ""),
        "HOME": str(home),
        "TMPDIR": str(temporary),
        "TEMP": str(temporary),
        "TMP": str(temporary),
        "LANG": "C",
        "LC_ALL": "C",
        "NO_PROXY": "*",
        "HTTP_PROXY": "http://127.0.0.1:9",
        "HTTPS_PROXY": "http://127.0.0.1:9",
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONUTF8": "1",
    }


def _bubblewrap_mount_arguments() -> list[str]:
    arguments: list[str] = []
    usr = Path("/usr")
    if not usr.is_dir():
        raise EngineeringError("network_isolation_unavailable")
    arguments.extend(("--ro-bind", "/usr", "/usr"))
    for raw in ("/bin", "/sbin", "/lib", "/lib64"):
        path = Path(raw)
        if path.is_symlink():
            arguments.extend(("--symlink", os.readlink(path), raw))
        elif path.exists():
            arguments.extend(("--ro-bind", raw, raw))
    if Path("/opt").is_dir():
        arguments.extend(("--ro-bind", "/opt", "/opt"))
    return arguments


def _bubblewrap_command(
    bubblewrap: str,
    workspace: Path,
    argv: Sequence[str],
) -> list[str]:
    return [
        bubblewrap,
        "--die-with-parent",
        "--new-session",
        "--unshare-all",
        "--clearenv",
        *_bubblewrap_mount_arguments(),
        "--proc",
        "/proc",
        "--dev",
        "/dev",
        "--tmpfs",
        "/tmp",
        "--dir",
        "/home",
        "--dir",
        "/home/sandbox",
        "--ro-bind",
        str(workspace),
        "/workspace",
        "--chdir",
        "/workspace",
        "--setenv",
        "PATH",
        "/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin",
        "--setenv",
        "HOME",
        "/home/sandbox",
        "--setenv",
        "TMPDIR",
        "/tmp",
        "--setenv",
        "LANG",
        "C",
        "--setenv",
        "LC_ALL",
        "C",
        "--setenv",
        "PYTHONUTF8",
        "1",
        "--setenv",
        "PYTHONDONTWRITEBYTECODE",
        "1",
        "--",
        *argv,
    ]


def _admit_bubblewrap(workspace: Path, envelope: CandidateEnvelope) -> str:
    if not sys.platform.startswith("linux") or os.name != "posix":
        raise EngineeringError("network_isolation_unavailable")
    bubblewrap = shutil.which("bwrap")
    if bubblewrap is None:
        raise EngineeringError("network_isolation_unavailable")
    probe = (
        sys.executable,
        "-I",
        "-c",
        "from pathlib import Path; "
        "assert not Path('/workspace/.git').exists(); "
        "p=Path('/workspace/.hepta-write-probe'); "
        "failed=False; "
        "\ntry: p.write_bytes(b'x')\nexcept OSError: failed=True\n"
        "assert failed",
    )
    code = _run_bounded(
        _bubblewrap_command(bubblewrap, workspace, probe),
        cwd=None,
        environment=None,
        timeout=min(30, envelope.wall_time_seconds),
        memory_bytes=envelope.memory_bytes,
        processes=envelope.processes,
    )
    if code != 0:
        raise EngineeringError("network_isolation_unavailable")
    return bubblewrap


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
    if not raw_checks:
        raise EngineeringError("invalid_check")
    check_values: list[tuple[str, ...]] = []
    for check in raw_checks:
        if isinstance(check, (str, bytes)) or not isinstance(check, Sequence) or not check:
            raise EngineeringError("invalid_check")
        if any(not isinstance(item, str) or not item or "\x00" in item for item in check):
            raise EngineeringError("invalid_check")
        check_values.append(tuple(check))
    check_set_digest = semantic_digest(check_values)
    root = Path(repository).resolve(strict=True)
    source_tree = _git(root, "rev-parse", f"{envelope.base_commit}^{{tree}}")
    if len(source_tree) != 40:
        raise EngineeringError("invalid_git_identity")
    source_boundary_before = _source_boundary_digest(root)
    start = time.monotonic_ns()
    with tempfile.TemporaryDirectory(prefix="hepta-lane-g-") as temporary_name:
        temporary = Path(temporary_name)
        workspace = temporary / "candidate"
        _extract_source_archive(root, envelope.base_commit, workspace)
        base_manifest = _tree_manifest(workspace)
        _apply_mutation(workspace, candidate.mutation)
        candidate_manifest = _tree_manifest(workspace)
        changed = _changed_paths(base_manifest, candidate_manifest)
        expected = () if candidate.mutation.operation == "no_change" else (candidate.mutation.path,)
        if changed != expected:
            raise EngineeringError("sandbox_path_escape")
        if len(changed) > envelope.maximum_changed_files:
            raise EngineeringError("changed_file_limit")
        if any(not path_is_within(path, roots) for path in changed):
            raise EngineeringError("sandbox_path_escape")
        if any(path_is_within(path, protected) for path in changed):
            raise EngineeringError("protected_path")
        if _changed_byte_budget(base_manifest, candidate_manifest, changed) > envelope.maximum_diff_bytes:
            raise EngineeringError("diff_limit_exceeded")
        state_before = _manifest_digest(candidate_manifest)
        sandbox_home = temporary / "home"
        sandbox_tmp = temporary / "tmp"
        sandbox_home.mkdir()
        sandbox_tmp.mkdir()
        bubblewrap: str | None = None
        filesystem_isolated = False
        network_isolated = False
        adapter = "fixture-only"
        if envelope.require_network_isolation:
            bubblewrap = _admit_bubblewrap(workspace, envelope)
            filesystem_isolated = True
            network_isolated = True
            adapter = "bubblewrap-unshare-all-ro-workspace-v1"
        environment = _fixture_environment(sandbox_home, sandbox_tmp)
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
            argv = (
                _bubblewrap_command(bubblewrap, workspace, check)
                if bubblewrap is not None
                else list(check)
            )
            code = _run_bounded(
                argv,
                cwd=None if bubblewrap is not None else workspace,
                environment=None if bubblewrap is not None else environment,
                timeout=envelope.wall_time_seconds,
                memory_bytes=envelope.memory_bytes,
                processes=envelope.processes,
            )
            results.append((label, code))
            if code != 0:
                break
        source_boundary_after = _source_boundary_digest(root)
        if source_boundary_after != source_boundary_before:
            raise EngineeringError("source_tree_mutated")
        post_manifest = _tree_manifest(workspace)
        state_after = _manifest_digest(post_manifest)
        if post_manifest != candidate_manifest or state_after != state_before:
            raise EngineeringError("source_tree_mutated")
        post_changed = _changed_paths(base_manifest, post_manifest)
        if post_changed != changed:
            raise EngineeringError("source_tree_mutated")
        if any(not path_is_within(path, roots) for path in post_changed):
            raise EngineeringError("sandbox_path_escape")
        if any(path_is_within(path, protected) for path in post_changed):
            raise EngineeringError("protected_path")
        source_after = _git(root, "rev-parse", f"{envelope.base_commit}^{{tree}}")
        if source_after != source_tree:
            raise EngineeringError("source_tree_mutated")
        passed = len(results) == len(check_values) and all(code == 0 for _, code in results)
        receipt = SandboxReceipt(
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
        if passed and filesystem_isolated and network_isolated:
            state = "sandbox_tested"
        elif passed:
            state = "fixture_tested"
        else:
            state = "rejected"
        return (
            Candidate(
                candidate.candidate_id,
                candidate.envelope_id,
                candidate.base_commit,
                candidate.mutation,
                candidate.semantic_digest,
                state,
                changed,
                receipt_digest,
            ),
            receipt,
        )
