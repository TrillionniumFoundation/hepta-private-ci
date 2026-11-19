"""Jointly trained content and regenerative-boundary sequence model.

The stationary scalar boundary is exact for the contract in ``oracle.py``.
The neural recurrence is a frozen-local, mean-state approximation: coefficients
and boundary are frozen per observation; first-hit mass resets at interval end;
cooldown is propagated as a first moment. It is NOT an exact moving-boundary
renewal process or a reproduction of the complete He--Xiong credit model.
"""

import math

import torch
from torch import nn
from torch.nn import functional as F

from .oracle_torch import first_passage_terms, free_boundary, kappa


def _positive_raw(value):
    return math.log(math.expm1(value))


def parameter_count(model):
    return sum(parameter.numel() for parameter in model.parameters()
               if parameter.requires_grad)


class RegenerativeContentCell(nn.Module):
    """Preserve content with a policy-envelope / intervention-obstacle value pair.

    These are regenerative control values, not literal financial Call/Put
    prices. First-hit risk separately drives the reset/refractory dynamics.
    """

    def __init__(self, width, boundary_mode="free", channels="dual"):
        super().__init__()
        if boundary_mode not in {"fixed", "direct", "free"}:
            raise ValueError("boundary_mode must be fixed, direct, or free")
        if channels not in {"margin", "continuation", "dual", "ordinary"}:
            raise ValueError("channels must be margin, continuation, dual, or ordinary")
        self.width, self.boundary_mode, self.channels = width, boundary_mode, channels
        self.norm = nn.LayerNorm(width)
        self.drift_input = nn.Linear(width, width, bias=False)
        self.mu_bias = nn.Parameter(torch.full((width,), 0.35))
        self.raw_sigma = nn.Parameter(torch.full((width,), _positive_raw(0.45)))
        rho_initial = torch.full((width,), _positive_raw(0.3))
        if channels == "margin" and boundary_mode != "free":
            self.register_buffer("raw_rho", rho_initial)
        else:
            self.raw_rho = nn.Parameter(rho_initial)
        # K is bounded below the fixed control's threshold. Reset remains < K.
        self.raw_K = nn.Parameter(torch.full((width,), math.log(9 / 8)))
        self.raw_reset_gap = nn.Parameter(torch.full((width,), _positive_raw(0.4)))
        self.raw_refractory = nn.Parameter(torch.full((width,), _positive_raw(0.3)))
        if boundary_mode == "direct":
            self.raw_boundary_gap = nn.Parameter(
                torch.full((width,), _positive_raw(0.9)))
        self.register_buffer("fixed_boundary", torch.full((width,), 1.5))
        self.content_input = nn.Linear(width, width)
        self.content_state = nn.Linear(width, width, bias=False)
        self.gate_input = nn.Linear(width, 2 * width)
        self.gate_state = nn.Linear(width, 2 * width, bias=False)
        feature_count = {"margin": 1, "continuation": 2, "dual": 3, "ordinary": 3}[channels]
        self.feature_weights = nn.Parameter(torch.full((2, feature_count, width), 0.2))
        self.raw_content_rate = nn.Parameter(torch.full((width,), _positive_raw(1.0)))
        self.raw_decay_rate = nn.Parameter(torch.full((width,), _positive_raw(0.04)))
        self.output = nn.Linear(width, width, bias=False)

    def prepare(self, sequence):
        """Batch all local boundary solves; input dependence is causal."""
        signal = self.norm(sequence)
        mu = 0.15 + 0.5 * torch.tanh(self.drift_input(signal) + self.mu_bias)
        sigma = 0.15 + F.softplus(self.raw_sigma)
        rho = 0.1 + F.softplus(self.raw_rho)
        cost = 0.15 + 0.85 * self.raw_K.sigmoid()
        reset = cost - 0.2 - F.softplus(self.raw_reset_gap)
        refractory = 0.02 + F.softplus(self.raw_refractory)
        if self.boundary_mode == "free":
            boundary = free_boundary(mu, sigma, rho, cost, reset, refractory)
        elif self.boundary_mode == "direct":
            boundary = (cost + F.softplus(self.raw_boundary_gap)).expand_as(mu)
        else:
            boundary = self.fixed_boundary.expand_as(mu)
        return signal, dict(mu=mu, sigma=sigma, rho=rho, K=cost, r=reset,
                            tau=refractory, boundary=boundary)

    def initial_state(self, batch, anchor):
        return {key: anchor.new_zeros(batch, self.width)
                for key in ("content", "voltage", "refractory", "event")}

    def advance(self, x, signal, duration, state, local):
        """One continuous mean-state update, without Bernoulli sampling."""
        h, voltage = state["content"], state["voltage"]
        mu, sigma, rho, cost, reset, tau, boundary = (
            local[key] for key in ("mu", "sigma", "rho", "K", "r", "tau", "boundary"))
        active_time = (duration - state["refractory"]).clamp_min(0)
        distance = boundary - voltage
        cdf, survival, image = first_passage_terms(distance, mu, sigma, active_time)
        # A zero-duration observation does not advance or reset any state.
        event = torch.where(active_time > 0, cdf, torch.zeros_like(voltage))
        survival = torch.where(active_time > 0, survival, torch.ones_like(voltage))
        image = torch.where(active_time > 0, image, torch.zeros_like(voltage))
        next_voltage = ((voltage + mu * active_time) * survival
                        - 2 * distance.clamp_min(0) * image + reset * event)
        # Fixed/direct controls get their OWN policy value, not optimal labels.
        kap = kappa(mu, sigma, rho)
        log_q = -rho * tau - kap * (boundary - reset)
        at_boundary = (boundary - cost) / (-torch.expm1(log_q))
        intervention = voltage - cost + log_q.exp() * at_boundary
        continuation = torch.where(
            voltage < boundary,
            torch.exp(kap * (voltage - boundary).clamp_max(0)) * at_boundary,
            intervention)
        scaled_margin = torch.tanh(distance / (sigma * (duration + 0.1).sqrt()))
        scaled_value = continuation / (1 + continuation.abs())
        scaled_intervention = intervention / (1 + intervention.abs())
        if self.channels == "ordinary":
            # Same state, time, and learned parameters; no value/first-hit gate features.
            features = torch.stack((scaled_margin, torch.tanh((voltage - reset) / (1 + rho * duration)),
                                    torch.tanh(mu * duration / sigma)), dim=-2)
        else:
            features = [scaled_margin]
            if self.channels != "margin":
                features.append(scaled_value)
            if self.channels == "dual":
                features.append(scaled_intervention)
            features = torch.stack(features, dim=-2)
        analytic_gates = torch.einsum("bsw,gsw->bgw", features, self.feature_weights)
        base_gates = (self.gate_input(signal) + self.gate_state(h)).reshape(
            h.shape[0], 2, self.width)
        write_gate, recovery_gate = (base_gates + analytic_gates).sigmoid().unbind(1)
        write = -torch.expm1(-F.softplus(self.raw_content_rate) * duration * write_gate)
        retention = torch.exp(-F.softplus(self.raw_decay_rate) * duration * recovery_gate)
        candidate = torch.tanh(self.content_input(signal) + self.content_state(h))
        content = retention * ((1 - write) * h + write * candidate)
        cooldown = ((1 - event) * (state["refractory"] - duration).clamp_min(0)
                    + event * tau)
        next_state = dict(content=content, voltage=next_voltage, refractory=cooldown,
                          event=torch.where(duration > 0, event, state["event"]))
        aux = dict(activity=event, event_probability=event, cost=cost * event,
                   continuation=continuation, intervention=intervention,
                   continuation_gap=continuation - intervention,
                   margin=distance, boundary=boundary,
                   voltage=next_voltage, content=content, refractory=cooldown,
                   mu=mu, sigma=sigma.expand_as(mu), K=cost.expand_as(mu),
                   r=reset.expand_as(mu), tau=tau.expand_as(mu),
                   write=write, retention=retention)
        return x + self.output(content), next_state, aux

    def forward(self, sequence, dt, state=None):
        signal, parameters = self.prepare(sequence)
        state = self.initial_state(sequence.shape[0], sequence) if state is None else state
        outputs, records = [], []
        for index in range(sequence.shape[1]):
            local = {key: value[:, index] if value.ndim == 3 else value
                     for key, value in parameters.items()}
            output, state, aux = self.advance(sequence[:, index], signal[:, index],
                                              dt[:, index, None], state, local)
            outputs.append(output)
            records.append(aux)
        return torch.stack(outputs, 1), state, {
            key: torch.stack([row[key] for row in records], 1) for key in records[0]}


class HCSNClassifier(nn.Module):
    """Shared frontend/readout with per-layer trainable regenerative content cells.

    ``context`` optionally supplies public budget/deadline features to EVERY arm.
    It must never contain target labels or a privileged simulator state.
    """

    def __init__(self, input_dim, output_dim, width=32, depth=1,
                 boundary_mode="free", channels="dual", seed=0, context_dim=0):
        super().__init__()
        if min(input_dim, output_dim, width, depth) < 1 or context_dim < 0:
            raise ValueError("Model dimensions must be positive; context_dim nonnegative")
        self.config = dict(input_dim=input_dim, output_dim=output_dim, width=width,
                           depth=depth, boundary_mode=boundary_mode, channels=channels,
                           seed=seed, context_dim=context_dim)
        with torch.random.fork_rng():
            torch.manual_seed(seed)
            self.frontend = nn.Sequential(nn.Linear(input_dim + 2 + context_dim, width),
                                          nn.LayerNorm(width), nn.Tanh())
            self.readout = nn.Linear(width, output_dim)
        with torch.random.fork_rng():
            torch.manual_seed(seed + 100003)
            self.layers = nn.ModuleList([
                RegenerativeContentCell(width, boundary_mode, channels) for _ in range(depth)])

    def _encode(self, x, dt, elapsed, context):
        if context is None:
            if self.config["context_dim"]:
                raise ValueError("Configured public context is required")
            context = x.new_empty(*x.shape[:-1], 0)
        expected = (*x.shape[:-1], self.config["context_dim"])
        if tuple(context.shape) != expected:
            raise ValueError(f"context must have shape {expected}")
        common = torch.cat((x, dt.unsqueeze(-1) / 32,
                            elapsed.unsqueeze(-1) / 32, context), -1)
        return self.frontend(common)

    def initial_state(self, batch, anchor=None):
        anchor = next(self.parameters()) if anchor is None else anchor
        return dict(elapsed=anchor.new_zeros(batch),
                    layers=[layer.initial_state(batch, anchor) for layer in self.layers])

    def forward(self, x, dt, return_sequence=False, return_aux=True, context=None,
                state=None):
        if x.ndim != 3 or x.shape[1] == 0 or x.shape[-1] != self.config["input_dim"]:
            raise ValueError("x must be [batch, nonempty_time, configured_input_dim]")
        if dt.shape != x.shape[:2] or not bool(torch.isfinite(dt).all()) or bool((dt < 0).any()):
            raise ValueError("dt must be finite nonnegative [batch,time]")
        state = self.initial_state(x.shape[0], x) if state is None else state
        elapsed = state["elapsed"][:, None] + dt.cumsum(1)
        sequence = self._encode(x, dt, elapsed, context)
        layer_states, layer_aux = [], []
        for layer, old_state in zip(self.layers, state["layers"], strict=True):
            sequence, new_state, aux = layer(sequence, dt, old_state)
            layer_states.append(new_state)
            layer_aux.append(aux)
        logits = self.readout(sequence)
        result = logits if return_sequence else logits[:, -1]
        if not return_aux:
            return result
        aux = dict(layer_aux[-1])
        aux["layers"] = layer_aux
        aux["state"] = dict(elapsed=elapsed[:, -1], layers=layer_states)
        aux["total_activity"] = sum(record["activity"].sum() for record in layer_aux)
        aux["total_cost"] = sum(record["cost"].sum() for record in layer_aux)
        return result, aux

    def step(self, x, dt, state=None, context=None):
        if x.ndim != 2 or dt.shape != x.shape[:1]:
            raise ValueError("step expects x[batch,features], dt[batch]")
        logits, aux = self.forward(x[:, None], dt[:, None], context=(
            None if context is None else context[:, None]), state=state)
        return logits, aux["state"], aux

    def parameter_groups(self):
        """Disjoint groups used for task-gradient and actual-update evidence."""
        groups = {key: [] for key in ("content", "dynamics", "boundary", "reset", "refractory")}
        for name, parameter in self.named_parameters():
            if "raw_K" in name or "raw_boundary_gap" in name:
                key = "boundary"
            elif "raw_reset_gap" in name:
                key = "reset"
            elif "raw_refractory" in name:
                key = "refractory"
            elif any(part in name for part in ("drift_input", "mu_bias", "raw_sigma", "raw_rho")):
                key = "dynamics"
            else:
                key = "content"
            groups[key].append((name, parameter))
        return groups

    def counts(self):
        return dict(total=parameter_count(self), frontend=parameter_count(self.frontend),
                    backbone=parameter_count(self.layers), readout=parameter_count(self.readout),
                    groups={key: sum(parameter.numel() for _, parameter in entries)
                            for key, entries in self.parameter_groups().items()})


def simulate_event_interval(voltage, refractory, mu, sigma, boundary, reset, tau,
                            dt, noise):
    """Hard-event Brownian grid reference with actual reset and deterministic hold.

    ``noise`` supplies independent standard normal increments [substeps,...].
    An active start already at/above the boundary fires before propagation.
    Subsequent crossing/reset occurs at grid endpoints and has discretization
    bias. A zero-duration call is a neural-API no-op, unlike the scalar oracle's
    initial-hit probability atom. This is not the differentiable training path.
    """
    if noise.ndim != voltage.ndim + 1 or noise.shape[1:] != voltage.shape or noise.shape[0] < 1:
        raise ValueError("noise must be [positive_substeps,*voltage.shape]")
    if bool((dt < 0).any()) or bool((tau < 0).any()) or bool((reset >= boundary).any()):
        raise ValueError("Require nonnegative durations and reset below boundary")
    step = dt / noise.shape[0]
    initial_hit = (dt > 0) & (refractory <= 0) & (voltage >= boundary)
    voltage = torch.where(initial_hit, reset, voltage)
    refractory = torch.where(initial_hit, tau, refractory)
    events = initial_hit.to(voltage.dtype)
    for increment in noise:
        active = (step - refractory).clamp_min(0)
        refractory = (refractory - step).clamp_min(0)
        proposal = voltage + mu * active + sigma * active.sqrt() * increment
        hit = (active > 0) & (proposal >= boundary)
        voltage = torch.where(hit, reset, proposal)
        refractory = torch.where(hit, tau, refractory)
        events = events + hit.to(events.dtype)
    return dict(voltage=voltage, refractory=refractory, events=events)
