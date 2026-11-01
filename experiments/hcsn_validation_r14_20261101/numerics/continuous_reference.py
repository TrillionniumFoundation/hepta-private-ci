"""Continuous reference independent of the spatial generator and its solver."""

import numpy as np
from scipy.integrate import quad_vec

from experiments.hcsn_regeneration_content_20261031 import renewal
from experiments.hcsn_validation_r12_20261031.numerics.dynamics import hitting_density, killed_functionals


def successor(case, edges, count_cap, tail_atol=1e-12):
    x, mu, sigma, horizon, reset = (case[k] for k in ("x", "mu", "sigma", "horizon", "reset"))
    effective_x = reset if x == 0 else x
    active = killed_functionals(effective_x, mu, sigma, horizon, edges)[np.r_[0, np.arange(3, len(edges) + 2)]]
    errors, terms, omitted = [], 0, 0.0
    if horizon > 0:
        for n in range(1, 257):
            distance = effective_x + (n - 1) * reset
            increment, error = quad_vec(
                lambda s: hitting_density(s, distance, mu, sigma)
                * killed_functionals(reset, mu, sigma, horizon - s, edges)[np.r_[0, np.arange(3, len(edges) + 2)]],
                0, horizon, epsabs=2e-12, epsrel=2e-11)
            active += increment
            errors.append(float(error)); terms = n
            omitted = float(renewal.count_tail(n + 1, effective_x, mu, sigma, horizon, reset, 0))
            if omitted <= tail_atol:
                break
        else:
            raise ArithmeticError("Continuous successor branch cap did not meet its tail criterion")
    args = {**{k: case[k] for k in ("x", "mu", "sigma", "horizon", "reset")}, "refractory": 0.0}
    pmf = renewal.count_pmf(np.arange(count_cap + 1), **args).tolist()
    pmf.append(float(renewal.count_tail(count_cap + 1, **args)))
    return {"expected_count": float(renewal.expected_count(**args)),
            "first_hit": float(renewal.first_passage_cdf(x, mu, sigma, horizon)),
            "count_pmf_with_overflow": pmf, "active_mass": float(active[0]),
            "active_bins": active[1:].tolist(), "completed_reset_terms": terms,
            "omitted_probability_bound": omitted,
            "quadrature_error_estimate": sum(errors)}


def count_gradient(case, terms, precision):
    import mpmath as mp
    with mp.workdps(precision):
        values = [mp.mpf(str(case[k])) for k in ("x", "mu", "sigma", "horizon", "reset")]
        def count(*p):
            x, mu, sigma, horizon, reset = p
            scale = sigma * mp.sqrt(horizon)
            def cdf(z):
                return mp.erfc(-z / mp.sqrt(2)) / 2
            return mp.fsum(cdf(-(x + n * reset + mu * horizon) / scale)
                + mp.exp(-2 * mu * (x + n * reset) / sigma**2)
                * cdf((-x - n * reset + mu * horizon) / scale) for n in range(terms))
        gradient = []
        for i in range(5):
            order = tuple(int(j == i) for j in range(5))
            gradient.append(mp.diff(count, tuple(values), order))
        return {"expected_count": str(count(*values)), "gradient": [str(x) for x in gradient],
                "terms": terms, "precision_digits": precision}
