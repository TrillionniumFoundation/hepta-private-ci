"""Finite-hidden-prior H=1 information diagnostics, never an online oracle.

Utilities have axes [private target, independent future replica, feasible action].
Every target must share the same complete public history. The caller must justify
the prior, utility bounds, independent future replicas, and any deterministic
actions from its registered generator law; arrays alone cannot establish them.

All targets are integrated exactly under the declared finite prior. Thus only the
future-replica axis enters Monte Carlo intervals. The empirical information lattice
uses realized action tables and is not a population-optimality certificate.
"""

import hashlib
import math
import re

import numpy as np


def _validated(values, probabilities, gamma, utility_bounds):
    if np.ma.isMaskedArray(values) and np.any(np.ma.getmaskarray(values)):
        raise ValueError("Missing utilities cannot be dropped")
    values = np.asarray(values, dtype=np.float64)
    weights = np.asarray(probabilities, dtype=np.float64)
    gamma = float(gamma)
    bounds = tuple(float(x) for x in utility_bounds)
    if values.ndim != 3 or min(values.shape) < 1 or not np.isfinite(values).all():
        raise ValueError("Utilities must be finite nonempty [target,replica,action]")
    if weights.shape != (len(values),) or not np.isfinite(weights).all() or (weights <= 0).any() or not math.isclose(float(weights.sum()), 1.0, rel_tol=0, abs_tol=1e-12):
        raise ValueError("A positive normalized finite target prior is required")
    if not math.isfinite(gamma) or gamma < 0 or len(bounds) != 2 or not all(math.isfinite(x) for x in bounds) or bounds[0] > bounds[1]:
        raise ValueError("Invalid gamma or declared utility bounds")
    if values.min() < bounds[0] - 1e-12 or values.max() > bounds[1] + 1e-12:
        raise ValueError("Observed utility violates its predeclared bounds")
    if gamma and gamma * max(abs(x) for x in bounds) > 600:
        raise ValueError("The supplied moment bounds exceed supported float64 range")
    target = -values if gamma == 0 else np.exp(-gamma * values)
    return values, weights, gamma, bounds, target


def select_public_action(fit_utilities, probabilities, *, gamma, utility_bounds):
    """Choose a single action using fit replicas only; ties follow action order."""
    _, weights, _, _, targets = _validated(fit_utilities, probabilities, gamma, utility_bounds)
    return int(np.argmin(np.einsum("k,kra->a", weights, targets) / targets.shape[1]))


def _ce(objective, gamma):
    values = np.asarray(objective, dtype=np.float64)
    return -values if gamma == 0 else -np.log(values) / gamma


def information_lattice(utilities, probabilities, *, gamma, utility_bounds):
    """Exact lattice on this finite empirical potential-outcome table only.

    T reveals the private target. F reveals the complete future potential-outcome
    table before selecting an action. Neither is admissible online information.
    """
    _, weights, gamma, _, target = _validated(utilities, probabilities, gamma, utility_bounds)
    by_target_action = target.mean(axis=1)
    by_replica_action = np.einsum("k,kra->ra", weights, target)
    objective = {
        "public_only": float(by_replica_action.mean(axis=0).min()),
        "private_target_known": float(weights @ by_target_action.min(axis=1)),
        "full_future_table_known": float(by_replica_action.min(axis=1).mean()),
        "target_and_future_known": float(np.einsum("k,kr->r", weights, target.min(axis=2)).mean()),
    }
    ce = {name: float(_ce(value, gamma)) for name, value in objective.items()}
    for middle in ("private_target_known", "full_future_table_known"):
        if ce[middle] < ce["public_only"] - 1e-10 or ce["target_and_future_known"] < ce[middle] - 1e-10:
            raise ArithmeticError("Finite empirical information ordering failed")
    return {"objective": objective, "CE": ce,
            "scope": "Same empirical finite table; sample minima can be optimistic for the population",
            "information_gain_is_not_uniquely_additive": True,
            "interaction": ce["target_and_future_known"] - ce["private_target_known"] - ce["full_future_table_known"] + ce["public_only"]}


def analyze_history(fit_utilities, evaluation_utilities, probabilities, *,
                    public_history_digests, action_names, selected_actions,
                    gamma, utility_bounds, alpha=0.05, family_history_count=1,
                    deterministic_actions=(), predicted_moments=None):
    """Evaluate previously frozen public actions and fixed-head predictions.

    Selections must be frozen before evaluation replicas are generated/scored.
    The function does not choose a deployed action using evaluation utilities.
    A declared deterministic action must have identical fit/eval utility for each
    target; claiming determinism from a constant sample alone is not sufficient.
    """
    fit, weights, gamma, bounds, fit_target = _validated(fit_utilities, probabilities, gamma, utility_bounds)
    evaluation, _, _, _, target = _validated(evaluation_utilities, weights, gamma, bounds)
    if evaluation.shape[0] != fit.shape[0] or evaluation.shape[2] != fit.shape[2]:
        raise ValueError("Fit/evaluation targets and actions must have the same census")
    digests, names = tuple(public_history_digests), tuple(action_names)
    if len(digests) != len(weights) or len(set(digests)) != 1 or not re.fullmatch(r"[0-9a-f]{64}", digests[0]):
        raise ValueError("Every private target must share one complete public history digest")
    if len(names) != target.shape[2] or len(set(names)) != len(names) or any(not isinstance(x, str) or not x for x in names):
        raise ValueError("Unique action names must match the complete action axis")
    if not selected_actions or any(type(a) is not int or not 0 <= a < len(names) for a in selected_actions.values()):
        raise ValueError("Frozen policies must select an action in the declared census")
    if not 0 < alpha < 1 or type(family_history_count) is not int or family_history_count < 1:
        raise ValueError("Invalid simultaneous confidence family")
    deterministic = tuple(deterministic_actions)
    if len(set(deterministic)) != len(deterministic) or any(type(a) is not int or not 0 <= a < len(names) for a in deterministic):
        raise ValueError("Invalid deterministic action indices")
    per_replica = np.einsum("k,kra->ra", weights, target)
    means = per_replica.mean(axis=0)
    lower_bound, upper_bound = ((-bounds[1], -bounds[0]) if gamma == 0
                                else (math.exp(-gamma * bounds[1]), math.exp(-gamma * bounds[0])))
    radius = np.full(len(names), (upper_bound - lower_bound) * math.sqrt(
        math.log(2 * len(names) * family_history_count / alpha) / (2 * len(per_replica))))
    for a in deterministic:
        if not (np.array_equal(fit[:, :, a], np.repeat(fit[:, :1, a], fit.shape[1], axis=1))
                and np.array_equal(evaluation[:, :, a], np.repeat(fit[:, :1, a], evaluation.shape[1], axis=1))):
            raise ValueError("Declared deterministic action changed across replicas or phases")
        radius[a] = 0.0
    lower = np.maximum(means - radius, lower_bound)
    upper = np.minimum(means + radius, upper_bound)
    ce_point = _ce(means, gamma)
    ce_lower, ce_upper = _ce(upper, gamma), _ce(lower, gamma)
    policies = {}
    for name, action in selected_actions.items():
        policies[name] = {"action_index": action, "action": names[action],
                          "evaluation_CE": float(ce_point[action]),
                          "simultaneous_CE_interval": [float(ce_lower[action]), float(ce_upper[action])],
                          "finite_history_regret_interval": [float(max(0, ce_lower.max() - ce_upper[action])),
                                                             float(max(0, ce_upper.max() - ce_lower[action]))]}
    predictions = {}
    for name, supplied in (predicted_moments or {}).items():
        predicted = np.asarray(supplied, dtype=np.float64)
        if predicted.shape != means.shape or not np.isfinite(predicted).all() or (gamma > 0 and (predicted <= 0).any()):
            raise ValueError("Critic predictions must be finite action objectives in the same profile")
        difference = predicted - means
        predictions[name] = {"predicted_objective": predicted.tolist(),
            "conditional_mean_target_MSE_estimate": float(np.mean(difference**2)),
            "maximum_absolute_mean_target_error_estimate": float(np.max(np.abs(difference))),
            "maximum_absolute_mean_target_error_simultaneous_upper_bound": float(np.maximum(np.abs(predicted-lower), np.abs(predicted-upper)).max()),
            "CE_action_error_MSE_estimate": float(np.mean((_ce(predicted, gamma)-ce_point)**2)),
            "global_or_all_neural_histories_certificate": False}
    payload = np.ascontiguousarray(evaluation, dtype="<f8").tobytes()
    return {"schema": "hepta.abc-next.common-history-diagnostic.v1", "gamma": gamma,
            "public_history_sha256": digests[0], "evaluation_utility_array_sha256": hashlib.sha256(payload).hexdigest(),
            "target_count": len(weights), "fit_future_replicas": fit.shape[1],
            "evaluation_future_replicas": evaluation.shape[1], "actions": list(names),
            "target_prior_is_fixed_finite_diagnostic_law": True,
            "targets_are_not_independent_confidence_samples": True,
            "future_replica_iid_is_caller_model_assumption": True,
            "alpha": alpha, "simultaneous_history_observer_family": family_history_count,
            "moment_interval_method": "two-sided bounded Hoeffding with union over actions and registered history/observer family",
            "moment_bounds": [lower_bound, upper_bound], "moment_radius": radius.tolist(),
            "fit_action_mean_objectives": (np.einsum("k,kra->a", weights, fit_target) / fit.shape[1]).tolist(),
            "evaluation_action_mean_objectives": means.tolist(),
            "evaluation_action_CE": ce_point.tolist(),
            "action_simultaneous_CE_intervals": np.stack((ce_lower, ce_upper), axis=1).tolist(),
            "causal_best_action_CE_interval": [float(ce_lower.max()), float(ce_upper.max())],
            "empirical_best_action_CE_is_population_optimum": False,
            "policies": policies, "critic_predictions": predictions,
            "empirical_information_lattice": information_lattice(evaluation, weights, gamma=gamma, utility_bounds=bounds),
            "H2_or_global_optimality_claim": False}
