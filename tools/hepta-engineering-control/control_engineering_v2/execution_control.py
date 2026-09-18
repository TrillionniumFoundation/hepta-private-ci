"""Owner-level execution capacity, retry and mutation-test admission controls."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass
import os
from pathlib import Path
import time
import tempfile

from .control_plane import EngineeringError, bounded_tuple, checked_id, semantic_digest

try:
    import fcntl
except ImportError:  # pragma: no cover - production strong sandbox is Linux.
    fcntl = None

MAX_PARALLEL_SANDBOXES = 8
MAX_INFRASTRUCTURE_RETRIES = 2
MAX_MUTATION_PROBES = 256
SANDBOX_LOCK_DIRECTORY_ENV = "HEPTA_ENGINEERING_SANDBOX_LOCK_DIR"
_RETRYABLE_INFRA_CODES = frozenset(
    {
        "network_isolation_unavailable",
        "git_operation_failed",
    }
)


@dataclass
class SandboxSlotLease:
    slot: int
    file_descriptor: int

    def close(self) -> None:
        if self.file_descriptor < 0:
            return
        try:
            if fcntl is not None:
                fcntl.flock(self.file_descriptor, fcntl.LOCK_UN)
        finally:
            os.close(self.file_descriptor)
            self.file_descriptor = -1

    def __enter__(self) -> "SandboxSlotLease":
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        self.close()


def default_host_sandbox_limiter(
    maximum_slots: int = MAX_PARALLEL_SANDBOXES,
) -> "HostSandboxLimiter":
    """Return the canonical cross-process limiter for authoritative host execution.

    The optional environment override is an operator configuration input.  In its
    absence every process on the host converges on one stable temporary-directory
    namespace, so separate CLI/library processes cannot each create an independent
    eight-slot pool.
    """

    raw = os.environ.get(SANDBOX_LOCK_DIRECTORY_ENV)
    directory = (
        Path(raw)
        if raw
        else Path(tempfile.gettempdir()) / "hepta-engineering-sandbox-slots-v1"
    )
    return HostSandboxLimiter(directory, maximum_slots=maximum_slots)


class HostSandboxLimiter:
    """Cross-process single-host semaphore implemented with durable lock files."""

    def __init__(self, directory: str | Path, maximum_slots: int = MAX_PARALLEL_SANDBOXES):
        if type(maximum_slots) is not int or not 1 <= maximum_slots <= MAX_PARALLEL_SANDBOXES:
            raise EngineeringError("invalid_sandbox_parallelism")
        if fcntl is None:
            raise EngineeringError("sandbox_capacity_control_unavailable")
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        self.maximum_slots = maximum_slots

    def acquire(self, *, deadline_monotonic: float | None = None) -> SandboxSlotLease:
        while True:
            for slot in range(self.maximum_slots):
                path = self.directory / f"sandbox-slot-{slot:02d}.lock"
                descriptor = os.open(path, os.O_RDWR | os.O_CREAT, 0o600)
                try:
                    fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
                except BlockingIOError:
                    os.close(descriptor)
                    continue
                return SandboxSlotLease(slot, descriptor)
            if deadline_monotonic is not None and time.monotonic() >= deadline_monotonic:
                raise EngineeringError("sandbox_capacity_exhausted")
            time.sleep(0.02)


def execute_with_infrastructure_retries(
    operation: Callable[[], object],
    limiter: HostSandboxLimiter,
    *,
    maximum_retries: int = MAX_INFRASTRUCTURE_RETRIES,
    deadline_monotonic: float | None = None,
):
    """Run one admitted sandbox operation with <=2 infrastructure-only retries."""
    if type(maximum_retries) is not int or not 0 <= maximum_retries <= MAX_INFRASTRUCTURE_RETRIES:
        raise EngineeringError("invalid_infrastructure_retry_limit")
    attempt = 0
    while True:
        try:
            with limiter.acquire(deadline_monotonic=deadline_monotonic):
                return operation()
        except EngineeringError as error:
            if error.code not in _RETRYABLE_INFRA_CODES or attempt >= maximum_retries:
                raise
            attempt += 1


@dataclass(frozen=True)
class MutationProbeResult:
    probe_id: str
    targeted_test_id: str
    mutant_digest: str
    killed: bool


@dataclass(frozen=True)
class MutationTestReceipt:
    test_set_digest: str
    probe_count: int
    killed_count: int
    surviving_probe_ids: tuple[str, ...]
    passed: bool
    receipt_digest: str


def evaluate_mutation_probes(
    test_set_digest: str,
    probes: Iterable[MutationProbeResult],
) -> MutationTestReceipt:
    """Fail closed unless every declared generated-test mutant is detected."""
    if (
        not isinstance(test_set_digest, str)
        or len(test_set_digest) != 64
        or any(ch not in "0123456789abcdef" for ch in test_set_digest)
    ):
        raise EngineeringError("invalid_test_set_digest")
    values = bounded_tuple(probes, MAX_MUTATION_PROBES, "mutation_probe_limit_exceeded")
    if not values:
        raise EngineeringError("mutation_probe_required")
    seen: set[str] = set()
    surviving: list[str] = []
    killed = 0
    for value in values:
        if not isinstance(value, MutationProbeResult):
            raise EngineeringError("invalid_mutation_probe")
        checked_id(value.probe_id, "probe_id")
        checked_id(value.targeted_test_id, "test_id")
        if value.probe_id in seen:
            raise EngineeringError("duplicate_mutation_probe")
        seen.add(value.probe_id)
        if (
            not isinstance(value.mutant_digest, str)
            or len(value.mutant_digest) != 64
            or any(ch not in "0123456789abcdef" for ch in value.mutant_digest)
        ):
            raise EngineeringError("invalid_mutant_digest")
        if type(value.killed) is not bool:
            raise EngineeringError("invalid_mutation_probe")
        if value.killed:
            killed += 1
        else:
            surviving.append(value.probe_id)
    body = {
        "testSetDigest": test_set_digest,
        "probes": [
            {
                "probeId": item.probe_id,
                "targetedTestId": item.targeted_test_id,
                "mutantDigest": item.mutant_digest,
                "killed": item.killed,
            }
            for item in values
        ],
    }
    return MutationTestReceipt(
        test_set_digest,
        len(values),
        killed,
        tuple(sorted(surviving)),
        not surviving,
        semantic_digest(body),
    )
