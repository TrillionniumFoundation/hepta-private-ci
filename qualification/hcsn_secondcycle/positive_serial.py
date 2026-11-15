"""Positive serial-excursion renewal statistics candidate, two cycles maximum.

This new kernel consumes frozen rates and reset laws. It does not run a DDE,
project per-step hit flux, or provide a current spatial-state checkpoint.
The H channel is a killed auxiliary CTMC; it is not physical active mass.
"""

from fractions import Fraction
import math
import time
import resource
import mpmath as mp
import numpy as np
from scipy.special import gammainc, gammaincc


class Budget:
    def __init__(self, *, max_calls=72, max_terms=2500000, max_cpu_seconds=600.0):
        self.started_cpu = time.process_time()
        self.max_calls, self.max_terms = max_calls, max_terms
        self.max_cpu_seconds = max_cpu_seconds
        self.calls, self.terms = 0, 0

    def enter(self, terms):
        self.calls += 1
        self.terms += terms
        if self.calls > self.max_calls or self.terms > self.max_terms:
            raise RuntimeError("frozen positive-kernel call/term budget exceeded")
        self.check()

    def check(self):
        if resource.getrusage(resource.RUSAGE_SELF).ru_maxrss > 512*1024:
            raise RuntimeError("frozen 512 MiB RSS guard exceeded")
        if time.process_time() - self.started_cpu > self.max_cpu_seconds:
            raise RuntimeError("frozen CPU budget exceeded")


def _law(value, n, name):
    value = np.asarray(value, dtype=float)
    if value.shape != (n,) or not np.isfinite(value).all() or value.min() < 0:
        raise ValueError("finite nonnegative " + name + " required")
    # No normalization/repair: the two frozen domain stencils and controls
    # satisfy an EXACT rational probability total when FP64 values are decoded.
    if sum((Fraction.from_float(float(v)) for v in value), Fraction(0)) != 1:
        raise ValueError("exact-probability " + name + " required; no renormalization")
    return value


def _gamma_interval(k, hi, lo):
    upper, lower = gammainc(k + 1, hi), gammainc(k + 1, lo)
    return np.where(lower > .5, gammaincc(k + 1, lo) - gammaincc(k + 1, hi),
                    upper - lower)


def serial_phase_counts(down, up, initial, reset, *, cycles, horizon,
                        discount=.15, phase_width=.025, budget):
    """M_n and release-discounted H_n in ACTIVE clock before fixed delays.

    n serial active excursions use the true lower exit law as the next reset
    source. Initial remaining phase is uniform. Callers shift the deadline by
    (n-1)*delay and multiply H by exp[-q(n-1)*delay] exactly once.
    """
    started, cpu = time.perf_counter(), time.process_time()
    down, up = np.asarray(down, float), np.asarray(up, float)
    n = len(down)
    if (down.shape != (n,) or up.shape != (n,) or not 1 <= n <= 1023
            or not np.isfinite(np.r_[down, up]).all()
            or np.min(np.r_[down, up]) < 0
            or type(cycles) is not int or cycles not in (1, 2)
            or not math.isfinite(horizon) or not 0 < horizon <= .36
            or isinstance(discount, bool) or not math.isfinite(discount) or not .001 <= discount <= 4
            or not math.isfinite(phase_width) or not 0 < phase_width <= .2):
        raise ValueError("frozen bounded serial geometry/deadline required")
    initial, reset = _law(initial, n, "initial"), _law(reset, n, "reset")
    rates = down + up
    nu = float(np.nextafter(rates.max() + discount, np.inf))
    if rates.max() <= 0 or nu - discount <= 0:
        raise ValueError("strict positive jump bound required")
    lam = nu * horizon
    cutoff = math.ceil(lam + 14 * math.sqrt(lam) + 100)
    if cutoff + 1 > 250000:
        raise RuntimeError("frozen per-call term budget exceeded")
    budget.enter(cutoff + 1)
    k = np.arange(cutoff + 1)
    lo = max(0.0, horizon - phase_width)
    coefficients_m = _gamma_interval(k, nu * horizon, nu * lo) / (nu * phase_width)
    effective = nu - discount
    coefficients_h = (np.exp(-discount * horizon + k * math.log1p(discount / effective))
                      * _gamma_interval(k, effective * horizon, effective * lo)
                      / (effective * phase_width))
    if (not np.isfinite(np.r_[coefficients_m, coefficients_h]).all()
            or min(coefficients_m.min(), coefficients_h.min()) < 0):
        raise ArithmeticError("positive gamma coefficient construction unresolved")
    stay = np.vstack((1 - rates / nu, 1 - (rates + discount) / nu))
    if stay.min() < 0:
        raise ArithmeticError("positive transition construction unresolved")
    left, right = down / nu, up / nu
    active = np.zeros((2, cycles, n))
    active[:, 0, :] = initial
    hit, escape, killed = np.zeros(2), np.zeros(2), np.zeros(2)
    total, compensation = np.zeros(2), np.zeros(2)
    max_sampled_mass_drift = 0.0
    samples = 0
    for exponent, (cm, ch) in enumerate(zip(coefficients_m, coefficients_h)):
        term = np.array((cm, ch)) * hit - compensation
        value = total + term
        compensation = (value - total) - term
        total = value
        if exponent == cutoff:
            break
        old = active
        active = old * stay[:, None, :]
        active[:, :, :-1] += old[:, :, 1:] * left[None, None, 1:]
        active[:, :, 1:] += old[:, :, :-1] * right[None, None, :-1]
        lower_flux = old[:, :, 0] * left[0]
        if cycles == 2:
            active[:, 1, :] += lower_flux[:, 0, None] * reset[None, :]
        hit += lower_flux[:, -1]
        escape += old[:, :, -1].sum(axis=1) * right[-1]
        killed[1] += old[1].sum() * (discount / nu)
        if (exponent + 1) % 512 == 0:
            mass = active.sum(axis=(1, 2)) + hit + escape + killed
            max_sampled_mass_drift = max(max_sampled_mass_drift, float(abs(mass - 1).max()))
            samples += 1
            budget.check()
    final_mass = active.sum(axis=(1, 2)) + hit + escape + killed
    max_sampled_mass_drift = max(max_sampled_mass_drift, float(abs(final_mass - 1).max()))
    # The FP64 gamma tail may underflow for the finite controls. Preserve a
    # nonzero symbolic Chernoff bound in log space and high-precision decimal.
    # This bounds IDEAL series truncation, never floating point roundoff.
    with mp.workdps(80):
        exact_lam = mp.mpf(nu)*mp.mpf(horizon)
        threshold = mp.mpf(cutoff+1)
        log_tail = (mp.log(mp.mpf(horizon)/mp.mpf(phase_width))-exact_lam
                    + threshold*(1+mp.log(exact_lam/threshold)))
        tail = mp.nstr(mp.exp(log_tail)*(1+mp.mpf("1e-30")),80)
        log_tail = mp.nstr(log_tail,80)
    coefficient_expected = np.array((
        min(horizon, phase_width) / phase_width,
        -math.expm1(-discount * min(horizon, phase_width)) / (discount * phase_width)))
    return {
        "M": float(total[0]), "H_phase": float(total[1]),
        "poisson_truncation_bound_M_and_H": tail,
        "chernoff_log_expression": log_tail,
        "gamma_tail_fp64_diagnostic": float(gammainc(cutoff+1,lam)),
        "roundoff_certified": False,
        "sampled_power_mass_drift": max_sampled_mass_drift,
        "mass_sample_count": samples + 1, "mass_sample_stride": 512,
        "coefficient_sums": [float(coefficients_m.sum()), float(coefficients_h.sum())],
        "coefficient_sum_expected": coefficient_expected.tolist(),
        "final_power_active": active, "final_power_hit": hit,
        "final_power_escape": escape, "final_power_killed": killed,
        "final_power_exponent": cutoff, "nu": nu,
        "terms": cutoff + 1, "cycles": cycles, "active_horizon": horizon,
        "cpu_seconds": time.process_time() - cpu, "wall_seconds": time.perf_counter() - started,
        "state_semantics": "P^K auxiliary distributions, NOT spatial state at query time",
    }
