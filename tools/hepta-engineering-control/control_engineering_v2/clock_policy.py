"""Explicit wall-clock and receipt-skew policy for control.engineering."""

from __future__ import annotations

from dataclasses import dataclass
import time
from typing import Protocol

from .control_plane import EngineeringError


class Clock(Protocol):
    def wall_time_ns(self) -> int: ...
    def monotonic_ns(self) -> int: ...


@dataclass(frozen=True)
class SystemClock:
    def wall_time_ns(self) -> int:
        return time.time_ns()

    def monotonic_ns(self) -> int:
        return time.monotonic_ns()


@dataclass(frozen=True)
class FixedClock:
    wall_ns: int
    monotonic_value_ns: int = 0

    def wall_time_ns(self) -> int:
        return self.wall_ns

    def monotonic_ns(self) -> int:
        return self.monotonic_value_ns


@dataclass(frozen=True)
class ClockSkewPolicy:
    maximum_future_skew_ns: int = 5_000_000_000
    maximum_observation_age_ns: int = 300_000_000_000
    minimum_remaining_validity_ns: int = 1_000_000
    maximum_validity_ns: int = 86_400_000_000_000

    def __post_init__(self) -> None:
        values = (
            self.maximum_future_skew_ns,
            self.maximum_observation_age_ns,
            self.minimum_remaining_validity_ns,
            self.maximum_validity_ns,
        )
        if any(type(value) is not int or value < 0 for value in values):
            raise EngineeringError("invalid_clock_skew_policy")
        if (
            self.minimum_remaining_validity_ns > self.maximum_validity_ns
            or self.maximum_future_skew_ns > self.maximum_validity_ns
        ):
            raise EngineeringError("invalid_clock_skew_policy")


@dataclass(frozen=True)
class ReceiptWindow:
    observed_unix_ns: int
    expires_unix_ns: int
    evaluated_unix_ns: int
    age_ns: int
    remaining_ns: int
    future_skew_ns: int


def validate_receipt_window(
    observed_unix_ns: int,
    expires_unix_ns: int,
    *,
    now_ns: int,
    policy: ClockSkewPolicy = ClockSkewPolicy(),
) -> ReceiptWindow:
    if not isinstance(policy, ClockSkewPolicy):
        raise EngineeringError("clock_skew_policy_required")
    if any(
        type(value) is not int or value < 0
        for value in (observed_unix_ns, expires_unix_ns, now_ns)
    ):
        raise EngineeringError("invalid_time")
    if expires_unix_ns <= observed_unix_ns:
        raise EngineeringError("receipt_window_invalid")
    if expires_unix_ns - observed_unix_ns > policy.maximum_validity_ns:
        raise EngineeringError("receipt_window_too_long")
    future_skew = max(0, observed_unix_ns - now_ns)
    if future_skew > policy.maximum_future_skew_ns:
        raise EngineeringError("receipt_observed_in_future")
    age = max(0, now_ns - observed_unix_ns)
    if age > policy.maximum_observation_age_ns:
        raise EngineeringError("receipt_observation_stale")
    remaining = expires_unix_ns - now_ns
    if remaining < policy.minimum_remaining_validity_ns:
        raise EngineeringError("receipt_validity_exhausted")
    return ReceiptWindow(
        observed_unix_ns,
        expires_unix_ns,
        now_ns,
        age,
        remaining,
        future_skew,
    )
