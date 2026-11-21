"""A causal smooth boundary pulse fitted to paired training-task losses.

One decision occurs at T-H. Low/high teachers use the same complete prefix,
future training suffix and final task label. Both restore b=0 after one step.
The learned contrast is a finite-policy improvement surrogate, not a Bellman
optimal value or the financial equity/default free boundary.
"""

from dataclasses import asdict
import math

import numpy as np
import torch
from torch import nn

from qualification.hcsn_adaptive.batched_flow import BatchedFlow, FlowConfig, FlowState


def ridge_fit(layer, features, targets, penalty):
    if not math.isfinite(penalty) or penalty <= 0 or not torch.isfinite(targets).all():
        raise ValueError("finite targets and positive ridge penalty required")
    mean = features.mean(0)
    scale = features.std(0, unbiased=False).clamp_min(1e-8)
    normalized = (features - mean) / scale
    design = torch.cat((normalized, torch.ones_like(normalized[:, :1])), 1)
    regularizer = torch.eye(design.shape[1], dtype=design.dtype, device=design.device) * penalty
    regularizer[-1, -1] = 0
    coefficients = torch.linalg.solve(design.T @ design + regularizer, design.T @ targets)
    if not torch.isfinite(coefficients).all():
        raise FloatingPointError("nonfinite ridge coefficients")
    layer.weight.copy_(coefficients[:-1].T)
    layer.bias.copy_(coefficients[-1])
    return mean, scale


class TaskBoundaryModel(nn.Module):
    def __init__(self, flow, length, horizon=4, low=-0.25, high=0.25):
        super().__init__()
        if (not isinstance(flow, FlowConfig) or flow.upper_mode != "reflecting"
                or type(length) is not int or type(horizon) is not int
                or not 2 <= horizon < length or not -flow.boundary_limit <= low < high <= flow.boundary_limit):
            raise ValueError("reflecting finite model, 2<=H<T and valid boundary endpoints required")
        self.encoder = BatchedFlow(flow)
        self.length, self.horizon, self.low, self.high = length, horizon, low, high
        self.decision_step = length - horizon
        self.width = len(self.encoder.feature_names)
        self.critic_width = (1 + flow.content_size) * (flow.bins + flow.stages + 1) + flow.input_size + self.width + 3
        self.readout = nn.Linear(2 * self.width, 1, dtype=torch.float64)
        self.critic = nn.Linear(self.critic_width, 1, dtype=torch.float64)
        for name, size, fill in (("readout_mean", 2*self.width, 0), ("readout_scale", 2*self.width, 1),
                                 ("critic_mean", self.critic_width, 0), ("critic_scale", self.critic_width, 1)):
            self.register_buffer(name, torch.full((size,), float(fill), dtype=torch.float64))
        for name, value in (("advantage_scale", 1.0), ("input_mean", 0.0), ("input_scale", 1.0)):
            self.register_buffer(name, torch.tensor(value, dtype=torch.float64))
        self.requires_grad_(False)

    def contract(self):
        return {"flow": asdict(self.encoder.config), "length": self.length, "horizon": self.horizon,
                "decision_step": self.decision_step, "low": self.low, "high": self.high,
                "teacher": "one low/high boundary pulse, restore zero, same suffix and endpoint label",
                "clock": "known regular schedule; current input sampled at left edge; no P3 clock substitution",
                "critic_inputs": "complete probability/content/phase state, current input, accumulated causal feature mean, boundary, remaining fraction, elapsed fraction",
                "frozen_encoder_parameters": sum(p.numel() for p in self.encoder.parameters()),
                "readout_parameters": sum(p.numel() for p in self.readout.parameters()),
                "critic_parameters": sum(p.numel() for p in self.critic.parameters()),
                "controller_parameters": {"always_zero": 0, "fixed_pulse": 1, "input_pulse": 2,
                                          "task_advantage": sum(p.numel() for p in self.critic.parameters())+2},
                "claim": "finite realized training-task loss contrast; not global Bellman/network optimality"}

    def validate_data(self, x, intervals):
        if (x.ndim != 3 or x.shape[1:] != (self.length, self.encoder.config.input_size)
                or not 1 <= len(x) <= self.encoder.config.max_batch or not torch.isfinite(x).all()):
            raise ValueError("invalid finite [batch,T,input] pilot data")
        dt = np.asarray(intervals, dtype=np.float64)
        target = round(self.encoder.config.dt * 1_000_000)
        if (dt.shape != x.shape[:2] or not np.isfinite(dt).all()
                or not np.allclose(dt * 1_000_000, target, rtol=0, atol=1e-6)):
            raise ValueError("pilot requires its declared known regular clock; irregular data are rejected")

    def prefix(self, x):
        state = self.encoder.initial_state(len(x), like=x)
        total = x.new_zeros(len(x), self.width)
        for step in range(self.decision_step):
            feature, state, _ = self.encoder.step(x[:, step], state, boundary_override=0.0)
            total = total + feature
        return state, total

    def causal_features(self, state, current_input, prefix_total):
        """No future suffix, target, or task label is accepted by this function."""
        if current_input.ndim != 2 or prefix_total.shape != (len(current_input), self.width):
            raise ValueError("invalid causal decision context")
        elapsed = state.time_micros / (self.length * self.encoder.config.dt * 1_000_000)
        extra = current_input.new_tensor([self.horizon / self.length, elapsed]).expand(len(current_input), -1)
        return torch.cat((state.density.flatten(1).to(current_input), current_input,
                          prefix_total / self.decision_step, state.boundary[:, None].to(current_input), extra), 1)

    def boundary(self, state, current_input, prefix_total, policy):
        """Smooth online policy: current causal context -> one boundary pulse."""
        kind = policy["kind"]
        if kind == "zero":
            return current_input.new_zeros(len(current_input))
        if kind == "fixed":
            pulse = float(policy["value"])
            if not self.low <= pulse <= self.high:
                raise ValueError("fixed pulse outside the declared teacher endpoints")
            return current_input.new_full((len(current_input),), pulse)
        if kind == "input":
            score = float(policy["gain"]) * (current_input[:, 0] - self.input_mean) / self.input_scale
            score = score + float(policy["offset"])
        elif kind == "task":
            temperature = float(policy["temperature_multiplier"])
            if not math.isfinite(temperature) or temperature <= 0:
                raise ValueError("positive critic temperature required")
            features = self.causal_features(state, current_input, prefix_total)
            advantage = self.critic((features - self.critic_mean) / self.critic_scale).squeeze(-1)
            score = (advantage / self.advantage_scale - float(policy["offset_multiplier"])) / temperature
        else:
            raise ValueError("unknown pulse policy")
        if not torch.isfinite(score).all():
            raise FloatingPointError("nonfinite pulse score")
        return self.low + (self.high - self.low) * torch.sigmoid(score)

    def suffix(self, x, state, prefix_total, boundary):
        total = prefix_total
        for step in range(self.decision_step, self.length):
            pulse = boundary if step == self.decision_step else 0.0
            feature, state, _ = self.encoder.step(x[:, step], state, boundary_override=pulse)
            total = total + feature
        features = torch.cat((feature, total / self.length), 1)
        return features, total[:, 0], state

    def predict(self, x, intervals, policy):
        self.validate_data(x, intervals)
        state, total = self.prefix(x)
        pulse = self.boundary(state, x[:, self.decision_step], total, policy)
        features, events, final_state = self.suffix(x, state, total, pulse)
        prediction = self.readout((features - self.readout_mean) / self.readout_scale)
        return {"prediction": prediction, "features": features, "events": events,
                "pulse": pulse, "state": final_state}

    def fit_readout(self, x, intervals, targets, penalty=0.001):
        with torch.no_grad():
            features = self.predict(x, intervals, {"kind": "zero"})["features"]
            mean, scale = ridge_fit(self.readout, features, targets, penalty)
            self.readout_mean.copy_(mean)
            self.readout_scale.copy_(scale)

    def teacher(self, x, intervals, targets, *, split, event_cost):
        if split != "train":
            raise ValueError("counterfactual teachers may only consume training labels and suffixes")
        self.validate_data(x, intervals)
        if (targets.shape != (len(x), 1) or not torch.isfinite(targets).all()
                or not math.isfinite(event_cost) or event_cost < 0):
            raise ValueError("finite task targets and nonnegative event cost required")
        with torch.no_grad():
            state, total = self.prefix(x)
            causal = self.causal_features(state, x[:, self.decision_step], total)
            results = {}
            for name, pulse in (("low", self.low), ("high", self.high)):
                features, events, final = self.suffix(x, state, total, pulse)
                prediction = self.readout((features - self.readout_mean) / self.readout_scale)
                results[name] = {"prediction": prediction, "loss": (prediction - targets).square().mean(1),
                                 "events": events, "final_clock_micros": final.time_micros}
            advantage = results["low"]["loss"] - results["high"]["loss"] - event_cost * (
                results["high"]["events"] - results["low"]["events"])
            return {"causal_features": causal, "advantage": advantage[:, None], "targets": targets,
                    "low": results["low"], "high": results["high"],
                    "decision_clock_micros": state.time_micros, "event_cost": event_cost,
                    "same_horizon": self.horizon}

    def fit_critic(self, teacher, penalty=0.01):
        with torch.no_grad():
            mean, scale = ridge_fit(self.critic, teacher["causal_features"], teacher["advantage"], penalty)
            self.critic_mean.copy_(mean)
            self.critic_scale.copy_(scale)
            self.advantage_scale.copy_(teacher["advantage"].std(unbiased=False).clamp_min(1e-4))


def policy_grid():
    return {
        "always_zero": [],
        "fixed_pulse": [{"kind": "fixed", "value": float(value)} for value in np.linspace(-0.25, 0.25, 9)],
        "input_pulse": [{"kind": "input", "gain": gain, "offset": offset}
                        for gain in (-2.0, 0.0, 2.0) for offset in (-1.0, 0.0, 1.0)],
        "task_advantage": [{"kind": "task", "temperature_multiplier": temperature,
                            "offset_multiplier": offset}
                           for temperature in (0.5, 1.0, 2.0) for offset in (-0.5, 0.0, 0.5)],
    }


def evaluate_policy(model, x, intervals, targets, policy, event_cost):
    if (targets.shape != (len(x), 1) or not torch.isfinite(targets).all()
            or not math.isfinite(event_cost) or event_cost < 0):
        raise ValueError("finite scalar targets and nonnegative event cost required")
    with torch.no_grad():
        result = model.predict(x, intervals, policy)
        mse = float((result["prediction"] - targets).square().mean())
        events = float(result["events"].mean())
        if not math.isfinite(mse + events):
            raise FloatingPointError("nonfinite policy result")
        return {"task_mse": mse, "expected_events": events, "objective": mse + event_cost * events,
                "pulse_min": float(result["pulse"].min()), "pulse_max": float(result["pulse"].max()),
                "pulse_std": float(result["pulse"].std(unbiased=False)),
                "final_clock_micros": result["state"].time_micros}


def gradient_diagnostic(model, x, epsilon=1e-6):
    """FD/AD of the deployed continuous causal map, not a gradient training step."""
    with torch.no_grad():
        state, total = model.prefix(x[:1])
    density = state.density.detach().clone().requires_grad_(True)
    current = x[:1, model.decision_step].detach().clone().requires_grad_(True)
    policy = {"kind": "task", "temperature_multiplier": 1.0, "offset_multiplier": 0.0}

    def mapped(p, u):
        observed = FlowState(p, state.boundary, state.time_micros, state.config)
        return model.boundary(observed, u, total, policy).sum()

    value = mapped(density, current)
    dp, du = torch.autograd.grad(value, (density, current))
    directions = {"population_mass_tangent": torch.zeros_like(density), "current_input": torch.zeros_like(current)}
    cells = torch.topk(density[0, 0, :model.encoder.config.bins], 2).indices
    directions["population_mass_tangent"][0, 0, cells[0]] = 1
    directions["population_mass_tangent"][0, 0, cells[1]] = -1
    directions["current_input"][0, 0] = 1
    results = {}
    with torch.no_grad():
        for name, direction in directions.items():
            if name == "current_input":
                ad = (du * direction).sum()
                fd = (mapped(density, current + epsilon * direction)
                      - mapped(density, current - epsilon * direction)) / (2 * epsilon)
            else:
                ad = (dp * direction).sum()
                fd = (mapped(density + epsilon * direction, current)
                      - mapped(density - epsilon * direction, current)) / (2 * epsilon)
            error = float((ad-fd).abs())
            results[name] = {"ad": float(ad), "fd": float(fd), "absolute_error": error,
                             "passed": error <= 2e-6 * (1 + float(ad.abs()))}
    if not all(row["passed"] for row in results.values()):
        raise FloatingPointError("continuous boundary FD/AD diagnostic failed")
    return {"scope": "causal state/input to sigmoid boundary map; not global optimum or end-to-end training",
            "boundary": float(value.detach()), "epsilon": epsilon, "directions": results}
