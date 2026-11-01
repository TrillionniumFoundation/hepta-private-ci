"""Continuous Brownian first passage and stochastic-clock renewal enclosures.

The reference has no upper reflecting boundary. Positive convolutions include
arbitrarily many complete active -> R1 -> R2 -> active cycles. The enclosure
proof is exact mathematics conditional on the supplied CDF bounds. The current
float64 CDF calculations, with an explicit padding, are numerical evidence, not
a directed-rounding interval arithmetic implementation.
"""

import numpy as np
from scipy.special import log_ndtr, ndtr


def first_hit_cdf(x, t, mu, sigma):
    """P(inf{s>=0: x+mu*s+sigma*W_s<=0} <= t), including x=0."""
    x, t = np.broadcast_arrays(np.asarray(x, float), np.asarray(t, float))
    if sigma <= 0 or np.any(x < 0) or np.any(t < 0):
        raise ValueError("Need sigma>0, x>=0 and t>=0")
    safe_t = np.where(t == 0, 1.0, t)
    scale = sigma*np.sqrt(safe_t)
    first = ndtr((-x-mu*safe_t)/scale)
    second = np.exp(-2*mu*x/(sigma*sigma)+log_ndtr((-x+mu*safe_t)/scale))
    result = np.clip(first+second, 0, 1)
    return np.where(x == 0, 1.0, np.where(t == 0, 0.0, result))


def gaussian_bin_masses(edges, mean, sd, support=0.8):
    edges = np.asarray(edges, float)
    cdf = ndtr((np.minimum(edges, support)-mean)/sd)
    norm = ndtr((support-mean)/sd)-ndtr(-mean/sd)
    return np.diff(cdf)/norm


def mixture_cdf_bounds(times, mu, sigma, mean, sd, bins=512,
                       support=0.8, cdf_padding=2e-13):
    """Monotonicity in initial x bounds a continuous truncated-Gaussian law.

    Bin masses are analytic normal-CDF differences; absorption CDF decreases in
    x. Moving all bin mass to its right/left endpoint gives lower/upper bounds.
    cdf_padding records an assumed bound on all evaluated mixture-CDF error.
    """
    edges = np.linspace(0, support, bins+1)
    mass = gaussian_bin_masses(edges, mean, sd, support)
    t = np.asarray(times, float)[None, :]
    lower = mass @ first_hit_cdf(edges[1:, None], t, mu, sigma)
    upper = mass @ first_hit_cdf(edges[:-1, None], t, mu, sigma)
    lower = np.maximum.accumulate(np.clip(lower-cdf_padding, 0, 1))
    upper = np.maximum.accumulate(np.clip(upper+cdf_padding, 0, 1))
    return lower, upper


def _duration_pmf(cdf, fast, steps):
    # Fast: floor(duration/dt), including an atom at zero.
    # Slow: ceil(duration/dt). Remaining probability lies beyond this horizon.
    values = cdf[1:steps+2] if fast else cdf[:steps+1]
    pmf = np.diff(np.r_[0.0, values])
    if pmf.min() < -2e-14 or values.max() > 1+2e-14:
        raise ArithmeticError("Invalid duration CDF")
    return np.maximum(pmf, 0)


def _convolve(a, b, size):
    return np.convolve(a, b)[:size]


def _resolvent(base, cycle, weight):
    """Solve u=base+weight*cycle*u, retaining the zero-time renewal atom."""
    denominator = 1-weight*cycle[0]
    if denominator <= 0:
        raise ArithmeticError("Zero-duration cycle has unresolved infinite renewal")
    out = np.empty_like(base)
    for i in range(len(base)):
        out[i] = (base[i]+weight*np.dot(cycle[1:i+1], out[:i][::-1]))/denominator
    return out


def _clock_statistics(initial_hit, reset_hit, phase, retention):
    size = len(phase)
    initial_exit1 = _convolve(initial_hit, phase, size)
    reset_exit1 = _convolve(reset_hit, phase, size)
    initial_cycle = _convolve(initial_exit1, phase, size)
    reset_cycle = _convolve(reset_exit1, phase, size)
    out = {}
    for label, weight in (("counts", 1.0), ("weighted_counts", retention)):
        rows = []
        for initial_event, reset_event in (
            (initial_hit, reset_hit), (initial_exit1, reset_exit1),
            (initial_cycle, reset_cycle)
        ):
            recurring = _resolvent(np.cumsum(reset_event), reset_cycle, weight)
            expected = np.cumsum(initial_event)+weight*_convolve(initial_cycle, recurring, size)
            rows.append(expected)
        out[label] = np.asarray(rows)
    out["probability_at_least_two_resets"] = np.cumsum(_convolve(initial_cycle, reset_cycle, size))
    out["zero_duration_cycle_mass"] = float(reset_cycle[0])
    return out


def _phase_intervals(fast, slow, weight):
    # Event rows are hit, R1-exit and reset. Differences telescope pathwise.
    hf, lf, mf = fast
    hs, ls, ms = slow
    lower = np.stack((1-hf+weight*ms, hs-lf, ls-mf))
    upper = np.stack((1-hs+weight*mf, hf-ls, lf-ms))
    return np.clip(lower, 0, 1), np.clip(upper, 0, 1)


def renewal_enclosure(mu, sigma, reset_mean, initial_mean, initial_sd, total_time,
                      steps=1024, bins=256, recovery=0.35, retention=0.75,
                      initial_bit0=1.0, reset_sd=0.1, support=0.8,
                      cdf_padding=2e-13):
    """Bound phase, content and their joint law for an initial active Gaussian.

    Phase order: active, R1, R2. Joint array shape is [2,3,steps+1]. The returned
    interval is conservative: separate event-count intervals are subtracted.
    It does not bound the active location law or arbitrary financial payoffs.
    """
    if total_time <= 0 or steps < 1 or bins < 1 or recovery <= 0:
        raise ValueError("Positive time, steps, bins and recovery required")
    if not 0 <= retention <= 1 or not 0 <= initial_bit0 <= 1:
        raise ValueError("Invalid retention or content probability")
    dt = total_time/steps
    times = np.arange(steps+2)*dt
    reset_bounds = mixture_cdf_bounds(times, mu, sigma, reset_mean, reset_sd,
                                      bins, support, cdf_padding)
    initial_bounds = mixture_cdf_bounds(times, mu, sigma, initial_mean, initial_sd,
                                        bins, support, cdf_padding)
    exp_cdf = -np.expm1(-2/recovery*times)
    exp_bounds = (np.clip(exp_cdf-cdf_padding, 0, 1),
                  np.clip(exp_cdf+cdf_padding, 0, 1))
    clocks = {}
    for label, fast, bound_index in (("fast", True, 1), ("slow", False, 0)):
        ihit = _duration_pmf(initial_bounds[bound_index], fast, steps)
        rhit = _duration_pmf(reset_bounds[bound_index], fast, steps)
        phase = _duration_pmf(exp_bounds[bound_index], fast, steps)
        clocks[label] = _clock_statistics(ihit, rhit, phase, retention)
    fast, slow = clocks["fast"], clocks["slow"]
    phase_lo, phase_hi = _phase_intervals(fast["counts"], slow["counts"], 1.0)
    weight_lo, weight_hi = _phase_intervals(
        fast["weighted_counts"], slow["weighted_counts"], retention)
    # Weighted phase occupancy is eta^N times ordinary phase occupancy.
    weight_hi = np.minimum(weight_hi, phase_hi)
    content_weight_lo = np.clip(1-(1-retention)*fast["weighted_counts"][2], 0, 1)
    content_weight_hi = np.clip(1-(1-retention)*slow["weighted_counts"][2], 0, 1)
    joint_lo, joint_hi = [], []
    for coefficient in (initial_bit0-0.5, 0.5-initial_bit0):
        if coefficient >= 0:
            low = 0.5*phase_lo+coefficient*weight_lo
            high = 0.5*phase_hi+coefficient*weight_hi
        else:
            low = 0.5*phase_lo+coefficient*weight_hi
            high = 0.5*phase_hi+coefficient*weight_lo
        joint_lo.append(np.maximum(low, 0))
        joint_hi.append(np.minimum(high, phase_hi))
    return {
        "times": times[:steps+1], "phase_lower": phase_lo, "phase_upper": phase_hi,
        "weighted_phase_lower": weight_lo, "weighted_phase_upper": weight_hi,
        "content_weight_lower": content_weight_lo, "content_weight_upper": content_weight_hi,
        "joint_lower": np.asarray(joint_lo), "joint_upper": np.asarray(joint_hi),
        "at_least_two_resets_lower": slow["probability_at_least_two_resets"],
        "at_least_two_resets_upper": fast["probability_at_least_two_resets"],
        "fast_zero_cycle_mass": fast["zero_duration_cycle_mass"],
        "clock_step": dt, "initial_reset_bin_width": support/bins,
        "cdf_padding": cdf_padding,
        "scope": "Continuous renewal quantities; enclosures conditional on CDF arithmetic accuracy; active-location law not enclosed."
    }
