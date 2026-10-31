"""Independent arithmetic checks for the analytic terminal-event kernel.

Run: python -m experiments.analytic_event_neuron.reference [--output PATH]
Quadrature oracles integrate densities and do not call a normal CDF. A finite
partition's composition error is reported separately from the Gaussian law.
"""

import argparse
import hashlib
import json
import math
import platform
from pathlib import Path

import numpy as np
import scipy
from scipy.integrate import quad
from scipy.special import ndtr

from .analytic import (
    event_gradients, event_log_probs, event_probs, first_passage_upper,
    gaussian_transition, interval_transition_matrix, quantize_simplex,
    transition_event_gradients,
)


def _quad_events(mean, variance, lower, upper):
    scale = math.sqrt(variance)
    bounds = [-math.inf, (lower-mean)/scale, (upper-mean)/scale, math.inf]
    density = lambda x: math.exp(-0.5*x*x)/math.sqrt(2*math.pi)
    masses = []
    for lo, hi in zip(bounds[:-1], bounds[1:]):
        # Adaptive quadrature on (-inf, huge_positive) can entirely miss the
        # central peak. Explicit fixed splits make this a usable oracle.
        splits = [lo]+[x for x in (-8.0, -4.0, 0.0, 4.0, 8.0) if lo < x < hi]+[hi]
        masses.append(sum(quad(density, a, b, epsabs=2e-13, epsrel=2e-12)[0]
                          for a, b in zip(splits[:-1], splits[1:])))
    return np.array(masses)


def _tail_log_oracle(z):
    # Q(z)=phi(z)/(1+z) integral_0^inf exp(-z*y/(1+z)-y^2/(2*(1+z)^2))dy.
    scale = 1.0+z
    mass = quad(lambda y: math.exp(-z*y/scale-0.5*(y/scale)**2),
                0, math.inf, epsabs=1e-13, epsrel=1e-13)[0]
    return -0.5*z*z-0.5*math.log(2*math.pi)-math.log(scale)+math.log(mass)


def run_checks(seed=260627):
    """Return an auditable JSON-compatible result, raising only on code errors."""
    rng = np.random.default_rng(seed)
    checks = {}

    means = rng.uniform(-4, 4, 400)
    variances = np.exp(rng.uniform(-5, 2, 400))
    lower = rng.uniform(-2, 0, 400)
    upper = lower+rng.uniform(0.02, 4, 400)
    probabilities = event_probs(means, variances, lower, upper)
    normalization_error = float(np.max(np.abs(probabilities.sum(-1)-1)))
    checks["probability_partition"] = {
        "cases": len(means), "maximum_normalization_error": normalization_error,
        "minimum_probability": float(probabilities.min()),
        "pass": normalization_error <= 2e-14 and bool((probabilities >= 0).all()),
    }

    quad_error = max(float(np.max(np.abs(
        event_probs(m, v, lo, hi)-_quad_events(m, v, lo, hi)
    ))) for m, v, lo, hi in zip(means[:64], variances[:64], lower[:64], upper[:64]))
    checks["independent_density_quadrature"] = {
        "cases": 64, "maximum_absolute_error": quad_error, "pass": quad_error < 2e-11,
    }

    tail_errors = [abs(float(event_log_probs(0, 1, -1, z)[2])-_tail_log_oracle(z))
                   for z in (0, 1, 4, 8, 16, 32, 40)]
    narrow_errors = []
    for center in (-30.0, -8.0, -0.1, 0.0, 1.0, 8.0, 30.0):
        lo, hi = center-5e-10, center+5e-10
        width, midpoint = hi-lo, lo+(hi-lo)/2
        integral = quad(lambda s: math.exp(-midpoint*width*s-0.5*(width*s)**2),
                        -0.5, 0.5, epsabs=1e-13, epsrel=1e-13)[0]
        oracle = math.log(width)-0.5*midpoint**2-0.5*math.log(2*math.pi)+math.log(integral)
        narrow_errors.append(abs(float(event_log_probs(0, 1, lo, hi)[1])-oracle))
    checks["tail_and_narrow_interval_logs"] = {
        "tail_z": [0, 1, 4, 8, 16, 32, 40],
        "maximum_tail_log_error": float(max(tail_errors)),
        "maximum_narrow_log_error": float(max(narrow_errors)),
        "underflow_probability_keeps_finite_log": bool(
            event_probs(0, 1, -1, 40)[2] == 0
            and np.isfinite(event_log_probs(0, 1, -1, 40)[2])),
        "pass": max(tail_errors+narrow_errors) < 2e-11,
    }

    atom_states = np.array([-2, -1, 0, 1, 2])
    atom_expected = np.eye(3)[[0, 0, 1, 1, 2]]
    atom_actual = event_probs(atom_states, 0, -1, 1)
    pair = event_probs(np.linspace(-8, 8, 50), 0.25, 0.1, 0.1)
    checks["ties_and_binary_complement"] = {
        "atom_probabilities": atom_actual.tolist(),
        "binary_sum_error": float(np.max(abs(pair[:, 0]+pair[:, 2]-1))),
        "pass": bool(np.array_equal(atom_expected, atom_actual)
                     and np.all(pair[:, 1] == 0)
                     and np.max(abs(pair[:, 0]+pair[:, 2]-1)) < 2e-14),
    }

    derivative_errors = {"mean": 0.0, "variance": 0.0}
    for m, v in zip(rng.uniform(-2, 2, 80), rng.uniform(0.15, 2, 80)):
        gradients = event_gradients(m, v, -0.35, 0.8)
        step = 1e-5
        numerical = {
            "mean": (event_probs(m+step, v, -0.35, 0.8)-event_probs(m-step, v, -0.35, 0.8))/(2*step),
            "variance": (event_probs(m, v+step, -0.35, 0.8)-event_probs(m, v-step, -0.35, 0.8))/(2*step),
        }
        for key in derivative_errors:
            derivative_errors[key] = max(derivative_errors[key], float(np.max(abs(
                gradients[key]-numerical[key]))))
    params = dict(mean=0.3, variance=0.2, drift=-0.15, diffusion=0.6, dt=0.7)
    gradients = transition_event_gradients(**params, lower=-0.4, upper=0.9)
    chain_errors = {}
    for key in ("drift", "diffusion", "dt"):
        plus, minus = params.copy(), params.copy()
        plus[key] += 1e-5
        minus[key] -= 1e-5
        numerical = (event_probs(*gaussian_transition(**plus), -0.4, 0.9)
                     - event_probs(*gaussian_transition(**minus), -0.4, 0.9))/2e-5
        chain_errors[key] = float(np.max(abs(numerical-gradients[key])))
    checks["analytic_gradients"] = {
        "cases": 80, "central_difference_step": 1e-5,
        "maximum_errors": derivative_errors, "chain_rule_errors": chain_errors,
        "pass": max([*derivative_errors.values(), *chain_errors.values()]) < 2e-8,
    }

    # This compares the same canonical affine coefficients, not two optimizers.
    x = rng.normal(size=(91, 7))
    w, bias, threshold, drift, sigma, time = rng.normal(size=7), 0.2, 0.3, -0.08, 0.6, 0.7
    m = x@w+bias+drift*time
    digital = event_probs(m, sigma*sigma*time, threshold, threshold)[:, 2]
    probit = ndtr(x@(w/(sigma*math.sqrt(time)))+(bias-threshold+drift*time)/(sigma*math.sqrt(time)))
    equality_error = float(np.max(abs(digital-probit)))
    checks["probit_reparameterization_negative_control"] = {
        "maximum_forward_error": equality_error,
        "pass": equality_error < 2e-14,
        "scope": "Identical affine function; optimizer trajectories need separately matched geometry.",
    }

    x0, b, sigma, first, second, threshold = 0.31, 0.14, 0.55, 0.45, 0.65, 0.2
    direct = float(event_probs(x0+b*(first+second), sigma*sigma*(first+second),
                              threshold, threshold)[2])
    composed = quad(lambda z: float(event_probs(
        x0+b*first+sigma*math.sqrt(first)*z+b*second, sigma*sigma*second,
        threshold, threshold)[2])*math.exp(-z*z/2)/math.sqrt(2*math.pi),
        -math.inf, math.inf, epsabs=1e-12, epsrel=1e-12)[0]
    law_errors = []
    for _ in range(50):
        state = (float(rng.normal()), float(rng.uniform(0, 1)))
        a, c = rng.uniform(0, 3, 2)
        one = gaussian_transition(*state, b, sigma, a+c)
        two = gaussian_transition(*gaussian_transition(*state, b, sigma, a), b, sigma, c)
        law_errors.append(max(abs(float(one[0]-two[0])), abs(float(one[1]-two[1]))))
    projection_rows = []
    for spacing in (0.5, 0.25, 0.125):
        centers = np.arange(-10, 10+spacing/2, spacing)
        edges = np.r_[-np.inf, (centers[:-1]+centers[1:])/2, np.inf]
        first_row = interval_transition_matrix([x0], edges, b, sigma, first)[0]
        continuation = event_probs(centers+b*second, sigma*sigma*second, threshold, threshold)[:, 2]
        projection_rows.append({"spacing": spacing, "absolute_error": abs(float(first_row@continuation)-direct)})
    checks["time_consistency"] = {
        "continuous_quadrature_error": abs(direct-composed),
        "maximum_moment_composition_error": max(law_errors),
        "finite_partition_projection_errors": projection_rows,
        "finite_partition_claims_exact_semigroup": False,
        "pass": abs(direct-composed) < 2e-11 and max(law_errors) < 2e-14
            and projection_rows[-1]["absolute_error"] < projection_rows[0]["absolute_error"],
    }

    states = np.linspace(-3, 3, 31)
    edges = np.r_[-np.inf, (states[:-1]+states[1:])/2, np.inf]
    kernel = interval_transition_matrix(states, edges, 0.15, 0.4, 0.7)
    low = rng.normal(size=len(states))
    high = low+rng.uniform(0, 2, len(states))
    observed_gain = float(np.max(abs(kernel@high-kernel@low))/np.max(abs(high-low)))
    quantized = quantize_simplex(probabilities)
    quantization_error = float(np.max(abs(quantized/(1 << 24)-probabilities)))
    checks["positive_operator_and_q24"] = {
        "maximum_row_sum_error": float(np.max(abs(kernel.sum(1)-1))),
        "observed_sup_norm_gain": observed_gain,
        "maximum_q24_component_error": quantization_error,
        "pass": bool((kernel >= 0).all() and np.max(abs(kernel.sum(1)-1)) < 2e-14
                     and (kernel@high >= kernel@low-1e-14).all() and observed_gain <= 1+1e-14
                     and (quantized >= 0).all() and (quantized.sum(-1) == 1 << 24).all()
                     and quantization_error <= 1/(1 << 24)+2e-14),
    }

    endpoint = float(event_probs(0, 1, 1, 1)[2])
    hitting = float(first_passage_upper(0, 1, 0, 1, 1))
    checks["first_passage_is_a_separate_event"] = {
        "endpoint_probability": endpoint, "first_passage_probability": hitting,
        "pass": abs(hitting-2*endpoint) < 1e-14 and abs(hitting-endpoint) > 0.1,
    }

    invalid = [lambda: event_probs(0, -1, -1, 1), lambda: event_probs(np.nan, 1, -1, 1),
               lambda: event_probs(0, 1, 1, -1), lambda: event_gradients(0, 0, -1, 1),
               lambda: gaussian_transition(0, 1, 0, 1, -1),
               lambda: interval_transition_matrix([0], [-1, 1], 0, 1, 1),
               lambda: quantize_simplex([0.1, 0.1, 0.1])]
    rejected = 0
    for call in invalid:
        try:
            call()
        except ValueError:
            rejected += 1
    checks["invalid_domain_rejection"] = {"cases": len(invalid), "rejected": rejected,
                                           "pass": rejected == len(invalid)}
    source_paths = [Path(__file__), Path(__file__).with_name("analytic.py")]
    return {"schema": "hepta.analytic-event.math-validation.v1", "seed": seed,
            "python": platform.python_version(), "numpy": np.__version__, "scipy": scipy.__version__,
            "source_sha256": {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in source_paths},
            "checks": checks, "pass": all(value["pass"] for value in checks.values())}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = run_checks()
    rendered = json.dumps(result, indent=2, sort_keys=True, allow_nan=False)+"\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered)
    print(rendered, end="")
    return 0 if result["pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
