"""Finite-law direct-p gradient audit; not a neural efficiency/identification claim.

p is an intervention with a fixed productive consequence, not an editable reward
rule. This one-step frozen target isolates critic semantics from recursive target
error. Training draws, exact-law oracle training, and held-out references are
accounted separately. The Z=epsilon*P diagnostic is an imposed sensitivity
identity, not a claim that this discrete simulator is a continuous-time FBSDE.
"""

import argparse
import hashlib
import json
from pathlib import Path
import time

import numpy as np
from numpy.polynomial.chebyshev import chebder, chebval, chebvander
import scipy
from scipy.optimize import minimize


ETA = 1.3
EPSILONS = (1.0, 1e-2, 1e-4, 1e-6, 0.0)
PROBABILITY = np.array([0.175, 0.325, 0.175, 0.325])
XI = np.array([-1.0, -1.0, 1.0, 1.0])
U = np.array([-1.0, 1.0, -1.0, 1.0])
SEEDS = {"train_states": 202611051, "train_outcomes": 202611052, "heldout_states": 202611053}


def _clock():
    return time.perf_counter(), time.process_time()


def _elapsed(start):
    return {"wall_seconds": time.perf_counter() - start[0],
            "process_cpu_seconds": time.process_time() - start[1]}


def outcomes(p, epsilon):
    """Return four joint outcomes and exact dR/dp; on-domain R is in [-3, 2]."""
    p = np.asarray(p, dtype=float)
    if (p.ndim != 1 or not len(p) or not np.isfinite(p).all() or np.any(np.abs(p) > 1)
            or isinstance(epsilon, bool) or not np.isfinite(epsilon) or not 0 <= epsilon <= 1):
        raise ValueError("Require nonempty p in [-1,1] and epsilon in [0,1]")
    x = p[:, None] + epsilon * XI
    reward = 1 - 0.45 * (x - 0.35) ** 2 + 0.3 * U * x - 0.05 * p[:, None] ** 2
    gradient = -0.9 * (x - 0.35) + 0.3 * U - 0.1 * p[:, None]
    return reward, gradient


def exact_value_gradient(p, epsilon):
    """Enumerate the complete conditional law; no gradient fitted from Z/epsilon."""
    reward, derivative = outcomes(p, epsilon)
    log_terms = -ETA * reward + np.log(PROBABILITY)
    peak = log_terms.max(axis=1, keepdims=True)
    weights = np.exp(log_terms - peak)
    total = weights.sum(axis=1, keepdims=True)
    value = -(peak[:, 0] + np.log(total[:, 0])) / ETA
    gradient = np.sum(weights * derivative, axis=1) / total[:, 0]
    return value, gradient


def fit_log_moment(p, y, *, degree=4, objective="proper"):
    """Fit v=log E[Y|p] with exp(v)-Y*v, or its declared log-sample control.

    The log-sample control minimizes squared error to log(Y), whose target is
    E[log Y|p]. It is deliberately not labelled a conditional log-moment fit.
    No clipping or regularization changes either loss. Actual solver status and
    work are returned; a failed fit cannot silently become successful evidence.
    """
    start = _clock()
    p, y = np.asarray(p, dtype=float), np.asarray(y, dtype=float)
    if (p.ndim != 1 or y.shape != p.shape or not len(p) or not np.isfinite(p).all()
            or not np.isfinite(y).all() or np.any(np.abs(p) > 1) or np.any(y <= 0)
            or not isinstance(degree, int) or isinstance(degree, bool) or not 0 <= degree <= 10
            or objective not in {"proper", "log_sample"}):
        raise ValueError("Invalid polynomial fit data or objective")
    design = chebvander(p, degree)
    if np.linalg.matrix_rank(design) != degree + 1:
        raise ValueError("Polynomial training design lacks support")
    if objective == "log_sample":
        coefficient = np.linalg.lstsq(design, np.log(y), rcond=None)[0]
        return {"coefficient": coefficient.tolist(), "objective": objective, "degree": degree,
                "success": True, "solver": "numpy.linalg.lstsq", "iterations": 1,
                "objective_calls": 0, "least_squares_solves": 1, "training_rows": len(p), "cost": _elapsed(start)}
    calls = 0

    def loss(beta):
        nonlocal calls
        calls += 1
        v = design @ beta
        predicted_moment = np.exp(v)
        return (float(np.mean(predicted_moment - y * v)),
                design.T @ (predicted_moment - y) / len(p))

    initial = np.zeros(degree + 1)
    initial[0] = np.log(np.mean(y))
    result = minimize(loss, initial, jac=True, method="BFGS",
                      options={"gtol": 1e-8, "maxiter": 250})
    return {"coefficient": result.x.tolist(), "objective": objective, "degree": degree,
            "success": bool(result.success), "solver": "scipy.optimize.BFGS",
            "solver_message": str(result.message), "iterations": int(result.nit),
            "objective_calls": calls, "least_squares_solves": 0, "gradient_max_abs": float(np.max(np.abs(result.jac))),
            "training_rows": len(p), "final_loss": float(result.fun), "cost": _elapsed(start)}


def predict(fit, p):
    coefficient = np.asarray(fit["coefficient"])
    return -chebval(p, coefficient) / ETA, -chebval(p, chebder(coefficient)) / ETA


def error_metrics(value, gradient, truth, exact_gradient, intervention_gradient):
    return {"value_rmse": float(np.sqrt(np.mean((value - truth) ** 2))),
            "value_max_abs": float(np.max(np.abs(value - truth))),
            "gradient_rmse": float(np.sqrt(np.mean((gradient - exact_gradient) ** 2))),
            "gradient_max_abs": float(np.max(np.abs(gradient - exact_gradient))),
            "intervention_gradient_rmse": float(np.sqrt(np.mean((gradient - intervention_gradient) ** 2)))}


def oscillatory_actor_counterexample():
    """An explicit small value perturbation induces an actually harmful step."""
    start = _clock()
    p0, amplitude, frequency, step = 0.55, 1e-3, 2000.0, 5e-4
    before, derivative = exact_value_gradient([p0], 0.0)
    wrong_gradient = float(derivative[0]) + amplitude * frequency
    candidate = p0 + step * np.sign(wrong_gradient)
    after, _ = exact_value_gradient([candidate], 0.0)
    true_gain = float(after[0] - before[0])
    critic_gain = true_gain + amplitude * np.sin(frequency * (candidate - p0))
    return {"p_before": p0, "p_proposed": float(candidate), "step_size": step,
            "uniform_value_error_bound": amplitude, "gradient_error_at_prefix": amplitude * frequency,
            "true_gradient": float(derivative[0]), "critic_gradient": wrong_gradient,
            "critic_predicted_gain": float(critic_gain), "independent_exact_gain": true_gain,
            "disposition": "adopt" if true_gain > 0 else "no-update",
            "reference_outcome_evaluations": 8, "cost": _elapsed(start),
            "scope": "Constructed critic corruption; exact finite-law evaluator, no statistical CI or neural claim"}


def run_study(*, train_contexts=128, draws_per_context=64, heldout_contexts=256):
    if min(train_contexts, draws_per_context, heldout_contexts) < 1:
        raise ValueError("All declared observation counts must be positive")
    run_start = _clock()
    p = np.random.default_rng(SEEDS["train_states"]).uniform(-1, 1, train_contexts)
    indices = np.random.default_rng(SEEDS["train_outcomes"]).choice(
        4, size=(train_contexts, draws_per_context), p=PROBABILITY)
    heldout = np.random.default_rng(SEEDS["heldout_states"]).uniform(-0.95, 0.95, heldout_contexts)
    rows = []
    for epsilon in EPSILONS:
        sample_start = _clock()
        reward, _ = outcomes(p, epsilon)
        samples = reward[np.arange(train_contexts)[:, None], indices]
        sampled_y = np.exp(-ETA * samples).reshape(-1)
        exact_moment = np.exp(-ETA * reward) @ PROBABILITY
        sampling_cost = _elapsed(sample_start)
        # Shared sampled training work is charged once, not once per fit.
        fitted = {
            "proper_moment_poly4": fit_log_moment(np.repeat(p, draws_per_context), sampled_y),
            "log_sample_poly4": fit_log_moment(np.repeat(p, draws_per_context), sampled_y, objective="log_sample"),
            "exact_moment_poly4": fit_log_moment(p, exact_moment),
        }
        evaluation_start = _clock()
        value, derivative = exact_value_gradient(heldout, epsilon)
        delta = 1e-3
        high, _ = exact_value_gradient(heldout + delta, epsilon)
        low, _ = exact_value_gradient(heldout - delta, epsilon)
        intervention = (high - low) / (2 * delta)
        metrics = {name: error_metrics(*predict(fit, heldout), value, derivative, intervention)
                   for name, fit in fitted.items()}
        probe = 0.55
        _, direct = exact_value_gradient([probe], epsilon)
        _, fitted_direct = predict(fitted["proper_moment_poly4"], [probe])
        z_true, z_error = epsilon * float(direct[0]), 1e-5
        inverse = (z_true + z_error) / epsilon if epsilon else None
        rows.append({"epsilon": epsilon, "fits": fitted, "heldout": metrics,
                     "analytic_gradient_vs_actual_intervention_max_abs": float(np.max(np.abs(derivative - intervention))),
                     "sample_generation_cost": sampling_cost, "evaluation_cost": _elapsed(evaluation_start),
                     "counts": {"sampled_training_draws": train_contexts * draws_per_context,
                                "exact_training_support_outcomes": 4 * train_contexts,
                                "heldout_support_outcomes": 4 * heldout_contexts,
                                "intervention_support_outcomes": 8 * heldout_contexts,
                                "probe_support_outcomes": 4, "prediction_calls": 4,
                                "prediction_contexts": 3 * heldout_contexts + 1},
                     "degenerate_noise_diagnostic": {
                         "probe_p": probe, "direct_exact_gradient": float(direct[0]),
                         "direct_fitted_gradient": float(fitted_direct[0]),
                         "direct_fit_error": float(abs(fitted_direct[0] - direct[0])),
                         "z_true": z_true, "injected_absolute_z_error": z_error,
                         "recovered_gradient_from_noisy_z": inverse,
                         "inverse_error": abs(inverse - float(direct[0])) if epsilon else None,
                         "status": "ill-conditioned division" if epsilon else "unidentifiable from Z=0"}})
    counterexample = oscillatory_actor_counterexample()
    all_fits_ok = all(fit["success"] for row in rows for fit in row["fits"].values())
    return {"schema": "hepta.ndu-jac.frozen-target-critic-audit.v1", "eta": ETA,
            "return_formula": "1 - .45*(p + epsilon*xi - .35)^2 + .3*u*(p + epsilon*xi) - .05*p^2",
            "p_domain": [-1, 1], "return_bounds": [-3, 2], "outcome_probability": PROBABILITY.tolist(),
            "noise_xi": XI.tolist(), "environment_u": U.tolist(), "data_seeds": SEEDS,
            "train_contexts": train_contexts, "draws_per_context": draws_per_context,
            "heldout_contexts": heldout_contexts, "all_optimizer_status_success": all_fits_ok,
            "models_fixed_before_execution": ["proper_moment_poly4", "log_sample_poly4", "exact_moment_poly4"],
            "split": "Independent heldout p; four-outcome truth never used to choose model, degree, seed or hyperparameter",
            "oracle_baseline_scope": "Exact conditional moment at training p, known probabilities; not equal-information sampled learning",
            "cost_scope": "Single local process; sampling, all fits and exact evaluations; imports, dependency setup and publication excluded",
            "reuse": "Training samples and heldout references reused across fixed methods; repeated states/noise IDs paired across epsilon",
            "sampling_implementation": "Sampled IDs index a fully enumerated training payoff table; table computed once; no paid environment-reset claim",
            "registration": "Exploratory fixed local design; not externally preregistered",
            "source_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            "numpy_version": np.__version__, "scipy_version": scipy.__version__,
            "rows": rows, "oscillatory_critic": counterexample,
            "aggregate_counts": {"sampled_training_draws": len(EPSILONS) * train_contexts * draws_per_context,
                                 "exact_training_support_outcomes": len(EPSILONS) * 4 * train_contexts,
                                 "heldout_and_intervention_support_outcomes": len(EPSILONS) * 12 * heldout_contexts,
                                 "probe_and_actor_support_outcomes": len(EPSILONS) * 4 + 8,
                                 "fits": sum(len(row["fits"]) for row in rows),
                                 "prediction_calls": len(EPSILONS) * 4,
                                 "prediction_contexts": len(EPSILONS) * (3 * heldout_contexts + 1),
                                 "least_squares_solves": sum(fit["least_squares_solves"] for row in rows for fit in row["fits"].values()),
                                 "objective_calls": sum(fit["objective_calls"] for row in rows for fit in row["fits"].values())},
            "total_cost": _elapsed(run_start),
            "claims": {"finite_known_model_diagnostic_only": True, "neural_advantage": False,
                       "matched_information_efficiency": False, "general_zero_noise_theorem": False,
                       "recursive_target_unbiasedness": False, "production_qualification": False}}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = run_study()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, sort_keys=True, indent=2, allow_nan=False) + "\n")
    print(json.dumps({"output": str(args.output), "all_optimizer_status_success": result["all_optimizer_status_success"],
                      "cost": result["total_cost"]}, sort_keys=True))
    raise SystemExit(0 if result["all_optimizer_status_success"] else 1)
