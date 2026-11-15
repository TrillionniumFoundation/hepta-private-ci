"""One-step, interval-supported NDU computation control for the existing loop.

This is a FLOAT64 linear discounted, nonnegative continuation profile, not the
native Q32 reference or a general stochastic FBSDE solver. External estimates
remain unauthenticated. No outcome labels, trainable weights or goal edits enter
this controller. Scenario durations and costs are UPPER bounds; their mass is a
complete declared joint distribution, not an empirical independence certificate.
"""
from __future__ import annotations

import math
from dataclasses import asdict, dataclass

from next_round_matrix import _digest
from paired_execution import _integer, _sha

SCHEMA = "hepta.ndu.reasoning-policy.v1"
PROFILE = "linear_discounted_nonnegative_continuation_float64.v1"
MASS = 1_000_000


def freeze_policy(*, objective_sha256, subject_id, critic_sha256, critic_cutoff_ns,
                  expires_at_ns, discount_rate_per_second, cost_per_formula_flop,
                  cost_per_latency_ns, minimum_margin, max_estimate_age_ns, execution):
    """Bind objective, critic revision, units and thresholds BEFORE execution."""
    for value in (objective_sha256, critic_sha256):
        _sha(value, "objective/critic artifact")
    if not isinstance(subject_id, str) or not 1 <= len(subject_id.encode()) <= 256:
        raise ValueError("bounded registered subject identity required")
    for value in (critic_cutoff_ns, expires_at_ns, max_estimate_age_ns):
        _integer(value, "policy time", 1)
    if expires_at_ns <= critic_cutoff_ns:
        raise ValueError("critic policy expired before training cutoff")
    for value in (discount_rate_per_second, cost_per_formula_flop, cost_per_latency_ns, minimum_margin):
        if type(value) not in (float, int) or not math.isfinite(value) or value < 0:
            raise ValueError("finite nonnegative utility coefficients required")
    from execution_meter import validate_policy as validate_meter_policy
    from paired_execution import PHASES
    import copy
    execution = copy.deepcopy(execution)
    if not isinstance(execution, dict) or set(execution) != {"max_calls", "max_rounds", "meter_policy", "phase_caps"}:
        raise ValueError("complete execution budget required")
    validate_meter_policy(execution["meter_policy"])
    for key, minimum, maximum in (("max_calls", 2, 192), ("max_rounds", 1, 64)):
        _integer(execution[key], key, minimum)
        if execution[key] > maximum:
            raise ValueError("execution depth/call ceiling exceeded")
    if not isinstance(execution["phase_caps"], dict) or set(execution["phase_caps"]) != set(PHASES):
        raise ValueError("complete phase work caps required")
    for value in execution["phase_caps"].values():
        _integer(value, "phase work cap")
    body = dict(schema=SCHEMA, utility_profile=PROFILE, objective_sha256=objective_sha256,
                subject_id=subject_id, critic_sha256=critic_sha256, critic_cutoff_ns=critic_cutoff_ns,
                expires_at_ns=expires_at_ns, discount_rate_per_second=discount_rate_per_second,
                cost_per_formula_flop=cost_per_formula_flop, cost_per_latency_ns=cost_per_latency_ns,
                minimum_margin=minimum_margin, max_estimate_age_ns=max_estimate_age_ns, execution=execution)
    return {**body, "policy_id": _digest(body)}


def validate_policy(policy, *, task_as_of_ns):
    if not isinstance(policy, dict):
        raise ValueError("frozen reasoning policy required")
    values = {k: v for k, v in policy.items() if k not in ("schema", "utility_profile", "policy_id")}
    try:
        expected = freeze_policy(**values)
    except TypeError as exc:
        raise ValueError("incomplete/unknown reasoning policy fields") from exc
    if _digest(expected) != _digest(policy):
        raise ValueError("reasoning policy identity changed")
    _integer(task_as_of_ns, "task boundary", 1)
    if not policy["critic_cutoff_ns"] < task_as_of_ns < policy["expires_at_ns"]:
        raise ValueError("critic must precede this task and remain valid")


@dataclass(frozen=True)
class ContinuationBranch:
    mass_ppm: int
    value_lower: float
    value_upper: float
    duration_upper_ns: int
    formula_work_upper: int


@dataclass(frozen=True)
class ContinuationEstimate:
    context_id: str
    critic_sha256: str
    support_sha256: str
    observed_through_ns: int
    valid_until_ns: int
    stop_upper: float
    branches: tuple[ContinuationBranch, ...]

    def validate(self):
        for identity in (self.context_id, self.critic_sha256, self.support_sha256):
            _sha(identity, "continuation/support identity")
        _integer(self.observed_through_ns, "estimate filtration time", 1)
        _integer(self.valid_until_ns, "estimate expiry", 1)
        if self.valid_until_ns <= self.observed_through_ns:
            raise ValueError("invalid estimate validity window")
        if (type(self.stop_upper) not in (int, float) or not math.isfinite(self.stop_upper)
                or not 0 <= self.stop_upper <= 1):
            raise ValueError("nonnegative normalized stop utility required")
        if type(self.branches) is not tuple or not 1 <= len(self.branches) <= 16:
            raise ValueError("bounded immutable joint continuation scenarios required")
        for branch in self.branches:
            if type(branch) is not ContinuationBranch:
                raise ValueError("typed continuation branch required")
            _integer(branch.mass_ppm, "scenario probability mass", 1)
            _integer(branch.duration_upper_ns, "scenario duration bound", 1)
            _integer(branch.formula_work_upper, "scenario work bound")
            if branch.duration_upper_ns > 3_600_000_000_000 or branch.formula_work_upper > 10**18:
                raise ValueError("scenario exceeds the bounded reference envelope")
            if (any(type(v) not in (int, float) or not math.isfinite(v)
                    for v in (branch.value_lower, branch.value_upper))
                    or not 0 <= branch.value_lower <= branch.value_upper <= 1):
                raise ValueError("ordered nonnegative value interval required")
        if sum(b.mass_ppm for b in self.branches) != MASS:
            raise ValueError("scenario mass must sum exactly to one million")


@dataclass(frozen=True)
class DecisionContext:
    policy_id: str
    task_sha256: str
    candidate_sha256: str
    feedback_sha256: str
    trace_sha256: str
    as_of_ns: int
    rounds_left: int
    calls_left: int
    remaining_formula_work: int | None
    remaining_wall_ns: int

    @property
    def context_id(self):
        return _digest(asdict(self))


def decide(policy, context, estimate, *, now_ns, resources):
    """Conservative one-step comparison; sunk valuation cost is NOT charged twice.

    Each branch describes the NEXT boundary: utility there excludes this
    segment's costs and has not yet been discounted for this segment. Compute
    E[exp(-r*dt_upper)*U_lower - lambda*C_upper] branch by branch. Do not replace
    E[discount*U] with discount(E[dt])*E[U]. Worst branch bounds must also fit the
    remaining run resources AFTER the critic call. This is conditional on the
    validity/completeness of the external support, not a confidence certificate.
    """
    if type(context) is not DecisionContext or context.policy_id != policy["policy_id"]:
        raise ValueError("context is not bound to the fixed policy")
    _integer(now_ns, "decision time", 1)
    if now_ns < context.as_of_ns:
        raise ValueError("decision clock moved backwards")
    report = dict(policy_id=policy["policy_id"], context_id=context.context_id,
                  context=asdict(context), estimate=None, decision_at_ns=now_ns,
                  post_critic_resources=dict(resources),
                  continue_computation=False, reason="unsupported_continuation", estimate_id=None,
                  declared_continuation_lower=None, stop_upper=None, marginal_cost_upper=None,
                  support_authenticity_verified=False, confidence_bound_established=False)
    if estimate is None:
        return report
    if type(estimate) is not ContinuationEstimate:
        raise ValueError("bound controller requires a typed estimate, never a scalar score tuple")
    estimate.validate()
    if estimate.context_id != context.context_id or estimate.critic_sha256 != policy["critic_sha256"]:
        raise ValueError("stale context or substituted critic")
    if not policy["critic_cutoff_ns"] <= estimate.observed_through_ns <= context.as_of_ns:
        raise ValueError("estimate used observations beyond its decision filtration")
    report.update(estimate_id=_digest(asdict(estimate)), estimate=asdict(estimate), stop_upper=estimate.stop_upper)
    if (now_ns >= min(policy["expires_at_ns"], estimate.valid_until_ns)
            or now_ns - estimate.observed_through_ns > policy["max_estimate_age_ns"]):
        return {**report, "reason": "expired_support"}
    remaining = resources["remaining_formula_work"]
    wall = resources["remaining_wall_ns"]
    if remaining is None or context.remaining_formula_work is None:
        return {**report, "reason": "incomplete_work_coverage"}
    _integer(remaining, "remaining formula work")
    _integer(wall, "remaining wall budget")
    if remaining > context.remaining_formula_work or wall > context.remaining_wall_ns:
        raise ValueError("resources increased across one decision boundary")
    if context.rounds_left < 1 or context.calls_left < 3:
        return {**report, "reason": "insufficient_callback_budget"}
    max_work = max(b.formula_work_upper for b in estimate.branches)
    max_time = max(b.duration_upper_ns for b in estimate.branches)
    if max_work > remaining or max_time >= wall:
        return {**report, "reason": "infeasible_continuation"}
    lower, costs = [], []
    for branch in estimate.branches:
        p = branch.mass_ppm / MASS
        marginal = (policy["cost_per_formula_flop"] * branch.formula_work_upper
                    + policy["cost_per_latency_ns"] * branch.duration_upper_ns)
        discount_exponent = policy["discount_rate_per_second"] * (branch.duration_upper_ns / 1e9)
        if not math.isfinite(marginal) or not math.isfinite(discount_exponent):
            raise ValueError("utility coefficient arithmetic overflow")
        lower.append(p * (math.exp(-discount_exponent) * branch.value_lower - marginal))
        costs.append(p * marginal)
    value = math.fsum(lower)
    gain = value - estimate.stop_upper
    if not math.isfinite(value) or not math.isfinite(gain):
        raise ValueError("nonfinite continuation comparison")
    admitted = gain > policy["minimum_margin"]
    return {**report, "continue_computation": admitted,
            "reason": "supported_net_gain" if admitted else "no_supported_net_gain",
            "declared_continuation_lower": value, "marginal_cost_upper": math.fsum(costs),
            "worst_branch_formula_work": max_work, "worst_branch_duration_ns": max_time,
            "comparison_uses_post_critic_resources": True, "sunk_critic_cost_subtracted_again": False}
