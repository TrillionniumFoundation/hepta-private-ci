"""Explicit wall-clock and signed-observation skew policy.

Local duration measurement should use a monotonic clock. Cross-principal signed
receipts use this bounded wall-clock policy and never silently widen freshness.
"""
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
    wall: int
    monotonic: int = 0

    def wall_time_ns(self) -> int:
        return self.wall

    def monotonic_ns(self) -> int:
        return self.monotonic


@dataclass(frozen=True)
class ClockSkewPolicy:
    max_future_skew_ns: int = 0
    max_observation_age_ns: int | None = None

    def __post_init__(self) -> None:
        if type(self.max_future_skew_ns) is not int or self.max_future_skew_ns < 0:
            raise EngineeringError("invalid_clock_future_skew")
        if self.max_observation_age_ns is not None and (
            type(self.max_observation_age_ns) is not int
            or self.max_observation_age_ns < 1
        ):
            raise EngineeringError("invalid_clock_observation_age")


STRICT_CLOCK_SKEW_POLICY = ClockSkewPolicy()


def validate_signed_window(
    observed_unix_ns: int,
    expires_unix_ns: int,
    now_unix_ns: int,
    *,
    not_before_unix_ns: int = 0,
    owner_expires_unix_ns: int | None = None,
    policy: ClockSkewPolicy = STRICT_CLOCK_SKEW_POLICY,
) -> None:
    values = (
        observed_unix_ns,
        expires_unix_ns,
        now_unix_ns,
        not_before_unix_ns,
    )
    if any(type(value) is not int or value < 0 for value in values):
        raise EngineeringError("invalid_time")
    if not isinstance(policy, ClockSkewPolicy):
        raise EngineeringError("invalid_clock_policy")
    if observed_unix_ns < not_before_unix_ns:
        raise EngineeringError("signed_observation_predates_owner")
    if observed_unix_ns > now_unix_ns + policy.max_future_skew_ns:
        raise EngineeringError("signed_observation_from_future")
    if not now_unix_ns < expires_unix_ns or expires_unix_ns <= observed_unix_ns:
        raise EngineeringError("signed_observation_stale")
    if policy.max_observation_age_ns is not None and (
        now_unix_ns - observed_unix_ns > policy.max_observation_age_ns
    ):
        raise EngineeringError("signed_observation_too_old")
    if owner_expires_unix_ns is not None:
        if type(owner_expires_unix_ns) is not int or owner_expires_unix_ns < 0:
            raise EngineeringError("invalid_owner_expiry")
        if expires_unix_ns > owner_expires_unix_ns:
            raise EngineeringError("signed_observation_outlives_owner")
