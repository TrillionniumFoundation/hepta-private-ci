"""Explicit second-round dispatch; no monkeypatching of frozen model inference."""

import numpy as np

from .. import learners, task


def predict(model, history, native=None, raw=None):
    if model["kind"] == "signed_event_filter":
        from .pulse import predict as event_predict

        return event_predict(model, history, native=native, raw=raw)
    if model["kind"] in {"protected_filter", "fixed_mixture", "likelihood_mixture"}:
        from .adaptation import predict as adaptive_predict

        return adaptive_predict(model, history)
    return learners.predict(model, history, native=native, raw=raw)


def forecast(model, history, horizon, native=None):
    indices = np.flatnonzero(np.isclose(task.HORIZONS, horizon, atol=1e-12))
    if len(indices) != 1:
        raise ValueError("Forecast horizon must be registered")
    means, variances = predict(model, history, native)
    return means[:, int(indices[0])], variances[:, int(indices[0])]


def value_scores(model, history, horizon, native=None, cost_multiplier=1.0):
    """Same registered variance VOI as round one, with explicit model dispatch.

    Quantized or projected predictors use a declared plug-in approximation;
    actual post-action delivery is the primary score.
    """
    means, variances = predict(model, history, native)
    multiplier = np.broadcast_to(np.asarray(cost_multiplier, dtype=float), (len(means),))
    if not np.isfinite(multiplier).all() or np.any(multiplier <= 0):
        raise ValueError("Public action cost must be finite and positive")
    index = int(np.flatnonzero(np.isclose(task.HORIZONS, horizon))[0])
    current, terminal = variances[:, 0], variances[:, index]
    q, scale = model["planning_q"], model["planning_noise_scale"]
    repair_noise = scale * task.REPAIR_VARIANCE
    repair_cost, wait_cost = task.REPAIR_COST * multiplier, task.WAIT_COST * multiplier
    gain = current * current / (current + repair_noise)
    scores = {"stop": terminal, "repair": np.maximum(0.0, terminal - gain) + repair_cost}
    if horizon > 1.5:
        propagated = current + q
        wait_noise = scale * task.OBSERVATION_VARIANCE
        wait_gain = propagated * propagated / (propagated + wait_noise)
        after_wait = propagated * wait_noise / (propagated + wait_noise)
        after_terminal = np.maximum(0.0, terminal - wait_gain)
        repair_gain = after_wait * after_wait / (after_wait + repair_noise)
        scores["wait"] = wait_cost + np.minimum(
            after_terminal, np.maximum(0.0, after_terminal - repair_gain) + repair_cost
        )
    return means[:, index], scores, {
        "current_mean": means[:, 0], "terminal_mean": means[:, index],
        "current_variance": current, "terminal_variance": terminal,
        "planning_q": q, "planning_noise_scale": scale, "cost_multiplier": multiplier,
    }
