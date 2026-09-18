"""Bounded candidate execution admission and infrastructure retry control."""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from threading import BoundedSemaphore, Lock

from .candidate import Candidate, CandidateEnvelope, SandboxReceipt, sandbox_candidate
from .control_plane import EngineeringError, semantic_digest

MAX_PARALLEL_SANDBOXES = 8
MAX_INFRASTRUCTURE_RETRIES = 2
_INFRASTRUCTURE_ERRORS = frozenset(
    {
        "network_isolation_unavailable",
        "git_operation_failed",
        "sandbox_time_budget_exceeded",
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
    """Process-local admission owner; distributed deployment needs an external fence."""

    def __init__(self, policy: SandboxExecutionPolicy = SandboxExecutionPolicy()):
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

    @property
    def peak_parallelism(self) -> int:
        with self._lock:
            return self._peak

    def _enter(self) -> None:
        self._semaphore.acquire()
        with self._lock:
            self._active += 1
            self._peak = max(self._peak, self._active)
            if self._active > self.policy.maximum_parallel_sandboxes:
                raise EngineeringError("sandbox_parallelism_invariant")

    def _exit(self) -> None:
        with self._lock:
            self._active -= 1
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
        self._enter()
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
                        semantic_digest(self.policy.__dict__),
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
            self._exit()
