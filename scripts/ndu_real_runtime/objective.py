"""Finite entropic utility shared by inference and differentiable training.

This is an empirical finite-horizon profile, not a Brownian/FBSDE solver.
External rubric values and real tool effects never become differentiable labels.
"""

import hashlib
import json
import math

PROFILE_ID = "hepta.ndu.finite-entropic.v1"
MEMORY_MODES = ("reset", "persistent")


def canonical_sha(value):
    raw = json.dumps(
        value, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode()
    return hashlib.sha256(raw).hexdigest()


def utility_profile(plan):
    return {
        "id": PROFILE_ID,
        "risk": plan.risk,
        "discount_per_second": plan.discount_per_second,
        "latency_weight": plan.latency_weight,
        "time_unit": "second",
        "terminal_range": [0.0, 1.0],
        "terminal": "independently_observed_delivery_rubric; critic_is_prediction_only",
        "edge": "-latency_weight*duration_seconds+discount_per_second**duration_seconds*continuation",
        "noise": "empirical_diagonal_gaussian; fixed_step_action_seed; no_dt_scaling",
        "cost_scope": "observed_latency; all_runtime_stages_retained; energy_and_money_unknown",
        "policy_improvement": "exact_sum_pi_times_frozen_action_Q; not_environment_REINFORCE",
    }


def forecast_seed(seed, step, action):
    # Independent of floating point features: finite-difference perturbations
    # keep the same base noise instead of changing the random experiment.
    material = json.dumps([seed, step, action], separators=(",", ":")).encode()
    return int.from_bytes(hashlib.sha256(material).digest()[:8], "big")


def edge_value(duration_seconds, continuation, plan):
    return (
        -plan.latency_weight * duration_seconds
        + plan.discount_per_second**duration_seconds * continuation
    )


def certainty_equivalent(values, probabilities, risk):
    x, p = tuple(values), tuple(probabilities)
    if (
        not x
        or len(x) != len(p)
        or not math.isfinite(risk)
        or risk < 0
        or any(not math.isfinite(v) for v in (*x, *p))
        or any(v < 0 for v in p)
        or not math.isclose(math.fsum(p), 1.0, rel_tol=0, abs_tol=1e-9)
    ):
        raise ValueError("Invalid predicted lottery or risk")
    total = math.fsum(p)
    p = tuple(probability / total for probability in p)
    mean = math.fsum(a * b for a, b in zip(x, p))
    if risk == 0:
        return mean
    positive = [
        (value, probability) for value, probability in zip(x, p) if probability > 0
    ]
    centered = [-risk * (value - mean) for value, _ in positive]
    if max(abs(value) for value in centered) <= 1e-3:
        correction = math.fsum(
            probability * math.expm1(value)
            for value, (_, probability) in zip(centered, positive)
        )
        return mean - math.log1p(correction) / risk
    # Discard zero-mass values before shifting; otherwise an impossible extreme
    # outcome can underflow every positive-probability term.
    minimum = min(value for value, _ in positive)
    exponential_mean = math.fsum(
        probability * math.exp(-risk * (value - minimum))
        for value, probability in positive
    )
    result = minimum - math.log(exponential_mean) / risk
    if not math.isfinite(result):
        raise ValueError("Entropic result exceeds the finite numeric domain")
    return result
