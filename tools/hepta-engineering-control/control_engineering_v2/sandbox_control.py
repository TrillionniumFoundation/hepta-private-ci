"""Bounded candidate execution admission and infrastructure retry control."""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import asdict, dataclass
import errno
import os
from pathlib import Path
import stat
from threading import BoundedSemaphore, Lock

try:
    import fcntl as _fcntl
except ImportError:  # Windows portable fixtures cannot be strong sandbox evidence.
    _fcntl = None

from .candidate import Candidate, CandidateEnvelope, SandboxReceipt, sandbox_candidate
from .control_plane import EngineeringError, semantic_digest

MAX_PARALLEL_SANDBOXES = 8
MAX_INFRASTRUCTURE_RETRIES = 2
_HOST_ADMISSION_ROOT = Path("/tmp")
_INFRASTRUCTURE_ERRORS = frozenset(
    {
        "network_isolation_unavailable",
        "git_operation_failed",
    }
)


@dataclass(frozen=True)
class SandboxExecutionPolicy:
    maximum_parallel_sandboxes: int = MAX_PARALLEL_SANDBOXES
    infrastructure_retries: int = MAX_INFRASTRUCTURE_RETRIES


@dataclass(frozen=True)
class SandboxExecutionResult:
    candidate: Candidate
    receipt: SandboxReceipt
    attempts: int
    policy_digest: str


class SandboxCoordinator:
    """Bound sandbox admission on one host; multi-host deployment needs an external fence."""

    def __init__(
        self,
        policy: SandboxExecutionPolicy = SandboxExecutionPolicy(),
    ):
        if not isinstance(policy, SandboxExecutionPolicy):
            raise EngineeringError("invalid_sandbox_execution_policy")
        if (
            type(policy.maximum_parallel_sandboxes) is not int
            or not 1 <= policy.maximum_parallel_sandboxes <= MAX_PARALLEL_SANDBOXES
            or type(policy.infrastructure_retries) is not int
            or not 0 <= policy.infrastructure_retries <= MAX_INFRASTRUCTURE_RETRIES
        ):
            raise EngineeringError("invalid_sandbox_execution_policy")
        self.policy = policy
        self._semaphore = BoundedSemaphore(policy.maximum_parallel_sandboxes)
        self._lock = Lock()
        self._active = 0
        self._peak = 0
        if _fcntl is None:
            self._admission_directory = None
        else:
            # This path is intentionally not caller-configurable. All cooperating
            # processes for one UID must contend on the same eight host slots.
            directory = (
                _HOST_ADMISSION_ROOT
                / f"hepta-engineering-sandbox-slots-{os.getuid()}"
            )
            try:
                directory.mkdir(mode=0o700, parents=True, exist_ok=True)
                metadata = directory.lstat()
                if (
                    directory.is_symlink()
                    or not stat.S_ISDIR(metadata.st_mode)
                    or metadata.st_uid != os.getuid()
                    or stat.S_IMODE(metadata.st_mode) & 0o077
                ):
                    raise OSError("sandbox admission directory is not private")
            except OSError:
                raise EngineeringError("sandbox_host_admission_unavailable") from None
            self._admission_directory = directory

    @property
    def peak_parallelism(self) -> int:
        with self._lock:
            return self._peak

    @property
    def admission_scope(self) -> str:
        return "host" if self._admission_directory is not None else "process"

    def _acquire_host_slot(self) -> int | None:
        if self._admission_directory is None:
            return None
        assert _fcntl is not None
        flags = os.O_RDWR | os.O_CREAT
        if hasattr(os, "O_CLOEXEC"):
            flags |= os.O_CLOEXEC
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        for index in range(MAX_PARALLEL_SANDBOXES):
            path = self._admission_directory / f"slot-{index:02d}.lock"
            try:
                descriptor = os.open(path, flags, 0o600)
                metadata = os.fstat(descriptor)
                if (
                    not stat.S_ISREG(metadata.st_mode)
                    or metadata.st_uid != os.getuid()
                    or stat.S_IMODE(metadata.st_mode) & 0o077
                ):
                    os.close(descriptor)
                    raise EngineeringError("sandbox_host_admission_unavailable")
            except EngineeringError:
                raise
            except OSError:
                raise EngineeringError("sandbox_host_admission_unavailable") from None
            try:
                _fcntl.flock(descriptor, _fcntl.LOCK_EX | _fcntl.LOCK_NB)
                return descriptor
            except OSError as error:
                os.close(descriptor)
                if error.errno in {errno.EACCES, errno.EAGAIN}:
                    continue
                raise EngineeringError("sandbox_host_admission_unavailable") from None
        raise EngineeringError("sandbox_capacity_exhausted")

    def _enter(self) -> int | None:
        if not self._semaphore.acquire(blocking=False):
            raise EngineeringError("sandbox_capacity_exhausted")
        host_slot: int | None = None
        try:
            host_slot = self._acquire_host_slot()
            with self._lock:
                self._active += 1
                if self._active > self.policy.maximum_parallel_sandboxes:
                    self._active -= 1
                    raise EngineeringError("sandbox_parallelism_invariant")
                self._peak = max(self._peak, self._active)
            return host_slot
        except BaseException:
            if host_slot is not None and _fcntl is not None:
                try:
                    _fcntl.flock(host_slot, _fcntl.LOCK_UN)
                finally:
                    os.close(host_slot)
            self._semaphore.release()
            raise

    def _exit(self, host_slot: int | None) -> None:
        with self._lock:
            self._active -= 1
        if host_slot is not None and _fcntl is not None:
            try:
                _fcntl.flock(host_slot, _fcntl.LOCK_UN)
            finally:
                os.close(host_slot)
        self._semaphore.release()

    def execute(
        self,
        repository: str,
        envelope: CandidateEnvelope,
        candidate: Candidate,
        checks: Iterable[Sequence[str]],
    ) -> SandboxExecutionResult:
        checks_value = tuple(tuple(item) for item in checks)
        attempts = 0
        host_slot = self._enter()
        try:
            while True:
                attempts += 1
                try:
                    tested, receipt = sandbox_candidate(
                        repository, envelope, candidate, checks_value
                    )
                    return SandboxExecutionResult(
                        tested,
                        receipt,
                        attempts,
                        semantic_digest(
                            {
                                "policy": asdict(self.policy),
                                "admissionScope": self.admission_scope,
                                "hostSlotCeiling": (
                                    MAX_PARALLEL_SANDBOXES
                                    if self.admission_scope == "host"
                                    else None
                                ),
                            }
                        ),
                    )
                except EngineeringError as error:
                    if (
                        error.code not in _INFRASTRUCTURE_ERRORS
                        or attempts > self.policy.infrastructure_retries
                    ):
                        raise
                    # Semantic rejection is never retried.  Only the explicitly
                    # classified infrastructure failures above can consume budget.
        finally:
            self._exit(host_slot)
