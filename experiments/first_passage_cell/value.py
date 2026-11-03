"""Finite renewal action values under a declared wait-after-current plan.

The deployed controller replans every control interval. These are exact-model
renewal expectations plus explicit quadrature error, not the Bellman value of
that replanning policy. The evaluation objective never contains the fitted
policy gap bias.
"""

from dataclasses import asdict, dataclass
import math

import numpy as np
from scipy.integrate import quad
from scipy.stats import invgauss, levy

from .kernels import first_passage


@dataclass(frozen=True)
class ValueProfile:
    running_rate: float = 0.6
    failure_penalty: float = 0.5
    control_interval: float = 0.5
    maximum_horizon: float = 2.0
    schema: str = "hepta.first-passage.value-profile.v1"
    recursive_profile: str = "hepta.ndu.recursive-utility.scalar.q32.v1"
    plan_policy: str = "WAIT_AFTER_CURRENT"
    deployment_policy: str = "MPC_REPLAN_EACH_HALF"


PROFILE = ValueProfile()
BIAS_GRID = np.linspace(-0.08, 0.08, 17)
THRESHOLD_GRID = np.linspace(0.05, 0.85, 17)
_RULES = {}


def _cdf_reference(t, x, mu, sigma):
    if t <= 0:
        return float(x <= 0)
    if x <= 0:
        return 1.0
    scale = x * x / (sigma * sigma)
    if abs(mu) < 1e-14:
        return float(levy.cdf(t, scale=scale))
    probability = float(invgauss.cdf(t, sigma * sigma / (x * abs(mu)), scale=scale))
    return probability * (math.exp(-2 * mu * x / (sigma * sigma)) if mu > 0 else 1.0)


def renewal_moments(parameters, distance, inputs, horizon, *, mode="renewal",
                    method="analytic", quadrature_order=48):
    """Expected active time and failure count, with deterministic refractory.

    T_n has the law (n-1)*a + tau_(x+(n-1)*reset), because Brownian first-passage
    times with the same drift/diffusion add over distances. a>0 makes the sum
    finite. The single-event comparator retains only n=1 with the same costs.
    """
    x, t = float(distance), float(horizon)
    mu, sigma = float(parameters.mu(inputs)), float(parameters.sigma)
    reset, refractory = float(parameters.reset_gap), float(parameters.refractory)
    if not all(math.isfinite(v) for v in (x, t, mu, sigma, reset, refractory)):
        raise ValueError("finite renewal inputs required")
    if x < 0 or t < 0 or t > PROFILE.maximum_horizon or sigma <= 0 or reset <= 0 or refractory <= 0:
        raise ValueError("unsupported renewal domain")
    if mode not in {"renewal", "single"} or method not in {"analytic", "quad"}:
        raise ValueError("unknown renewal or reference profile")
    if t == 0:
        return {"active_time": 0.0, "expected_failures": 0.0,
                "first_failure_probability": 0.0, "quadrature_error_estimate": 0.0,
                "omitted_refractory_bound": 0.0, "renewal_terms": 0}
    count = 1 if mode == "single" else int(math.ceil(t / refractory))
    if count > 512:
        raise ValueError("bounded renewal horizon exceeded")
    ds = x + np.arange(count) * reset
    upper = np.maximum(0.0, t - np.arange(count) * refractory)
    lower = np.maximum(0.0, upper - refractory)
    if method == "quad":
        probabilities = np.array([_cdf_reference(z, d, mu, sigma) for z, d in zip(upper, ds)])
        integrals, errors = [], []
        for lo, hi, d in zip(lower, upper, ds):
            val, err = quad(_cdf_reference, lo, hi, args=(d, mu, sigma),
                            epsabs=2e-11, epsrel=2e-10, limit=100)
            integrals.append(val)
            errors.append(err)
        lost = float(sum(integrals))
        error, omitted = float(sum(errors)), 0.0
    else:
        probabilities = np.asarray(first_passage(ds, mu, sigma, upper)["F"], dtype=float)
        active = probabilities > 1e-14
        # The skipped refractory integral is bounded by width times its upper CDF.
        omitted = float(np.sum((upper[~active] - lower[~active]) * probabilities[~active]))
        if quadrature_order not in _RULES:
            _RULES[quadrature_order] = np.polynomial.legendre.leggauss(quadrature_order)
        nodes, weights = _RULES[quadrature_order]
        midpoint = (lower[active] + upper[active]) / 2
        halfwidth = (upper[active] - lower[active]) / 2
        times = midpoint[:, None] + halfwidth[:, None] * nodes[None, :]
        values = first_passage(ds[active, None], mu, sigma, times)["F"]
        lost = float(np.sum(halfwidth * (np.asarray(values) @ weights)))
        error = None  # validated independently; not an a posteriori certificate
    active_time = t - lost
    if active_time < -1e-10 or active_time > t + 1e-10:
        raise ArithmeticError("renewal time conservation failed")
    return {"active_time": float(np.clip(active_time, 0, t)),
            "expected_failures": float(np.sum(probabilities)),
            "first_failure_probability": float(probabilities[0]),
            "quadrature_error_estimate": error, "omitted_refractory_bound": omitted,
            "renewal_terms": count}


def action_values(parameters, observation, *, mode="renewal", method="analytic", profile=PROFILE):
    """Predict complete candidate paths using exactly the supplied public state."""
    if profile != PROFILE:
        raise ValueError("unsupported objective, timing or recursive-utility profile")
    y = float(observation["level"])
    inputs = tuple(float(v) for v in observation["inputs"])
    cost = float(observation["repair_cost"])
    remaining = float(observation["remaining_duration"])
    pending = float(observation["refractory_remaining"])
    if not all(math.isfinite(v) for v in (y, cost, remaining, pending, *inputs)):
        raise ValueError("finite public observation required")
    if remaining <= 0 or remaining > profile.maximum_horizon or cost < 0 or pending < 0:
        raise ValueError("invalid horizon, action cost or refractory state")
    legal = {str(action).upper() for action in observation["legal_actions"]}
    if not legal or not legal <= {"WAIT", "REPAIR", "STOP"}:
        raise ValueError("unsupported action set")
    distance = y - parameters.barrier
    # A model can put a valid observed state below its estimated boundary.
    # That forecast has an explicit immediate-event atom; it is not clipped
    # to a fictitious small positive distance.
    distance = max(0.0, float(distance))
    endpoints = np.minimum(np.arange(1, int(math.ceil(remaining / profile.control_interval)) + 1)
                           * profile.control_interval, remaining)
    rows = {}
    for action in ("STOP", "WAIT", "REPAIR"):
        if action not in legal:
            continue
        if action == "STOP":
            rows[action] = {"value": 0.0, "risk": 0.0, "resource_cost": 0.0,
                            "terminal": 0.0, "events": [{"instant": 0.0, "discount": 1.0}],
                            "expected_active_time": 0.0, "expected_failure_count": 0.0}
            continue
        delay = parameters.refractory if action == "REPAIR" else pending
        start = parameters.reset_gap if action == "REPAIR" else distance
        charge = cost if action == "REPAIR" else 0.0
        prefixes = [renewal_moments(parameters, start, inputs, max(0.0, float(e) - delay),
                                   mode=mode, method=method) for e in endpoints]
        previous, events = 0.0, []
        for i, item in enumerate(prefixes):
            total = profile.running_rate * item["active_time"] - profile.failure_penalty * item["expected_failures"]
            events.append({"instant": total - previous - (charge if i == 0 else 0.0),
                           "discount": 1.0, "elapsed": float(endpoints[i] - (endpoints[i-1] if i else 0.0))})
            previous = total
        last = prefixes[-1]
        rows[action] = {"value": float(previous - charge), "risk": last["first_failure_probability"],
                        "resource_cost": float(charge), "terminal": 0.0, "events": events,
                        "expected_active_time": last["active_time"],
                        "expected_failure_count": last["expected_failures"],
                        "omitted_refractory_bound": last["omitted_refractory_bound"]}
    return {"schema": "hepta.first-passage.action-values.v1", "profile": asdict(profile),
            "mode": mode, "method": method, "distance": distance,
            "actions": rows, "predict": {"first_passage": rows.get("WAIT", {}).get("risk", 0.0),
                                           "survival": 1 - rows.get("WAIT", {}).get("risk", 0.0)},
            "continuation_value": rows.get("WAIT", {}).get("value", 0.0),
            "planning_scope": "WAIT_AFTER_CURRENT; not exact deployed MPC policy value"}


def select_action(parameters, observation, policy, *, bias=0.0, threshold=0.35, native=None, context=None, forecast_cache=None):
    """Return the deployed action and the raw, unmodified utility predictions.

    Both learned boundary families have one development-selected gap bias.
    It is an action-selection calibration, never a task cost or NDU reward.
    """
    if not math.isfinite(float(bias)) or not -0.08 <= float(bias) <= 0.08:
        raise ValueError("unsupported policy bias")
    if not math.isfinite(float(threshold)) or not 0.05 <= float(threshold) <= 0.85:
        raise ValueError("unsupported learned boundary threshold")
    legal = {str(action).upper() for action in observation["legal_actions"]}
    if policy in {"always_wait", "always_repair", "always_stop"}:
        desired = {"always_wait": "WAIT", "always_repair": "REPAIR", "always_stop": "STOP"}[policy]
        action = desired if desired in legal else "WAIT"
        return {"action": action, "policy": policy, "bias": 0.0, "values": None,
                "native_receipt": None, "planning_scope": "registered fixed action"}
    if policy not in {"ordinary", "endogenous", "learned_threshold", "fixed_shared6", "fixed7", "numerical_reference"}:
        raise ValueError("unknown policy")
    mode = "single" if policy == "ordinary" else "renewal"
    method = "quad" if policy == "numerical_reference" else "analytic"
    key = (tuple(sorted(asdict(parameters).items())), tuple(sorted(
        (name, tuple(value) if isinstance(value, (list, tuple)) else value)
        for name, value in observation.items())), mode, method)
    if forecast_cache is not None and key in forecast_cache:
        values = forecast_cache[key]
    else:
        values = action_values(parameters, observation, mode=mode, method=method)
        if forecast_cache is not None:
            forecast_cache[key] = values
    native_receipt = None
    if native is not None:
        native_receipt = native.evaluate_forecast(parameters, observation, values,
                                                  policy=policy, bias=bias, context={**(context or {}),
                                                      "boundary_threshold": float(threshold) if policy == "learned_threshold" else None})
        raw = native_receipt["action_values"]
    else:
        raw = {name: row["value"] for name, row in values["actions"].items()}
    if policy.startswith("fixed") or policy == "learned_threshold":
        threshold = float(threshold) if policy == "learned_threshold" else 0.35
        preferred = "REPAIR" if values["distance"] <= threshold and "REPAIR" in legal else "WAIT"
        action = preferred if raw.get(preferred, -math.inf) > 0 else "STOP"
    else:
        adjusted = dict(raw)
        if "REPAIR" in adjusted:
            adjusted["REPAIR"] -= float(bias)
        # Exact ties choose STOP, then WAIT. There is no hidden candidate-ID sort.
        order = {"STOP": 0, "WAIT": 1, "REPAIR": 2}
        action = min(adjusted, key=lambda name: (-adjusted[name], order[name]))
    return {"action": action, "policy": policy, "bias": float(bias),
            "threshold": float(threshold) if policy == "learned_threshold" else None, "values": values,
            "native_receipt": native_receipt, "planning_scope": values["planning_scope"]}
