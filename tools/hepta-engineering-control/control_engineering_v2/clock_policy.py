"""Explicit clock and signed-window policy for control.engineering.

The durable owner uses wall-clock timestamps for cross-principal receipts and a
monotonic clock for local elapsed-time measurements.  This module centralizes the
allowed skew, age and validity bounds so new production adapters do not silently
invent their own time semantics.
"""

from __future__ import annotations

from dataclasses import dataclass
import time
from typing import Protocol

from .control_plane import EngineeringError

_NANOSECONDS_PER_SECOND = 1_000_000_000


@dataclass(frozen=True)
class ClockPolicy:
    maximum_future_skew_ns: int = 5 * _NANOSECONDS_PER_SECOND
    maximum_observation_age_ns: int = 5 * 60 * _NANOSECONDS_PER_SECOND
    minimum_validity_ns: int = 1
    maximum_validity_ns: int = 24 * 60 * 60 * _NANOSECONDS_PER_SECOND

    def __post_init__(self) -> None:
        values = (
            self.maximum_future_skew_ns,
            self.maximum_observation_age_ns,
            self.minimum_validity_ns,
            self.maximum_validity_ns,
        )
        if any(type(value) is not int or value < 0 for value in values):
            raise EngineeringError("invalid_clock_policy")
        if self.minimum_validity_ns < 1:
            raise EngineeringError("invalid_clock_policy")
        if self.maximum_validity_ns < self.minimum_validity_ns:
            raise EngineeringError("invalid_clock_policy")


@dataclass(frozen=True)
class ClockWindowDecision:
    observed_unix_ns: int
    expires_unix_ns: int
    evaluated_unix_ns: int
    age_ns: int
    future_skew_ns: int
    validity_ns: int


class EngineeringClock(Protocol):
    def wall_time_ns(self) -> int:
        ...

    def monotonic_ns(self) -> int:
        ...


class SystemEngineeringClock:
    def wall_time_ns(self) -> int:
        return time.time_ns()

    def monotonic_ns(self) -> int:
        return time.monotonic_ns()


@dataclass(frozen=True)
class FixedEngineeringClock:
    wall_ns: int
    monotonic_value_ns: int = 0

    def wall_time_ns(self) -> int:
        return self.wall_ns

    def monotonic_ns(self) -> int:
        return self.monotonic_value_ns


def validate_signed_window(
    observed_unix_ns: int,
    expires_unix_ns: int,
    *,
    now_ns: int,
    policy: ClockPolicy = ClockPolicy(),
    label: str = "receipt",
) -> ClockWindowDecision:
    if not isinstance(label, str) or not label:
        raise EngineeringError("invalid_clock_label")
    if any(
        type(value) is not int or value < 0
        for value in (observed_unix_ns, expires_unix_ns, now_ns)
    ):
        raise EngineeringError("invalid_time")
    if not isinstance(policy, ClockPolicy):
        raise EngineeringError("invalid_clock_policy")

    validity = expires_unix_ns - observed_unix_ns
    if not policy.minimum_validity_ns <= validity <= policy.maximum_validity_ns:
        raise EngineeringError(f"{label}_validity_window")
    future_skew = max(0, observed_unix_ns - now_ns)
    if future_skew > policy.maximum_future_skew_ns:
        raise EngineeringError(f"{label}_from_future")
    if now_ns >= expires_unix_ns:
        raise EngineeringError(f"{label}_stale")
    age = max(0, now_ns - observed_unix_ns)
    if age > policy.maximum_observation_age_ns:
        raise EngineeringError(f"{label}_too_old")
    return ClockWindowDecision(
        observed_unix_ns,
        expires_unix_ns,
        now_ns,
        age,
        future_skew,
        validity,
    )
