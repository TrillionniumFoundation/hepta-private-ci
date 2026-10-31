"""Public-history routing and a pointwise protected Gaussian adaptation head.

The anchor is immutable. Candidate parameters are fitted on training data;
neither query targets nor hidden regime labels enter routing or prediction.
Mixture moments are explicitly Gaussian projections, not exact mixture laws.
"""

from copy import deepcopy
import hashlib
import json

import numpy as np
from scipy.special import expit, logsumexp

from .. import learners, task
from ..analytic import event_log_probs


SCHEMA = "hepta.analytic-event.protected-filter.v1"
KINDS = ("fixed_mixture", "likelihood_mixture", "protected_filter")


def document_digest(model):
    return hashlib.sha256(json.dumps(model, sort_keys=True, separators=(",", ":"),
                                    allow_nan=False).encode()).hexdigest()


def _validate_filter(model):
    parameters = np.asarray(model.get("parameters"), dtype=float)
    if (model.get("kind") != "filter" or parameters.shape != (3,)
            or not np.isfinite(parameters).all() or np.any(parameters[1:] <= 0)):
        raise ValueError("A finite Gaussian filter with positive variances is required")


def _validate_history(h):
    required = ("obs", "times", "mask", "occupied", "obs_var")
    shape = np.asarray(h["obs"]).shape
    if len(shape) != 2 or any(np.asarray(h[key]).shape != shape for key in required):
        raise ValueError("Public history fields must have one common two-dimensional shape")
    if any(np.asarray(h[key]).dtype != bool for key in ("mask", "occupied")):
        raise ValueError("Observation and occupancy masks must be Boolean")
    active, seen = h["occupied"], h["occupied"] & h["mask"]
    if (not np.isfinite(h["obs"][seen]).all()
            or not np.isfinite(h["times"][active]).all()
            or np.any(h["times"][active] < 0)
            or not np.isfinite(h["obs_var"][seen]).all()
            or np.any(h["obs_var"][seen] <= 0)):
        raise ValueError("Observed values/times must be finite and sensor variances positive")


def make_model(anchor, adaptive, kind="protected_filter", epsilon=0.02,
               routing="likelihood", prior=0.5, classical=False, output_quantization=None):
    """Construct a serializable head; prior and epsilon are fixed by protocol."""
    _validate_filter(anchor)
    _validate_filter(adaptive)
    if kind not in KINDS or routing not in ("fixed", "likelihood"):
        raise ValueError("Unknown adaptation or routing kind")
    if not np.isfinite(epsilon) or epsilon < 0 or not 0 < prior < 1:
        raise ValueError("A nonnegative finite guard and interior prior are required")
    if output_quantization not in (None, "guarded_q24_v1") or (
            output_quantization is not None and kind != "protected_filter"):
        raise ValueError("Quantized protection is only defined for the protected Gaussian head")
    model = {"schema": SCHEMA, "kind": kind, "anchor": deepcopy(anchor),
             "adaptive": deepcopy(adaptive), "epsilon": float(epsilon),
             "routing": routing, "prior": float(prior),
             "planning_q": float(anchor["parameters"][1]),
             "planning_noise_scale": float(anchor["parameters"][2]),
             "planning_scope": "anchor variance plug-in approximation; actual outcomes score control"}
    if classical:
        model["anchor"]["equivalent_classical_implementation"] = True
        model["adaptive"]["equivalent_classical_implementation"] = True
    if output_quantization is not None:
        model["output_quantization"] = output_quantization
        model["event_probability_quantization"] = "anchor_constrained_q24_v1"
    return model


def public_log_likelihood(model, h):
    """Exact observed-sensor likelihood under the declared linear Gaussian law.

    Times, missingness and acquired sensor variances are conditioned upon.
    They have the same exogenous mechanism under both experts. A missing slot
    contributes propagation but no observation likelihood. Simultaneous actual
    sensors contribute their own conditional innovations exactly once.
    """
    _validate_filter(model)
    _validate_history(h)
    drift, q, noise_scale = model["parameters"]
    n = len(h["obs"])
    mean, variance, last, score = np.zeros(n), np.ones(n), np.zeros(n), np.zeros(n)
    for j in range(h["obs"].shape[1]):
        active = h["occupied"][:, j]
        dt = np.where(active, h["times"][:, j] - last, 0.0)
        if np.any(dt < 0):
            raise ValueError("Observation clock regression")
        mean += drift * dt
        variance += q * dt
        observed = active & h["mask"][:, j]
        indices = np.flatnonzero(observed)
        innovation = h["obs"][indices, j] - mean[indices]
        innovation_variance = variance[indices] + noise_scale * h["obs_var"][indices, j]
        score[indices] += -.5 * (np.log(2 * np.pi * innovation_variance)
                                + innovation * innovation / innovation_variance)
        gain = variance[indices] / innovation_variance
        mean[indices] += gain * innovation
        variance[indices] *= 1.0 - gain
        last = np.where(active, h["times"][:, j], last)
    return score


def routing_weights(model, h):
    """Posterior adaptive-expert mass from public observation likelihood only."""
    if model.get("schema") != SCHEMA or model.get("kind") not in KINDS:
        raise ValueError("Unsupported adaptation document")
    prior = float(model["prior"])
    if not 0 < prior < 1:
        raise ValueError("Invalid expert prior")
    if model["kind"] == "fixed_mixture" or model["routing"] == "fixed":
        return np.full(len(h["obs"]), prior)
    if model["routing"] != "likelihood":
        raise ValueError("Unknown likelihood routing contract")
    a = public_log_likelihood(model["anchor"], h)
    b = public_log_likelihood(model["adaptive"], h)
    return expit(np.log(prior) - np.log1p(-prior) + b - a)


def protected_gaussian(anchor_mean, anchor_variance, proposal_mean, epsilon=0.02):
    """Guard each horizon with a Gaussian pointwise log-density envelope.

    d = clip((m1-m0)/sqrt(v0), +/-epsilon), c = 1+|d|.
    sup_x [NLL(N(m0+sqrt(v0)d,v0*c),x)-NLL(N(m0,v0),x)]
      = .5*log(c)+d*d/(2*(c-1)) <= |d| <= epsilon.
    The d=0 branch is exactly the unchanged anchor. This is a real-arithmetic
    statement; FP64 verification uses a separately declared numeric tolerance.
    """
    m, v, proposal = np.broadcast_arrays(np.asarray(anchor_mean, dtype=float),
                                        np.asarray(anchor_variance, dtype=float),
                                        np.asarray(proposal_mean, dtype=float))
    if (not np.isfinite(epsilon) or epsilon < 0 or np.any(v <= 0)
            or not all(np.isfinite(x).all() for x in (m, v, proposal))):
        raise ValueError("Finite means, positive variances and a nonnegative guard required")
    deviation = np.clip((proposal - m) / np.sqrt(v), -epsilon, epsilon)
    magnitude = np.abs(deviation)
    output_mean = m + np.sqrt(v) * deviation
    output_variance = v * (1.0 + magnitude)
    bound = 0.5 * (np.log1p(magnitude) + magnitude)
    return output_mean, output_variance, {
        "normalized_correction": deviation, "pointwise_nll_bound": bound,
        "unconstrained_normalized_correction": (proposal - m) / np.sqrt(v),
        "clipped": np.abs(proposal - m) > epsilon * np.sqrt(v),
    }


def predict_details(model, h):
    """Return Gaussian moments and routing/guard diagnostics for public histories."""
    _validate_history(h)
    # Missing values are absent information even if their storage contains NaN.
    # Strip all nonpublic auxiliary fields before invoking either implementation.
    active, seen = h["occupied"], h["occupied"] & h["mask"]
    h = {"obs": np.where(seen, h["obs"], 0.0),
         "times": np.where(active, h["times"], 0.0), "mask": seen,
         "occupied": active, "obs_var": np.where(seen, h["obs_var"], 1.0),
         "ids": np.asarray(h.get("ids", np.arange(len(h["obs"]))))}
    if model["kind"] == "filter":
        mean, variance = learners.predict(model, h)
        return mean, variance, {}
    _validate_filter(model["anchor"])
    _validate_filter(model["adaptive"])
    anchor_mean, anchor_variance = learners.predict(model["anchor"], h)
    candidate_mean, candidate_variance = learners.predict(model["adaptive"], h)
    weight = routing_weights(model, h)[:, None]
    proposal_mean = anchor_mean + weight * (candidate_mean - anchor_mean)
    # Stable total-variance identity; no subtraction of large squared means.
    proposal_variance = ((1.0 - weight) * anchor_variance + weight * candidate_variance
                         + weight * (1.0 - weight) * (candidate_mean - anchor_mean) ** 2)
    details = {"adaptive_weight": weight[:, 0], "proposal_mean": proposal_mean,
               "proposal_variance": proposal_variance,
               "anchor_model_sha256": document_digest(model["anchor"]),
               "adaptive_model_sha256": document_digest(model["adaptive"])}
    if model["kind"] == "protected_filter":
        if model.get("output_quantization") == "guarded_q24_v1":
            from .quantized_guard import guard_quantized
            mean, variance, guard = guard_quantized(anchor_mean, anchor_variance,
                                                    proposal_mean, model["epsilon"])
        elif model.get("output_quantization") is None:
            mean, variance, guard = protected_gaussian(anchor_mean, anchor_variance,
                                                      proposal_mean, model["epsilon"])
        else:
            raise ValueError("Unsupported protected output quantization")
        details.update(guard)
        return mean, variance, details
    if model["kind"] not in ("fixed_mixture", "likelihood_mixture"):
        raise ValueError("Unknown adaptation head")
    return proposal_mean, proposal_variance, details


def predict(model, h):
    mean, variance, _ = predict_details(model, h)
    return mean, variance


def forecast(model, h, horizon):
    index = np.flatnonzero(np.isclose(task.HORIZONS, horizon, atol=1e-12))
    if len(index) != 1:
        raise ValueError("Forecast horizon must be registered")
    mean, variance = predict(model, h)
    return mean[:, int(index[0])], variance[:, int(index[0])]


def exact_mixture_log_scores(model, h, target):
    """Supplemental exact-mixture scores; these never replace the Gaussian gate."""
    if model["kind"] not in ("fixed_mixture", "likelihood_mixture"):
        raise ValueError("Exact mixture scoring requires a mixture head")
    w = routing_weights(model, h)
    logs, event_logs = [], []
    with np.errstate(divide="ignore"):
        log_weights = [np.log1p(-w), np.log(w)]
    labels = task.event_labels(target)
    for component, log_weight in zip((model["anchor"], model["adaptive"]), log_weights):
        mean, variance = learners.predict(component, h)
        logs.append(log_weight[:, None] - .5 * (
            np.log(2 * np.pi * variance) + (target - mean) ** 2 / variance))
        event = np.take_along_axis(event_log_probs(mean, variance, task.LOWER, task.UPPER),
                                  labels[..., None], -1)[..., 0]
        event_logs.append(log_weight[:, None] + event)
    return -logsumexp(logs, axis=0), -logsumexp(event_logs, axis=0)
