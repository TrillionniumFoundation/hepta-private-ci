"""Explicit wall-clock and monotonic-time policy for control.engineering.

Cross-principal receipts use wall time with a bounded future-skew allowance. Local
elapsed-time budgets use a monotonic clock.  The policy is injected so tests and
production hosts do not depend on implicit process-global time behavior.
"""

from __future__ import annotations

from dataclasses import dataclass
import time
from typing import Protocol

from .control_plane import EngineeringError


@dataclass(frozen=True)
class ClockPolicy:
    max_future_skew_ns: int
    max_observation_age_ns: int
    max_receipt_lifetime_ns: int

    def __post_init__(self) -> None:
        for value, code in (
            (self.max_future_skew_ns, "clock_future_skew"),
            (self.max_observation_age_ns, "clock_observation_age"),
            (self.max_receipt_lifetime_ns, "clock_receipt_lifetime"),
        ):
            if type(value) is not int or value < 0:
                raise EngineeringError(code)
        if self.max_receipt_lifetime_ns < 1:
            raise EngineeringError("clock_receipt_lifetime")


class Clock(Protocol):
    def wall_time_ns(self) -> int:
        ...

    def monotonic_ns(self) -> int:
        ...


class SystemClock:
    def wall_time_ns(self) -> int:
        return time.time_ns()

    def monotonic_ns(self) -> int:
        return time.monotonic_ns()


@dataclass
class FixedClock:
    wall_ns: int
    monotonic_value_ns: int = 0

    def __post_init__(self) -> None:
        if type(self.wall_ns) is not int or self.wall_ns < 0:
            raise EngineeringError("invalid_time")
        if type(self.monotonic_value_ns) is not int or self.monotonic_value_ns < 0:
            raise EngineeringError("invalid_monotonic_time")

    def wall_time_ns(self) -> int:
        return self.wall_ns

    def monotonic_ns(self) -> int:
        return self.monotonic_value_ns

    def advance(self, nanoseconds: int) -> None:
        if type(nanoseconds) is not int or nanoseconds < 0:
            raise EngineeringError("invalid_time_advance")
        self.wall_ns += nanoseconds
        self.monotonic_value_ns += nanoseconds


def checked_now(clock: Clock | None = None, *, now_ns: int | None = None) -> int:
    if clock is not None and now_ns is not None:
        raise EngineeringError("ambiguous_time_source")
    value = (clock or SystemClock()).wall_time_ns() if now_ns is None else now_ns
    if type(value) is not int or value < 0:
        raise EngineeringError("invalid_time")
    return value


def validate_observation_window(
    observed_unix_ns: int,
    expires_unix_ns: int,
    policy: ClockPolicy,
    *,
    clock: Clock | None = None,
    now_ns: int | None = None,
    owner_not_after_unix_ns: int | None = None,
) -> int:
    """Validate a signed receipt window under a declared clock-skew policy.

    A receipt may be slightly ahead of the verifier's wall clock, but never by
    more than ``max_future_skew_ns``. Its lifetime and age are independently
    bounded, and an optional owner deadline caps the receipt's validity.
    """

    if not isinstance(policy, ClockPolicy):
        raise EngineeringError("clock_policy_required")
    now = checked_now(clock, now_ns=now_ns)
    if (
        type(observed_unix_ns) is not int
        or type(expires_unix_ns) is not int
        or observed_unix_ns < 0
        or expires_unix_ns <= observed_unix_ns
    ):
        raise EngineeringError("invalid_observation_window")
    if observed_unix_ns > now + policy.max_future_skew_ns:
        raise EngineeringError("observation_from_future")
    if now > observed_unix_ns and now - observed_unix_ns > policy.max_observation_age_ns:
        raise EngineeringError("observation_too_old")
    if expires_unix_ns - observed_unix_ns > policy.max_receipt_lifetime_ns:
        raise EngineeringError("receipt_lifetime_exceeded")
    if now >= expires_unix_ns:
        raise EngineeringError("observation_expired")
    if owner_not_after_unix_ns is not None:
        if type(owner_not_after_unix_ns) is not int or owner_not_after_unix_ns < 0:
            raise EngineeringError("invalid_owner_deadline")
        if expires_unix_ns > owner_not_after_unix_ns:
            raise EngineeringError("observation_outlives_owner")
    return now


def elapsed_within_budget(
    started_monotonic_ns: int,
    budget_ns: int,
    *,
    clock: Clock | None = None,
    now_monotonic_ns: int | None = None,
) -> int:
    if type(started_monotonic_ns) is not int or started_monotonic_ns < 0:
        raise EngineeringError("invalid_monotonic_time")
    if type(budget_ns) is not int or budget_ns < 1:
        raise EngineeringError("invalid_time_budget")
    if clock is not None and now_monotonic_ns is not None:
        raise EngineeringError("ambiguous_time_source")
    observed = (
        (clock or SystemClock()).monotonic_ns()
        if now_monotonic_ns is None
        else now_monotonic_ns
    )
    if type(observed) is not int or observed < started_monotonic_ns:
        raise EngineeringError("monotonic_clock_regressed")
    elapsed = observed - started_monotonic_ns
    if elapsed > budget_ns:
        raise EngineeringError("time_budget_exceeded")
    return elapsed
