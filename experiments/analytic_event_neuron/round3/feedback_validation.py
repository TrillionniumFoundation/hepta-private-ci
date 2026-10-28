"""Independent numerical references for the new paid-feedback task."""

import math

import numpy as np
from scipy.integrate import quad

from .feedback import action_values, positive_square_expectation, posterior


def validate(seed=281028):
    rng = np.random.default_rng(seed)
    errors, posterior_errors = [], []
    for _ in range(160):
        mean, variance, cost = float(rng.uniform(-3, 3)), float(np.exp(rng.uniform(-5, 1))), float(np.exp(rng.uniform(-5, 1)))
        cutoff, sigma = math.sqrt(cost), math.sqrt(variance)
        lower, upper = (-cutoff - mean) / sigma, (cutoff - mean) / sigma
        integrand = lambda z: ((mean + sigma * z) ** 2 - cost) * math.exp(-z * z / 2) / math.sqrt(2 * math.pi)
        reference = quad(integrand, -np.inf, lower, epsabs=2e-11, epsrel=2e-11)[0]
        reference += quad(integrand, upper, np.inf, epsabs=2e-11, epsrel=2e-11)[0]
        errors.append(abs(positive_square_expectation(mean, variance, cost) - reference))
        n = int(rng.integers(1, 3))
        calibration = {"error_variance": float(np.exp(rng.uniform(-2, 1))), "noise_scale": float(np.exp(rng.uniform(-1, 1)))}
        public = {"residuals": rng.normal(size=n).tolist(), "variances": np.exp(rng.uniform(-4, 1, n)).tolist()}
        actual = posterior(calibration, public)
        alpha = calibration["error_variance"]
        covariance = np.full((n + 1, n + 1), alpha)
        covariance[1:, 1:] += np.diag(np.asarray(public["variances"]) * calibration["noise_scale"])
        mean_reference = covariance[0, 1:] @ np.linalg.solve(covariance[1:, 1:], public["residuals"])
        var_reference = covariance[0, 0] - covariance[0, 1:] @ np.linalg.solve(covariance[1:, 1:], covariance[1:, 0])
        posterior_errors.extend([abs(actual[0] - mean_reference), abs(actual[1] - var_reference)])
    deterministic = all(positive_square_expectation(m, 0, c) == max(m * m - c, 0)
                        for m in (-2, 0, 1) for c in (.1, 1, 4))
    symmetry = all(abs(positive_square_expectation(m, v, c) - positive_square_expectation(-m, v, c)) < 1e-14
                   for m in (.01, .5, 2) for v in (.01, 1) for c in (.1, 1))
    zero = action_values(0, .2, {"repair_cost": .12, "wait_variance": .04, "wait_cost": .01}, {"noise_scale": 1})
    checks = {"normal_second_tail_moment_matches_quadrature": bool(max(errors) < 1e-9),
              "posterior_matches_joint_gaussian_solve": bool(max(posterior_errors) < 2e-13),
              "zero_variance_branch": deterministic, "tail_symmetry": symmetry,
              "zero_mean_wait_can_have_value": zero["repair_gain"] < 0 < zero["wait_gain"]}
    rejected = 0
    for operation in (
        lambda: posterior({"error_variance": -1, "noise_scale": 1}, {"residuals": [0], "variances": [1]}),
        lambda: posterior({"error_variance": 1, "noise_scale": float("nan")}, {"residuals": [0], "variances": [1]}),
        lambda: positive_square_expectation(1e300, 1, 1),
        lambda: positive_square_expectation(1e300, 0, 1),
    ):
        try:
            operation()
        except ValueError:
            rejected += 1
    checks["invalid_model_and_overflow_rejected"] = rejected == 4
    if not all(checks.values()):
        raise AssertionError(checks)
    return {"passed": True, "checks": checks, "quadrature_cases": len(errors),
            "quadrature_max_absolute_error": float(max(errors)), "posterior_max_absolute_error": float(max(posterior_errors)),
            "quadrature_is_independent_of_tail_formula": True, "seed": seed}
