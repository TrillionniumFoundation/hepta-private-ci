"""Explicit wall-clock and signed-window policy for control.engineering.

The policy is injected by the product boundary.  It never manufactures a time
source or turns clock freshness into execution, merge, deployment, or release
authority.  Local elapsed-time budgets should still use ``time.monotonic_ns``;
this module is only for signed cross-principal wall-clock observations.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol
import time

from .control_plane import EngineeringError

_MAX_POLICY_NS = (1 << 63) - 1


class Clock(Protocol):
    """Injectable wall/monotonic clock pair."""

    def wall_time_ns(self) -> int: ...

    def monotonic_ns(self) -> int: ...


@dataclass(frozen=True)
class SystemClock:
    def wall_time_ns(self) -> int:
        return time.time_ns()

    def monotonic_ns(self) -> int:
        return time.monotonic_ns()


@dataclass(frozen=True)
class ClockSkewPolicy:
    """Bounds accepted signed observations without hiding host clock health.

    ``maximum_future_skew_ns`` is the only allowance for a signer whose clock is
    ahead of the verifier.  ``maximum_observation_age_ns`` and
    ``maximum_validity_ns`` prevent an otherwise correctly signed receipt from
    carrying an unbounded replay window.  These are protocol safety ceilings,
    not latency SLOs; a deployment may only narrow them.
    """

    maximum_future_skew_ns: int
    maximum_observation_age_ns: int
    maximum_validity_ns: int

    def __post_init__(self) -> None:
        for name, value in (
            ("maximum_future_skew_ns", self.maximum_future_skew_ns),
            ("maximum_observation_age_ns", self.maximum_observation_age_ns),
            ("maximum_validity_ns", self.maximum_validity_ns),
        ):
            if type(value) is not int or not 0 <= value <= _MAX_POLICY_NS:
                raise ValueError(f"invalid_{name}")
        if self.maximum_validity_ns < 1:
            raise ValueError("invalid_maximum_validity_ns")


# Compatibility-preserving default: no future skew is accepted.  Existing
# callers therefore retain their old ``observed <= now < expires`` behavior;
# deployments opt into a narrower, measured policy explicitly.
STRICT_CLOCK_POLICY = ClockSkewPolicy(
    maximum_future_skew_ns=0,
    maximum_observation_age_ns=_MAX_POLICY_NS,
    maximum_validity_ns=_MAX_POLICY_NS,
)


def checked_now(value: int | None, clock: Clock | None = None) -> int:
    result = (clock or SystemClock()).wall_time_ns() if value is None else value
    if type(result) is not int or result < 0:
        raise EngineeringError("invalid_time")
    return result


def validate_signed_window(
    observed_unix_ns: int,
    expires_unix_ns: int,
    now_unix_ns: int,
    policy: ClockSkewPolicy,
    *,
    error_code: str,
) -> None:
    """Fail closed unless one signed validity window satisfies ``policy``."""

    if not isinstance(policy, ClockSkewPolicy):
        raise EngineeringError("clock_policy_required")
    if (
        type(observed_unix_ns) is not int
        or type(expires_unix_ns) is not int
        or type(now_unix_ns) is not int
        or observed_unix_ns < 0
        or expires_unix_ns < 0
        or now_unix_ns < 0
        or expires_unix_ns <= observed_unix_ns
    ):
        raise EngineeringError(error_code)
    if observed_unix_ns > now_unix_ns + policy.maximum_future_skew_ns:
        raise EngineeringError(error_code)
    if now_unix_ns >= expires_unix_ns:
        raise EngineeringError(error_code)
    age = max(0, now_unix_ns - observed_unix_ns)
    if age > policy.maximum_observation_age_ns:
        raise EngineeringError(error_code)
    if expires_unix_ns - observed_unix_ns > policy.maximum_validity_ns:
        raise EngineeringError(error_code)
