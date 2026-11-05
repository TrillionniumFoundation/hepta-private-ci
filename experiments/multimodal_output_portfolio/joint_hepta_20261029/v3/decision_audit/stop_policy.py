"""Frozen-cohort STOP-relative proposals, with a separate research allowance.

This reference consumes owner-admitted hard gates and simultaneous net-utility
bounds. It neither authenticates those inputs nor executes an effect. The caller
must durably reserve the returned envelope under an idempotent operation before
dispatch. A prediction, local advantage, or research reservation is not payment
authority, a model-adoption certificate, or chainwork.
"""

from dataclasses import asdict, dataclass, replace
from fractions import Fraction
import math

from .factorial import digest


def require(condition, message):
    if not condition:
        raise ValueError(message)


def finite(value):
    try:
        return type(value) in (int, float) and math.isfinite(value)
    except OverflowError:
        return False


def sha(value):
    require(
        isinstance(value, str) and len(value) == 64 and all(c in "0123456789abcdef" for c in value),
        "expected a SHA-256 binding",
    )


def resources(items):
    """Integer upper envelopes in declared physical units; unknown is not zero."""
    require(isinstance(items, tuple) and items, "immutable resource vector required")
    require(all(isinstance(x, tuple) and len(x) == 2 for x in items), "immutable resource pairs required")
    require(
        all(isinstance(k, str) and k.strip() and type(v) is int and v >= 0 for k, v in items),
        "invalid resource axis or integer envelope",
    )
    out = dict(items)
    require(len(out) == len(items), "duplicate resource axis")
    return out


@dataclass(frozen=True)
class Cohort:
    name: str
    critic_sha256: str
    objective_sha256: str
    continuation_sha256: str
    unit: str
    generation: int

    def __post_init__(self):
        for value in (self.critic_sha256, self.objective_sha256, self.continuation_sha256):
            sha(value)
        require(
            all(isinstance(x, str) and x.strip() for x in (self.name, self.unit)),
            "cohort and utility unit strings required",
        )
        require(type(self.generation) is int and self.generation >= 0, "invalid generation")


@dataclass(frozen=True)
class Bound:
    """Bounds on the declared remaining net utility, including future costs/risk.

    The support owner must certify coverage jointly across the frozen action and
    monitoring roster. This class checks arithmetic, not statistical coverage.
    """

    lower: float
    upper: float

    def __post_init__(self):
        require(
            all(finite(x) for x in (self.lower, self.upper)) and self.lower <= self.upper,
            "invalid finite utility bounds",
        )

    @classmethod
    def from_log_moment(cls, lower, upper, gamma):
        """Convert log E exp(-gamma*net_return) bounds to CE; endpoints reverse."""
        cls(lower, upper)
        require(finite(gamma) and gamma > 0, "positive finite CE gamma required")
        converted = cls(-upper / gamma, -lower / gamma)
        lo, hi = converted.lower, converted.upper
        # Preserve enclosure when division rounds a certified endpoint inward.
        if Fraction(lo) > -Fraction(upper) / Fraction(gamma):
            lo = math.nextafter(lo, -math.inf)
        if Fraction(hi) < -Fraction(lower) / Fraction(gamma):
            hi = math.nextafter(hi, math.inf)
        return cls(lo, hi)


@dataclass(frozen=True)
class HardGate:
    action: str
    status: str
    envelope: tuple[tuple[str, int], ...]
    reason: str = ""

    def __post_init__(self):
        require(self.status in ("admitted", "rejected"), "unknown hard admission")
        require(
            isinstance(self.action, str)
            and self.action.strip()
            and isinstance(self.reason, str)
            and (self.status != "rejected" or self.reason.strip()),
            "missing action or gate reason",
        )
        resources(self.envelope)


@dataclass(frozen=True)
class Report:
    cohort: Cohort
    state_sha256: str
    look: int
    support_sha256: str
    bounds: tuple[tuple[str, Bound | None], ...]
    available: tuple[tuple[str, int], ...]


@dataclass(frozen=True)
class Allowance:
    """Caller-persisted research balance. No outcome or prediction can replenish it."""

    policy_sha256: str
    next_look: int
    calls_left: int
    resources_left: tuple[tuple[str, int], ...]


@dataclass(frozen=True)
class Proposal:
    action: str
    mode: str
    delta_lower: float | None
    reservation: tuple[tuple[str, int], ...]
    next_allowance: Allowance
    rejected: tuple[tuple[str, str], ...]
    request_sha256: str


@dataclass(frozen=True)
class Policy:
    cohort: Cohort
    actions: tuple[str, ...]
    support_sha256: str
    max_looks: int
    exploration_order: tuple[str, ...]
    exploration_calls: int
    exploration_resources: tuple[tuple[str, int], ...]
    minimum_gain: float = 0.0

    def __post_init__(self):
        require(isinstance(self.cohort, Cohort), "frozen cohort required")
        sha(self.support_sha256)
        require(
            isinstance(self.actions, tuple)
            and all(isinstance(a, str) and a.strip() for a in self.actions)
            and len(set(self.actions)) == len(self.actions)
            and "stop" in self.actions,
            "unique action roster including STOP required",
        )
        require(type(self.max_looks) is int and self.max_looks > 0, "finite monitoring roster required")
        require(
            isinstance(self.exploration_order, tuple)
            and all(isinstance(a, str) for a in self.exploration_order)
            and len(set(self.exploration_order)) == len(self.exploration_order)
            and set(self.exploration_order) <= set(self.actions) - {"stop"},
            "invalid research roster",
        )
        require(type(self.exploration_calls) is int and self.exploration_calls >= 0, "invalid research count")
        require(finite(self.minimum_gain) and self.minimum_gain >= 0, "invalid minimum net gain")
        resources(self.exploration_resources)

    def initial_allowance(self):
        return Allowance(digest(asdict(self)), 0, self.exploration_calls, self.exploration_resources)

    def propose(self, report, gates, available, allowance, *, live_cohort, state_sha256):
        """Filter hard constraints first; choose supported gain, bounded research, or STOP.

        All envelopes include the selected continuation and terminal delivery.
        Bounds already include prospective costs in the objective's units; do not
        subtract a resource vector or sum local Cell advantages into them.
        """
        require(
            isinstance(report, Report) and isinstance(allowance, Allowance), "typed report/balance required"
        )
        require(report.cohort == self.cohort == live_cohort, "critic/objective/unit/generation drift")
        sha(state_sha256)
        require(report.state_sha256 == state_sha256, "stale public state")
        require(report.support_sha256 == self.support_sha256, "unadmitted bound support")
        require(
            type(report.look) is int
            and type(allowance.next_look) is int
            and report.look == allowance.next_look
            and 0 <= report.look < self.max_looks,
            "monitoring roster exhausted or replayed",
        )
        require(allowance.policy_sha256 == digest(asdict(self)), "research allowance belongs to other policy")
        require(
            type(allowance.calls_left) is int and 0 <= allowance.calls_left <= self.exploration_calls,
            "invalid research balance",
        )
        capacity, research, original = map(
            resources, (available, allowance.resources_left, self.exploration_resources)
        )
        require(set(capacity) == set(research) == set(original), "resource axes differ")
        require(resources(report.available) == capacity, "stale resource snapshot for Q bounds")
        require(all(research[k] <= original[k] for k in original), "research resource balance increased")
        require(
            isinstance(gates, tuple)
            and len(gates) == len(self.actions)
            and all(isinstance(g, HardGate) for g in gates),
            "incomplete hard gate roster",
        )
        hard = {g.action: g for g in gates}
        require(set(hard) == set(self.actions), "missing or repeated action gate")
        require(
            isinstance(report.bounds, tuple)
            and len(report.bounds) == len(self.actions)
            and all(isinstance(x, tuple) and len(x) == 2 and isinstance(x[0], str) for x in report.bounds),
            "incomplete immutable Q roster",
        )
        bounds = dict(report.bounds)
        require(set(bounds) == set(self.actions), "missing or repeated Q action")
        eligible, rejected = {}, {}
        for action in self.actions:
            gate = hard[action]
            envelope = resources(gate.envelope)
            require(set(envelope) == set(capacity), "unknown resource cost axis")
            if gate.status == "rejected":
                rejected[action] = gate.reason
            elif any(envelope[k] > capacity[k] for k in capacity):
                rejected[action] = "resource_limit"
            else:
                eligible[action] = envelope
        require("stop" in eligible, "no admissible STOP; owner-qualified fallback required")
        for action in eligible:
            require(bounds[action] is None or isinstance(bounds[action], Bound), "invalid admitted Q bound")
        stop = bounds["stop"]
        deltas = {
            action: (bound.lower - stop.upper, bound.upper - stop.lower)
            for action in eligible
            if action != "stop"
            if (bound := bounds[action]) is not None and stop is not None
        }
        require(all(finite(x) for pair in deltas.values() for x in pair), "nonfinite STOP-relative gain")
        for action, (lo, hi) in deltas.items():
            bound = bounds[action]
            if Fraction(lo) > Fraction(bound.lower) - Fraction(stop.upper):
                lo = math.nextafter(lo, -math.inf)
            if Fraction(hi) < Fraction(bound.upper) - Fraction(stop.lower):
                hi = math.nextafter(hi, math.inf)
            deltas[action] = lo, hi
        require(all(finite(x) for pair in deltas.values() for x in pair), "nonfinite outward gain")
        gains = {action: pair[0] for action, pair in deltas.items()}
        positive = [a for a in gains if gains[a] > self.minimum_gain]
        selected, mode = "stop", "stop"
        if positive:
            selected = max(positive, key=lambda a: gains[a])
            mode = "supported_gain"
        elif allowance.calls_left:
            for action in self.exploration_order:
                # A known nonpositive action does not consume the research pool.
                # A straddling interval or absent bound remains an open question.
                if action not in eligible:
                    continue
                unresolved = action not in deltas or deltas[action][1] > self.minimum_gain
                if unresolved and all(eligible[action][k] <= research[k] for k in research):
                    selected, mode = action, "research"
                    break
        next_allowance = replace(allowance, next_look=allowance.next_look + 1)
        if mode == "research":
            next_allowance = replace(
                next_allowance,
                calls_left=allowance.calls_left - 1,
                resources_left=tuple((k, research[k] - eligible[selected][k]) for k in research),
            )
        request = digest(
            {
                "policy": asdict(self),
                "report": asdict(report),
                "gates": [asdict(g) for g in gates],
                "available": available,
                "allowance": asdict(allowance),
            }
        )
        return Proposal(
            selected,
            mode,
            gains.get(selected),
            hard[selected].envelope,
            next_allowance,
            tuple(rejected.items()),
            request,
        )
