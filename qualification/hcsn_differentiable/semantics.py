"""Mathematical interpretation, independent of any numerical qualification.

The regime diagnostic concerns an unconditioned continuum Brownian process
with a constant lower boundary, identity reset and fixed delay. It does not
describe a filtered neural posterior or certify a finite probability grid.
No Torch import, network construction or experiment is triggered here.
"""

import json
import math
from pathlib import Path


def semantic_contract():
    """Read the versioned object/API map without importing its implementations."""
    return json.loads(Path(__file__).with_name("semantic_contract.json").read_text())


def long_run_regime(*, mu, sigma, distance, reset_distance, refractory):
    """Classify constant-drift renewal, using the lower boundary at zero.

    ``None`` means mathematically infinite only for quantities named in
    ``infinite_quantities``. Arithmetic overflow is rejected separately.
    Probabilities may underflow in FP64; their finite logarithms are retained.
    The asymptotic event rate is zero for both null and defective renewal;
    this does not assert the existence of a stationary probability density.
    An exactly zero drift is not replaced by an epsilon or a sign tolerance.
    """
    inputs = dict(
        mu=mu,
        sigma=sigma,
        distance=distance,
        reset_distance=reset_distance,
        refractory=refractory,
    )
    for name, value in inputs.items():
        if (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(value)
        ):
            raise ValueError(f"{name} must be a finite real scalar")
    if min(sigma, distance, reset_distance) <= 0 or refractory < 0:
        raise ValueError("sigma/distances must be positive and refractory nonnegative")
    variance = sigma * sigma
    if not 0 < variance < math.inf:
        raise FloatingPointError("sigma squared is not representable in FP64")
    log_hit = -2 * mu * distance / variance if mu > 0 else 0.0
    log_reset_hit = -2 * mu * reset_distance / variance if mu > 0 else 0.0
    if not all(math.isfinite(value) for value in (log_hit, log_reset_hit)):
        raise FloatingPointError("eventual-hit logarithm is unresolved in FP64")

    if mu < 0:
        mean_hit = distance / (-mu)
        mean_cycle = refractory + reset_distance / (-mu)
        rate = 1 / mean_cycle
        total = None
        infinite = ["expected_total_events"]
        regime = "finite_mean_renewal"
    elif mu == 0:
        mean_hit = mean_cycle = total = None
        rate = 0.0
        infinite = ["mean_first_hit_time", "mean_cycle_time", "expected_total_events"]
        regime = "infinite_mean_renewal"
    else:
        mean_hit = mean_cycle = None
        rate = 0.0
        escape = -math.expm1(log_reset_hit)
        if escape <= 0:
            raise FloatingPointError("positive-drift escape probability is unresolved")
        total = math.exp(log_hit - math.log(escape))
        infinite = ["mean_first_hit_time", "mean_cycle_time"]
        regime = "defective_renewal"
    if any(
        value is not None and not math.isfinite(value)
        for value in (mean_hit, mean_cycle, rate, total)
    ):
        raise FloatingPointError("finite renewal diagnostic overflowed FP64")
    return dict(
        schema="hcsn-continuum-drift-regime-v1",
        regime=regime,
        inputs=inputs,
        eventual_hit_probability=math.exp(log_hit),
        log_eventual_hit_probability=log_hit,
        reset_hit_probability=math.exp(log_reset_hit),
        log_reset_hit_probability=log_reset_hit,
        mean_first_hit_time=mean_hit,
        mean_cycle_time=mean_cycle,
        asymptotic_event_rate=rate,
        expected_total_events=total,
        infinite_quantities=infinite,
        numerical_qualification=False,
        filtered_network_claim=False,
    )
