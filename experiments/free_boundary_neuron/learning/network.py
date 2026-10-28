"""Small hard-spiking network with explicit reverse-mode differentiation.

Scientific runs always use hard spikes. The smooth mode exists solely to
check the reverse-mode algebra against finite differences. A surrogate
gradient is not the finite-difference derivative of the hard objective.
Separately softened action gates need not sum to one; the smooth fixture is
an algebraic derivative check, not a normalized stochastic stopping policy.
"""

import numpy as np
from scipy.special import expit

from ..math.hitting import hit_probability_and_gradient
from .task import ABSTAIN_REWARD, TERMINAL_BOUND, action_arrays


THRESHOLDS = np.linspace(0.7, 1.4, 8)


def activation(value, gradient, *, soft=False):
    """A hard forward activation and an explicitly declared backward rule."""
    if gradient == "standard":
        primitive = expit(value / 0.5)
        slope = primitive * (1 - primitive) / 0.5
    elif gradient == "first_passage":
        primitive, slope = hit_probability_and_gradient(
            -value, 1.0, 0.25, 1.0, rate=0.1
        )
    else:
        raise ValueError("unknown surrogate gradient")
    return primitive if soft else (value > 0).astype(float), slope


def initialize(seed, method):
    """Identical neural initialization across boundary and gradient arms."""
    rng = np.random.default_rng(np.random.SeedSequence([seed, 701]))
    weights = rng.normal(0, 0.005, (6, 8))
    weights[0] = np.linspace(0.65, 1.35, 8) + rng.normal(0, 0.02, 8)
    weights[1] = np.linspace(0.1, 0.3, 8)
    parameters = {"weights": weights, "readout": np.full(8, 0.14), "bias": np.zeros(1)}
    if method == "direct":
        head = np.zeros((6, 2))
        head[0, 0] = np.log(np.expm1(1.6 - TERMINAL_BOUND))
        head[0, 1] = -2.0
        parameters["head"] = head
    return parameters


def forward(parameters, episodes, gradient, *, soft=False, cache_gradients=True):
    """Causal bipolar IF bank, reset after each spike, accumulated readout."""
    if soft and not cache_gradients:
        raise ValueError("the soft derivative fixture requires its gradient path")
    features = episodes.features
    count, horizon, _ = features.shape
    membrane, trace = np.zeros((count, 8)), np.zeros((count, 8))
    voltage, slopes, traces, spikes = [], [], [], []
    for t in range(horizon):
        before_reset = membrane + features[:, t] @ parameters["weights"]
        if cache_gradients:
            positive, dp = activation(before_reset - THRESHOLDS, gradient, soft=soft)
            negative, dn = activation(-before_reset - THRESHOLDS, gradient, soft=soft)
        else:
            # Deployment uses hard comparisons only. Neither the surrogate
            # primitive nor its slope is part of forward inference cost.
            positive = (before_reset > THRESHOLDS).astype(float)
            negative = (-before_reset > THRESHOLDS).astype(float)
        signed_spike = positive - negative
        membrane = before_reset - THRESHOLDS * signed_spike
        trace = trace + signed_spike
        voltage.append(trace @ parameters["readout"] + parameters["bias"][0])
        if cache_gradients:
            slopes.append(dp + dn)
            traces.append(trace.copy())
        spikes.append(np.sum(positive + negative, axis=1))
    cache = (
        {"slopes": np.stack(slopes, axis=1), "traces": np.stack(traces, axis=1)}
        if cache_gradients
        else {}
    )
    return np.stack(voltage, axis=1), np.stack(spikes, axis=1), cache


def boundaries(parameters, episodes, method, *, fixed=(1.6, -1.0), free=None):
    if method == "fixed":
        return (
            np.full_like(episodes.observations, fixed[0]),
            np.full_like(episodes.observations, fixed[1]),
        ), None
    if method == "free":
        if free is None:
            raise ValueError("free-boundary arm requires its actual Bellman profile")
        return free, None
    if method != "direct":
        raise ValueError("unknown boundary method")
    raw = episodes.boundary_features @ parameters["head"]
    choice = TERMINAL_BOUND + np.logaddexp(0, raw[..., 0])
    # Negative values explicitly disable early abstention. A sigmoid-only
    # positive bound would force abstention whenever accumulated evidence=0.
    abstain = TERMINAL_BOUND * np.tanh(raw[..., 1])
    return (choice, abstain), raw


def utility_and_derivatives(
    voltage, choice, abstain, episodes, gradient, *, soft=False
):
    """Differentiate complete stopped-path utility, including alive masks."""
    smooth = (lambda z: activation(z, gradient, soft=True)[0]) if soft else None
    positive, negative, neutral, final = action_arrays(
        voltage, choice, abstain, episodes.deadline, smooth=smooth
    )
    wait = 1 - positive - negative - neutral
    count, horizon = voltage.shape
    future = np.zeros((count, horizon + 1))
    truth = episodes.truth
    for t in range(horizon - 1, -1, -1):
        future[:, t] = positive[:, t] * truth - negative[:, t] * truth
        future[:, t] += neutral[:, t] * ABSTAIN_REWARD
        future[:, t] += wait[:, t] * (future[:, t + 1] - episodes.cost)
    alive = np.ones((count, horizon))
    for t in range(1, horizon):
        alive[:, t] = alive[:, t - 1] * wait[:, t - 1]
    continuing = future[:, 1:] - episodes.cost[:, None]
    plus_gain = alive * (truth[:, None] - continuing)
    minus_gain = alive * (-truth[:, None] - continuing)
    neutral_gain = alive * (ABSTAIN_REWARD - continuing)
    plus_slope = activation(voltage - choice, gradient)[1]
    minus_slope = activation(-voltage - choice, gradient)[1]
    neutral_slope = activation(abstain - np.abs(voltage), gradient)[1]
    derivative_voltage = plus_gain * plus_slope - minus_gain * minus_slope
    derivative_voltage -= neutral_gain * neutral_slope * np.sign(voltage)
    derivative_choice = -plus_gain * plus_slope - minus_gain * minus_slope
    derivative_abstain = neutral_gain * neutral_slope
    final_derivative = alive * (
        (truth[:, None] - ABSTAIN_REWARD)
        * activation(voltage - TERMINAL_BOUND, gradient)[1]
        - (-truth[:, None] - ABSTAIN_REWARD)
        * activation(-voltage - TERMINAL_BOUND, gradient)[1]
    )
    derivative_voltage = np.where(final, final_derivative, derivative_voltage)
    derivative_choice = np.where(final, 0, derivative_choice)
    derivative_abstain = np.where(final, 0, derivative_abstain)
    utility = np.mean(future[:, 0] - episodes.cost)
    return (
        utility,
        derivative_voltage / count,
        derivative_choice / count,
        derivative_abstain / count,
    )


def loss_and_gradient(
    parameters,
    episodes,
    method,
    gradient,
    *,
    fixed=(1.6, -1.0),
    free=None,
    soft=False,
    calibration_weight=0.5,
):
    voltage, spike_counts, cache = forward(parameters, episodes, gradient, soft=soft)
    (choice, abstain), raw = boundaries(
        parameters, episodes, method, fixed=fixed, free=free
    )
    utility, dv, dc, da = utility_and_derivatives(
        voltage, choice, abstain, episodes, gradient, soft=soft
    )
    valid = np.arange(voltage.shape[1])[None, :] < episodes.deadline[:, None]
    target = (episodes.truth[:, None] + 1) / 2
    calibration = (
        np.sum((np.logaddexp(0, voltage) - target * voltage) * valid) / valid.sum()
    )
    dv = -dv + calibration_weight * (expit(voltage) - target) * valid / valid.sum()
    derivatives = {name: np.zeros_like(value) for name, value in parameters.items()}
    derivatives["bias"][0] = np.sum(dv)
    derivatives["readout"] = np.einsum("nt,nth->h", dv, cache["traces"])
    if method == "direct":
        draw = np.stack(
            (
                -dc * expit(raw[..., 0]),
                -da * TERMINAL_BOUND * (1 - np.tanh(raw[..., 1]) ** 2),
            ),
            axis=-1,
        )
        derivatives["head"] = np.einsum("ntf,ntk->fk", episodes.boundary_features, draw)
    # Exact reverse-mode algebra for the chosen smooth primitive, or its
    # custom surrogate substitution when the forward spikes are hard.
    dmembrane = np.zeros((len(episodes.truth), 8))
    dtrace = np.zeros_like(dmembrane)
    for t in range(voltage.shape[1] - 1, -1, -1):
        dtrace += dv[:, t, None] * parameters["readout"]
        du = dmembrane + (dtrace - THRESHOLDS * dmembrane) * cache["slopes"][:, t]
        derivatives["weights"] += episodes.features[:, t].T @ du
        dmembrane = du
    loss = -utility + calibration_weight * calibration
    info = {
        "loss": float(loss),
        "utility": float(utility),
        "calibration": float(calibration),
        "prefix_spikes": float(np.sum(spike_counts * valid)),
    }
    return float(loss), derivatives, info


class Adam:
    """Bounded, explicit Adam implementation; no unavailable Torch backend."""

    def __init__(self, parameters, learning_rate=0.005):
        self.first = {k: np.zeros_like(v) for k, v in parameters.items()}
        self.second = {k: np.zeros_like(v) for k, v in parameters.items()}
        self.step_count = 0
        self.learning_rate = learning_rate
        self.clipped_steps = 0
        self.projected_scalars = 0

    def step(self, parameters, gradients):
        norm = float(np.sqrt(sum(np.sum(v * v) for v in gradients.values())))
        if not np.isfinite(norm):
            raise FloatingPointError("nonfinite surrogate gradient")
        scale = min(1.0, 5.0 / max(norm, 1e-12))
        self.clipped_steps += norm > 5.0
        self.step_count += 1
        for key, parameter in parameters.items():
            gradient = gradients[key] * scale
            self.first[key] = 0.9 * self.first[key] + 0.1 * gradient
            self.second[key] = 0.999 * self.second[key] + 0.001 * gradient**2
            first = self.first[key] / (1 - 0.9**self.step_count)
            second = self.second[key] / (1 - 0.999**self.step_count)
            parameter -= self.learning_rate * first / (np.sqrt(second) + 1e-8)
            limit = 6.0 if key in ("bias", "head") else 3.0
            self.projected_scalars += int(np.sum(np.abs(parameter) > limit))
            np.clip(parameter, -limit, limit, out=parameter)
        return norm
