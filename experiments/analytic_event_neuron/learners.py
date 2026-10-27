"""Small learned filters and full-history/native/pulse Gaussian readouts."""

import numpy as np

from . import task
from .analytic import event_probs
from .runtime import counter_uniform, pulse_initial_state, pulse_transition, pulse_features


def filter_states(h, parameters, return_path=False):
    drift, q, noise_scale = parameters
    n = len(h["obs"])
    mean, variance, last = np.zeros(n), np.ones(n), np.zeros(n)
    path = []
    for j in range(h["obs"].shape[1]):
        active = h["occupied"][:, j]
        dt = np.where(active, h["times"][:, j] - last, 0.0)
        if np.any(dt < 0):
            raise ValueError("Observation clock regression")
        mean = mean + drift * dt
        variance = variance + q * dt
        observed = active & h["mask"][:, j]
        gain = np.where(observed, variance / (variance + noise_scale * h["obs_var"][:, j]), 0.0)
        mean = mean + gain * (h["obs"][:, j] - mean)
        variance = variance * (1.0 - gain)
        last = np.where(active, h["times"][:, j], last)
        if return_path:
            path.append((mean.copy(), variance.copy(), active.copy()))
    return (mean, variance, path) if return_path else (mean, variance)


def raw_features(h, feature, parameters=None, seed=0, native=None):
    if feature == "history":
        seen = h["mask"] & h["occupied"]
        values = np.where(seen, h["obs"], 0.0)
        age = task.latest_time(h)[:, None] - h["times"]
        return np.column_stack([values, seen.astype(float), age * seen,
                                h["obs_var"] * seen, values * age,
                                values / (h["obs_var"] + 0.05), task.latest_time(h), seen.sum(1)])
    if feature in ("pulse", "mean_drive", "pulse_no_reset"):
        _, _, path = filter_states(h, parameters, return_path=True)
        result = []
        for row, identity in enumerate(h["ids"]):
            state = pulse_initial_state()
            # Stage suffixes do not alter already observed random marks.
            trajectory_id = str(identity).split("/")[0]
            for tick, (mean, variance, active) in enumerate(path, 1):
                if active[row]:
                    probabilities = event_probs(mean[row], variance[row], task.LOWER, task.UPPER)
                    uniform = counter_uniform(seed, trajectory_id, tick)
                    state, _ = pulse_transition(state, probabilities, uniform,
                                                mode="mean_drive" if feature == "mean_drive" else "sample",
                                                reset_enabled=feature != "pulse_no_reset")
            result.append(pulse_features(state))
        return np.asarray(result, dtype=float)
    if feature == "sparse":
        if native is None:
            raise ValueError("Real native baseline requires an executed native bridge")
        result = []
        for i, identity in enumerate(h["ids"]):
            occupied = h["occupied"][i]
            receipt = native.sparse_features(case=str(identity), observations=h["obs"][i, occupied].tolist(),
                                             times=h["times"][i, occupied].tolist(), mask=h["mask"][i, occupied].tolist(),
                                             obs_var=h["obs_var"][i, occupied].tolist())
            result.append(receipt["features"])
        return np.asarray(result, dtype=float)
    raise ValueError("Unknown feature family")


def predict(model, h, native=None, raw=None):
    if model["kind"] == "filter":
        if model.get("equivalent_classical_implementation"):
            drift, q, noise_scale = model["parameters"]
            means, variances = [], []
            for row in range(len(h["obs"])):
                observed = h["mask"][row] & h["occupied"][row]
                times = h["times"][row, observed]
                future_time = task.latest_time(task.subset(h, row))[0] + task.HORIZONS
                covariance = 1.0 + q * np.minimum(times[:, None], times[None, :])
                covariance += np.diag(noise_scale * h["obs_var"][row, observed])
                cross = 1.0 + q * times
                residual = h["obs"][row, observed] - drift * times
                solved = np.linalg.solve(covariance, np.column_stack([residual, cross]))
                means.append(drift * future_time + cross @ solved[:, 0])
                variances.append(1.0 + q * future_time - cross @ solved[:, 1])
            return np.asarray(means), np.asarray(variances)
        mean, variance = filter_states(h, model["parameters"])
        drift, q, _ = model["parameters"]
        return mean[:, None] + drift * task.HORIZONS, variance[:, None] + q * task.HORIZONS
    if raw is None:
        raw = raw_features(h, model["feature"], model.get("filter_parameters"), model.get("seed", 0), native)
    x = np.column_stack([np.ones(len(raw)), (raw - np.asarray(model["center"])) / np.asarray(model["scale"])])
    means = x @ np.asarray(model["weights"])
    log_variance = x @ np.asarray(model["variance_weights"])
    variances = np.exp(np.clip(log_variance, -7.0, 5.0)) * np.asarray(model["variance_scale"])
    return means, np.clip(variances, 1e-5, 100.0)


def forecast(model, h, horizon, native=None):
    index = np.flatnonzero(np.isclose(task.HORIZONS, horizon, atol=1e-12))
    if len(index) != 1:
        raise ValueError("Horizon must be registered")
    means, variances = predict(model, h, native)
    j = int(index[0])
    return means[:, j], variances[:, j]


def nll(target, means, variances):
    return float(np.mean(0.5 * (np.log(2.0 * np.pi * variances) + (target - means) ** 2 / variances)))


def value_scores(model, h, horizon, native=None, cost_multiplier=1.0):
    """Declared variance plug-in VOI. No hypothetical or private observations read.

    Gaussian filter gives the exact MSE dynamic-programming comparison for the
    fitted law. Readout models use the same formula with their own marginal
    variance estimates; this is a declared approximation evaluated by outcomes.
    """
    means, variances = predict(model, h, native)
    cost_multiplier = np.broadcast_to(np.asarray(cost_multiplier, dtype=float), (len(means),))
    if not np.isfinite(cost_multiplier).all() or np.any(cost_multiplier <= 0):
        raise ValueError("Action cost multiplier must be finite and positive")
    j = int(np.flatnonzero(np.isclose(task.HORIZONS, horizon))[0])
    p, terminal_variance = variances[:, 0], variances[:, j]
    q = model["planning_q"]
    noise_scale = model["planning_noise_scale"]
    r = noise_scale * task.REPAIR_VARIANCE
    immediate_gain = p * p / (p + r)
    repair_cost = task.REPAIR_COST * cost_multiplier
    wait_cost = task.WAIT_COST * cost_multiplier
    repair = np.maximum(0.0, terminal_variance - immediate_gain) + repair_cost
    scores = {"stop": terminal_variance, "repair": repair}
    if horizon > 1.5:
        propagated = p + q
        wait_r = noise_scale * task.OBSERVATION_VARIANCE
        gain = propagated * propagated / (propagated + wait_r)
        after_wait = propagated * wait_r / (propagated + wait_r)
        after_wait_terminal = np.maximum(0.0, terminal_variance - gain)
        gain_again = after_wait * after_wait / (after_wait + r)
        scores["wait"] = wait_cost + np.minimum(
            after_wait_terminal, np.maximum(0.0, after_wait_terminal - gain_again) + repair_cost)
    return means[:, j], scores, {"current_mean": means[:, 0], "terminal_mean": means[:, j],
                               "current_variance": p, "terminal_variance": terminal_variance,
                               "planning_q": q, "planning_noise_scale": noise_scale,
                               "cost_multiplier": cost_multiplier}
