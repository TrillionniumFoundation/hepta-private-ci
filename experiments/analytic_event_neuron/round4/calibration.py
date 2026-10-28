"""Exact diffusion-mixture forecasts with bounded, public context evidence.

The latent component is fixed within one block of prior sensor histories and
its query. All horizons share the posterior component weights. A separate
moment-projection control deliberately discards the mixture shape.
"""
from copy import deepcopy
import time

import numpy as np
from scipy.optimize import minimize
from scipy.special import expit, logsumexp, ndtr

from .. import learners, statistics, task
from ..analytic import event_log_probs
from ..round2.adaptation import _validate_filter, public_log_likelihood
from ..round3.calibration import dense_log_likelihood, public_history

SCHEMA = "hepta.analytic-event.context-mixture.v4"
STRENGTHS = tuple(float(x) for x in np.linspace(0, 1, 21))
Q24 = 1 << 24


def make_model(anchor, adaptive, context_count=8, projection=False):
    for model in (anchor, adaptive):
        _validate_filter(model)
    return {"schema": SCHEMA, "kind": "context_mixture", "anchor": deepcopy(anchor),
            "adaptive": deepcopy(adaptive), "prior": .5, "context_count": int(context_count),
            "projection": bool(projection), "parameter_q24": False,
            "pointwise_retention_guarantee": False}


def component_cache(model, history, context=None, classical=False):
    """Return component moments and public evidence; targets are never read."""
    if model.get("schema") != SCHEMA or model.get("kind") != "context_mixture":
        raise ValueError("Unsupported conditional-law model")
    prior = float(model["prior"])
    count = model["context_count"]
    if not np.isfinite(prior) or not 0 <= prior <= 1 or count not in (0, 8):
        raise ValueError("Invalid prior or public context budget")
    history = public_history(history)
    n = len(history["obs"])
    if count:
        if context is None or len(context["obs"]) != n * count:
            raise ValueError("Each query requires exactly eight prior public histories")
        context = public_history(context)
    means, variances, likelihoods, context_likelihoods = [], [], [], []
    for key in ("anchor", "adaptive"):
        component = deepcopy(model[key])
        _validate_filter(component)
        if model["parameter_q24"]:
            values = np.rint(np.asarray(component["parameters"]) * Q24) / Q24
            if np.any(values[1:] <= 0):
                raise ValueError("Quantized dynamics must have positive noise")
            component["parameters"] = values.tolist()
        if classical:
            component["equivalent_classical_implementation"] = True
        mean, variance = learners.predict(component, history)
        likelihood = dense_log_likelihood if classical else public_log_likelihood
        means.append(mean)
        variances.append(variance)
        likelihoods.append(likelihood(component, history))
        context_likelihoods.append(likelihood(component, context).reshape(n, count).sum(1)
                                   if count else np.zeros(n))
    cache = {"means": np.stack(means, -1), "variances": np.stack(variances, -1),
             "query_log_likelihoods": np.stack(likelihoods, -1),
             "context_log_likelihoods": np.stack(context_likelihoods, -1)}
    if not all(np.isfinite(value).all() for value in cache.values()):
        raise ValueError("Conditional moments and public likelihoods must be finite")
    return cache


def distribution_from_cache(cache, prior, projection=False):
    prior = float(prior)
    if not 0 <= prior <= 1:
        raise ValueError("Mixture prior must lie in the unit interval")
    evidence = cache["query_log_likelihoods"] + cache["context_log_likelihoods"]
    if not np.isfinite(evidence).all():
        raise ValueError("Public log likelihoods must remain finite")
    if prior in (0., 1.):
        log_weights = np.tile([-np.inf, 0.] if prior == 1. else [0., -np.inf], (len(evidence), 1))
    else:
        logodds = np.log(prior) - np.log1p(-prior) + evidence[:, 1] - evidence[:, 0]
        if not np.isfinite(logodds).all():
            raise ValueError("Posterior log odds must remain finite")
        log_weights = np.stack((-np.logaddexp(0., logodds), -np.logaddexp(0., -logodds)), -1)
    weights = np.exp(log_weights)
    means, variances = cache["means"], cache["variances"]
    if projection:
        mean = np.sum(weights[:, None, :] * means, -1)
        variance = np.sum(weights[:, None, :] * (variances + (means - mean[..., None]) ** 2), -1)
        weights, means, variances = np.ones((len(mean), 1)), mean[..., None], variance[..., None]
        log_weights = np.zeros_like(weights)
    return {"weights": weights, "log_weights": log_weights, "means": means, "variances": variances}


def predict_distribution(model, history, context=None, classical=False):
    cache = component_cache(model, history, context, classical)
    prior = np.rint(model["prior"] * Q24) / Q24 if model["parameter_q24"] else model["prior"]
    return distribution_from_cache(cache, prior, model["projection"])


def law_at(distribution, row, horizon):
    weights = distribution["weights"][row]
    physical = np.isfinite(distribution["log_weights"][row])
    if np.any(physical & (weights == 0)):
        raise ValueError("A physical mixture weight is not representable in the positive-weight runtime schema")
    keep = physical
    return {"schema": "hepta.conditional-law.v4", "semantics": "terminal",
            "weights": distribution["weights"][row, keep].tolist(),
            "means": distribution["means"][row, horizon, keep].tolist(),
            "variances": distribution["variances"][row, horizon, keep].tolist()}


def _logweights(distribution):
    return distribution["log_weights"][:, None, :]


def mixture_log_density(distribution, targets):
    variance = distribution["variances"]
    logpdf = -.5 * (np.log(2 * np.pi * variance)
                   + (np.asarray(targets)[..., None] - distribution["means"]) ** 2 / variance)
    if not np.isfinite(logpdf).all():
        raise ValueError("Component log densities exceed the finite numeric domain")
    return logsumexp(_logweights(distribution) + logpdf, axis=-1)


def mixture_cdf(distribution, values):
    standardized = (np.asarray(values)[..., None] - distribution["means"]) / np.sqrt(distribution["variances"])
    return np.sum(distribution["weights"][:, None, :] * ndtr(standardized), -1)


def mixture_event_log_probs(distribution, lower=task.LOWER, upper=task.UPPER):
    logp = event_log_probs(distribution["means"], distribution["variances"], lower, upper)
    return logsumexp(_logweights(distribution)[..., None] + logp, axis=-2)


def mixture_event_probs(distribution, lower=task.LOWER, upper=task.UPPER):
    return np.exp(mixture_event_log_probs(distribution, lower, upper))


def mixture_quantiles(distribution, levels=(.025, .975)):
    """Monotone bisection brackets every component quantile (80 iterations)."""
    from scipy.special import ndtri
    means, sigma = distribution["means"], np.sqrt(distribution["variances"])
    values = []
    for level in levels:
        if not 0 < level < 1:
            raise ValueError("Quantile levels must be strictly interior")
        component = means + sigma * ndtri(level)
        lo, hi = component.min(-1), component.max(-1)
        for _ in range(80):
            mid = lo + (hi - lo) * .5
            below = mixture_cdf(distribution, mid) < level
            lo, hi = np.where(below, mid, lo), np.where(below, hi, mid)
        values.append(lo + (hi - lo) * .5)
    return np.stack(values, -1)


def prior_objective(raw, cache, targets, projection=False):
    """Composite exact-mixture NLL; analytic derivative of one prior logit."""
    prior = float(expit(np.asarray(raw)[0]))
    dist = distribution_from_cache(cache, prior)
    variance, means = dist["variances"], dist["means"]
    if projection:
        w = dist["weights"][:, 1, None]
        delta = means[..., 1] - means[..., 0]
        mean = means[..., 0] + w * delta
        var = (1 - w) * variance[..., 0] + w * variance[..., 1] + w * (1 - w) * delta ** 2
        error = mean - targets
        dw = w * (1 - w)
        derivative = (error / var * dw * delta
                      + .5 * (1 / var - error ** 2 / var ** 2) * dw
                      * (variance[..., 1] - variance[..., 0] + (1 - 2 * w) * delta ** 2))
        return float(.5 * (np.log(2 * np.pi * var) + error ** 2 / var).mean()), np.array([float(derivative.mean())])
    logpdf = -.5 * (np.log(2 * np.pi * variance) + (targets[..., None] - means) ** 2 / variance)
    joint = _logweights(dist) + logpdf
    logpdf_mix = logsumexp(joint, -1)
    responsibility = np.exp(joint[..., 1] - logpdf_mix)
    gradient = (dist["weights"][:, 1, None] - responsibility).mean()
    return float(-logpdf_mix.mean()), np.array([float(gradient)])


def fit_prior(model, pieces):
    """Each piece is a labelled training dataset and its public-only context."""
    if len(pieces) != 2 or any(data["split"] not in ("train", "retention_train") for data, _ in pieces):
        raise ValueError("Old and current training collections are required")
    caches = [component_cache(model, task.history(data), context) for data, context in pieces]
    cache = {key: np.concatenate([item[key] for item in caches]) for key in caches[0]}
    target = np.concatenate([task.targets(data) for data, _ in pieces])
    trace = []
    started, cpu = time.perf_counter_ns(), time.process_time_ns()

    def objective(raw):
        value, gradient = prior_objective(raw, cache, target, model["projection"])
        trace.append({"prior_logit": float(raw[0]), "nll": value, "gradient": float(gradient[0])})
        return value, gradient

    result = minimize(objective, np.zeros(1), jac=True, method="L-BFGS-B",
                      bounds=[(-6., 6.)], options={"maxiter": 120, "ftol": 1e-12, "gtol": 1e-8})
    fitted = deepcopy(model)
    fitted["prior"] = float(expit(result.x[0]))
    receipt = {"initial_prior": .5, "fitted_prior": fitted["prior"],
               "prior_logit_change": float(abs(result.x[0])), "objective_trace": trace,
               "optimizer_success": bool(result.success), "optimizer_message": str(result.message),
               "training_trajectories": sum(len(data["ids"]) for data, _ in pieces),
               "context_public_histories": sum(len(context["obs"]) for _, context in pieces),
               "dataset_digests": [task.dataset_digest(data) for data, _ in pieces],
               "training_wall_ns": time.perf_counter_ns() - started,
               "training_parent_cpu_ns": time.process_time_ns() - cpu}
    return fitted, receipt


def scores(distribution, data):
    target = task.targets(data)
    log_density = mixture_log_density(distribution, target)[:, 1:]
    logp = mixture_event_log_probs(distribution)[:, 1:]
    labels = task.event_labels(target[:, 1:])
    probabilities = np.exp(logp)
    quantiles = mixture_quantiles(distribution)[:, 1:]
    event_loss = -np.take_along_axis(logp, labels[..., None], -1)[..., 0]
    mean = np.sum(distribution["weights"][:, None, :] * distribution["means"], -1)[:, 1:]
    arrays = {"density_nll_by_horizon": -log_density, "density_nll": -log_density.mean(1),
              "event_nll": event_loss.mean(1), "probabilities": probabilities, "labels": labels,
              "coverage95": ((target[:, 1:] >= quantiles[..., 0])
                             & (target[:, 1:] <= quantiles[..., 1])).mean(1),
              "mean": mean, "quantiles95": quantiles, "targets": target[:, 1:],
              "mse": ((target[:, 1:] - mean) ** 2).mean(1)}
    summary = {key: float(arrays[key].mean()) for key in ("density_nll", "event_nll", "coverage95", "mse")}
    summary["classwise_ece"] = statistics.calibration(probabilities, labels)["classwise_ece"]
    return arrays, summary


def select_model(model, old_development, new_development, old_context, new_context):
    """Identical 21-choice old-guard/new-NLL selection for exact and projected heads."""
    if any(data["split"] != "calibration_development" for data in (old_development, new_development)):
        raise ValueError("Selection only accepts explicitly labelled development data")
    caches = [component_cache(model, task.history(data), context)
              for data, context in ((old_development, old_context), (new_development, new_context))]
    targets = [task.targets(data) for data in (old_development, new_development)]
    anchor_loss = -mixture_log_density(distribution_from_cache(caches[0], 0), targets[0])[:, 1:]
    candidates = []
    for strength in STRENGTHS:
        prior = strength * model["prior"]
        loss = [-mixture_log_density(distribution_from_cache(cache, prior, model["projection"]), target)[:, 1:]
                for cache, target in zip(caches, targets)]
        difference = (loss[0] - anchor_loss).mean(1)
        mean, se = float(difference.mean()), float(difference.std(ddof=1) / np.sqrt(len(difference)))
        candidates.append({"strength": strength, "prior": prior, "old_nll_change": mean,
                           "old_paired_se": se, "old_upper_heuristic": mean + 1.645 * se,
                           "new_nll": float(loss[1].mean()), "eligible": mean + 1.645 * se <= .02})
    eligible = [i for i, row in enumerate(candidates) if row["eligible"]]
    if not eligible:
        raise AssertionError("Unchanged anchor must be feasible")
    chosen = min(eligible, key=lambda i: (candidates[i]["new_nll"], i))
    selected = deepcopy(model)
    selected["prior"] = candidates[chosen]["prior"]
    return selected, {"candidates": candidates, "selected_index": chosen,
                      "fit_prior": model["prior"], "development_labelled_queries": len(old_development["ids"]) + len(new_development["ids"]),
                      "old_guard_is_selection_heuristic_not_guarantee": True}
