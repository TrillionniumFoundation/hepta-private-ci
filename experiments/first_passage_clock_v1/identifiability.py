"""Deterministic local Fisher diagnostics; not an independent numerical oracle.

Uses the candidate event kernel, positive density-weighted score outer products,
and explicit no-hit probability masses. No training or holdout data are sampled.
"""

import argparse
import hashlib
import json
import math
from pathlib import Path
import platform
import subprocess

import numpy as np
import scipy
from scipy.integrate import quad_vec

from .kernels import Params, discounted_hit_derivatives, log_discounted_hit, log_event_likelihood


HERE = Path(__file__).resolve().parent


def log_scores(time, distance, params):
    """Scores in log(mu), log(sigma), log(lambda); positive mu/lambda required."""
    residual = distance - params.mu * time
    return np.array([params.mu * residual / params.sigma**2,
                     -1 + residual**2 / (params.sigma**2 * time),
                     -params.cancel_rate * time])


def spectrum(matrix, relative_tolerance=1e-9):
    matrix = (matrix + matrix.T) / 2
    eigenvalues = np.linalg.eigvalsh(matrix)
    threshold = relative_tolerance * max(float(eigenvalues[-1]), 1e-30)
    positive = eigenvalues[eigenvalues > threshold]
    return {"matrix": matrix.tolist(), "eigenvalues_ascending": eigenvalues.tolist(),
            "relative_rank_tolerance": relative_tolerance,
            "rank": int(len(positive)),
            "positive_subspace_condition_number": float(positive[-1] / positive[0]) if len(positive) else None,
            "smallest_eigenvalue": float(eigenvalues[0])}


def horizon_information(distance, horizon, params):
    hit_probability = math.exp(log_discounted_hit(distance, horizon, params.mu, params.sigma, params.cancel_rate))
    no_hit_probability = 1 - hit_probability
    physical = np.array([params.mu, params.sigma, params.cancel_rate])
    derivative = physical * discounted_hit_derivatives(distance, horizon, params)
    conditional_center = derivative / hit_probability

    # Keep the full four-dimensional score matrix separately; no finite-difference
    # Hessian is used, so the integrand is positive semidefinite by construction.
    def full_integrand(time):
        if time <= 0:
            return np.zeros(39)
        log_density = log_event_likelihood("hit", time, distance, params)
        if log_density < -740:
            return np.zeros(39)
        density = math.exp(log_density)
        score = log_scores(time, distance, params)
        centered = score - conditional_center
        residual = distance - params.mu * time
        score4 = np.r_[1 - distance * residual / (params.sigma**2 * time), score]
        return density * np.r_[1.0, score, np.outer(score, score).ravel(),
                               np.outer(centered, centered).ravel() / hit_probability,
                               score4[0], np.outer(score4, score4).ravel()]

    integral, error = quad_vec(full_integrand, 0, horizon, epsabs=2e-12, epsrel=2e-11)
    event_information = integral[4:13].reshape(3, 3)
    conditional_information = integral[13:22].reshape(3, 3)
    event_derivative = integral[1:4]
    full_information = event_information + np.outer(derivative, derivative) / no_hit_probability
    indicator_information = np.outer(derivative, derivative) / (hit_probability * no_hit_probability)
    derivative4 = np.r_[integral[22], derivative]
    unknown_scale_information = integral[23:39].reshape(4, 4) + np.outer(derivative4, derivative4) / no_hit_probability
    decomposition = full_information - indicator_information - hit_probability * conditional_information
    return {"horizon": horizon, "hit_probability": hit_probability,
            "full": full_information, "binary_indicator": indicator_information,
            "conditional_hit": conditional_information, "unknown_voltage_scale": unknown_scale_information,
            "integration_error_estimate": float(error),
            "mass_residual": float(abs(integral[0] - hit_probability)),
            "score_integral_residual": float(np.max(np.abs(event_derivative - derivative))),
            "fisher_chain_rule_residual": float(np.max(np.abs(decomposition)))}


def diagnose(distance=1.0, params=Params(0.8, 0.6, 0.35), horizons=(0.25, 0.6, 1.2, 2.4)):
    if distance <= 0 or params.mu <= 0 or params.sigma <= 0 or params.cancel_rate <= 0:
        raise ValueError("This log-coordinate diagnostic requires strictly positive parameters and distance.")
    if not horizons or any(horizon <= 0 for horizon in horizons):
        raise ValueError("Positive observed horizons required.")
    rows = [horizon_information(distance, horizon, params) for horizon in horizons]
    full = np.mean([row["full"] for row in rows], axis=0)
    binary = np.mean([row["binary_indicator"] for row in rows], axis=0)
    conditional = np.mean([row["conditional_hit"] for row in rows], axis=0)
    conditional_retained = sum(row["hit_probability"] * row["conditional_hit"] for row in rows) / sum(row["hit_probability"] for row in rows)
    retained_weights = np.array([row["hit_probability"] for row in rows])
    retained_weights /= retained_weights.sum()
    parameters = np.array([params.mu, params.sigma, params.cancel_rate])
    horizon_scores = np.array([parameters * discounted_hit_derivatives(distance, row["horizon"], params)
                               / row["hit_probability"] for row in rows])
    mean_horizon_score = retained_weights @ horizon_scores
    centered_horizon = horizon_scores - mean_horizon_score
    horizon_label_information = sum(weight * np.outer(score, score)
                                    for weight, score in zip(retained_weights, centered_horizon))
    conditional_joint = conditional_retained + horizon_label_information
    unknown_scale = np.mean([row["unknown_voltage_scale"] for row in rows], axis=0)
    kappa = math.sqrt(params.mu**2 + 2 * params.cancel_rate * params.sigma**2)
    beta = (kappa - params.mu) / params.sigma**2
    eventual_probability = math.exp(-distance * beta)
    log_eventual_score = np.array([params.mu * distance * beta / kappa,
                                   params.sigma**2 * distance * beta**2 / kappa,
                                   -params.cancel_rate * distance / kappa])
    eventual = eventual_probability / (1 - eventual_probability) * np.outer(log_eventual_score, log_eventual_score)
    null_conditional = np.array([params.cancel_rate * params.sigma**2, 0.0, -params.mu**2])
    null_conditional /= np.linalg.norm(null_conditional)
    null_scale = np.array([1.0, 1.0, 1.0, 0.0]) / math.sqrt(3)
    report = {
        "schema": "hepta.fpt.clock-identifiability.diagnostic.v1",
        "scope": "Deterministic local information diagnostic using candidate kernels; not an independent oracle, finite-sample convergence proof, or neural-network advantage result.",
        "coordinate_order": ["log_mu", "log_sigma", "log_cancel_rate"],
        "distance": distance, "params": {"mu": params.mu, "sigma": params.sigma, "cancel_rate": params.cancel_rate},
        "horizons": list(horizons), "horizon_design_weights": [1 / len(horizons)] * len(horizons),
        "full_event_time_plus_no_hit_per_attempt": spectrum(full),
        "finite_horizon_hit_indicator_per_attempt": spectrum(binary),
        "conditional_hit_time_equal_horizons_per_hit": spectrum(conditional),
        "conditional_hit_time_given_horizon_retained_weights_per_hit": spectrum(conditional_retained),
        "conditional_hit_joint_horizon_and_time_per_hit": spectrum(conditional_joint),
        "eventual_hit_indicator_per_attempt": spectrum(eventual),
        "unknown_voltage_scale_full_per_attempt": {"coordinate_order": ["log_distance", "log_mu", "log_sigma", "log_cancel_rate"], **spectrum(unknown_scale)},
        "conditional_null_direction": null_conditional.tolist(),
        "conditional_null_residual": float(np.linalg.norm(conditional @ null_conditional)),
        "unknown_scale_null_direction": null_scale.tolist(),
        "unknown_scale_null_residual": float(np.linalg.norm(unknown_scale @ null_scale)),
        "eventual_hit_probability": eventual_probability,
        "local_asymptotic_log_parameter_se_for_256_independent_attempts": np.sqrt(np.diag(np.linalg.inv(full)) / 256).tolist(),
        "per_horizon": [{key: spectrum(value) if isinstance(value, np.ndarray) else value for key, value in row.items()} for row in rows],
        "runtime": {"python": platform.python_version(), "numpy": np.__version__, "scipy": scipy.__version__},
        "source_sha256": {name: hashlib.sha256((HERE / name).read_bytes()).hexdigest() for name in ["identifiability.py", "kernels.py"]},
        "holdout_accessed": False,
    }
    if spectrum(full)["rank"] != 3 or spectrum(conditional)["rank"] != 2:
        raise ArithmeticError("The preregistered rank diagnostic did not match the structural claim")
    if max(row["fisher_chain_rule_residual"] for row in rows) > 1e-8:
        raise ArithmeticError("Fisher decomposition failed numerical consistency")
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=HERE / "IDENTIFIABILITY.json")
    args = parser.parse_args()
    result = diagnose()
    git = subprocess.run(["git", "rev-parse", "HEAD"], cwd=HERE, capture_output=True, text=True, check=False)
    result["repository_head_at_run"] = git.stdout.strip() if git.returncode == 0 else None
    args.output.write_text(json.dumps(result, indent=2, allow_nan=False) + "\n")
    print(json.dumps({"output": str(args.output), "full_eigenvalues": result["full_event_time_plus_no_hit_per_attempt"]["eigenvalues_ascending"],
                      "conditional_eigenvalues": result["conditional_hit_time_equal_horizons_per_hit"]["eigenvalues_ascending"],
                      "finite_horizon_binary_eigenvalues": result["finite_horizon_hit_indicator_per_attempt"]["eigenvalues_ascending"],
                      "max_mass_residual": max(row["mass_residual"] for row in result["per_horizon"])}))


if __name__ == "__main__":
    main()
