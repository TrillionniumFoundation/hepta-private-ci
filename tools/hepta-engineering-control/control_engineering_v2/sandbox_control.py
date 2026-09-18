"""Bounded sandbox admission and infrastructure-only retry control."""

from __future__ import annotations

from contextlib import contextmanager
import threading
from typing import Callable, TypeVar

from .control_plane import EngineeringError

MAX_PARALLEL_SANDBOXES = 8
MAX_INFRASTRUCTURE_RETRIES = 2

_INFRASTRUCTURE_ERRORS = frozenset(
    {
        "git_operation_failed",
        "git_read_failed",
        "network_isolation_unavailable",
        "sandbox_time_budget_exceeded",
    }
)
_slots = threading.BoundedSemaphore(MAX_PARALLEL_SANDBOXES)
T = TypeVar("T")


@contextmanager
def sandbox_admission():
    acquired = _slots.acquire(timeout=30)
    if not acquired:
        raise EngineeringError("sandbox_capacity_exhausted")
    try:
        yield
    finally:
        _slots.release()


def run_with_infrastructure_retries(
    operation: Callable[[], T],
    *,
    maximum_retries: int = MAX_INFRASTRUCTURE_RETRIES,
) -> T:
    if type(maximum_retries) is not int or not 0 <= maximum_retries <= MAX_INFRASTRUCTURE_RETRIES:
        raise EngineeringError("invalid_infrastructure_retry_limit")
    attempts = 0
    while True:
        try:
            return operation()
        except EngineeringError as error:
            if error.code not in _INFRASTRUCTURE_ERRORS or attempts >= maximum_retries:
                raise
            attempts += 1
