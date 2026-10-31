"""Joint content/reward/dynamics model with an explicit observation chronology.

This is a finite probability-flow recurrent network. Its learned local reward
is an inductive bias shaped by the supervised objective; it is not a proof of
globally task-optimal stopping. All model variants see the same physical state.
"""

import math

import torch
from torch import nn
from torch.nn import functional as F

from experiments.hcsn_distributional_v2 import distribution_kernel as finite
from experiments.hcsn_distributional_v2.stable_probability import (
    REGENERATIVE_PROBABILITY, advance_probability,
)
from .operators import prepare_interval, reward_boundary


PARAMETERS = ("mu", "sigma", "rho", "K", "r", "tau", "slope", "boundary")


class RewardFlowCell(nn.Module):
    def __init__(self, width, physical=2, boundary="value", channels="dual"):
        super().__init__()
        if boundary not in ("value", "fixed", "direct", "stop_gradient"):
            raise ValueError("Unknown boundary policy")
        if channels not in ("dual", "single", "ordinary"):
            raise ValueError("Unknown channel feature policy")
        self.width, self.physical = width, physical
        self.boundary_mode, self.channels = boundary, channels
        self.grid = finite.Grid(cells=8, lower=-2.0, refractory_stages=2,
                                fixed_rate=8.1, fixed_terms=21, max_duration=0.36,
                                per_token_chunks=True, max_independent_chunks=1048576)
        self.norm = nn.LayerNorm(width)
        self.drift_input = nn.Linear(width, physical, bias=False)
        self.reward_input = nn.Linear(width, physical, bias=False)
        for name in ("mu_bias", "raw_sigma", "raw_rho", "raw_K", "raw_reset", "raw_refractory", "raw_reward"):
            self.register_parameter(name, nn.Parameter(torch.zeros(physical)))
        with torch.no_grad():
            anchor = torch.zeros(physical)
            fixed = reward_boundary(anchor + .1, anchor + .45, anchor + .45,
                                    anchor + .525, anchor - .1, anchor + .75, anchor - .0275)
        self.register_buffer("fixed_boundary", fixed)
        if boundary == "direct":
            self.raw_threshold = nn.Parameter(torch.zeros(physical))
        self.content_input = nn.Linear(width, width)
        self.content_state = nn.Linear(width, width, bias=False)
        self.gate_input = nn.Linear(width, 2 * width)
        self.gate_state = nn.Linear(width, 2 * width, bias=False)
        self.physical_gate = nn.Linear(physical * (self.grid.cells + self.grid.refractory_stages + 8),
                                       2 * width, bias=False)
        self.feature_gate = nn.Linear(3 * physical, 2 * width, bias=False)
        self.raw_decay = nn.Parameter(torch.full((width,), math.log(math.expm1(.04))))
        self.output = nn.Linear(width, width, bias=False)

    def coefficients(self, signal):
        mu = .1 + .4 * torch.tanh(self.drift_input(signal) + self.mu_bias)
        sigma = (.3 + .3 * self.raw_sigma.sigmoid()).expand_as(mu)
        rho = (.15 + .6 * self.raw_rho.sigmoid()).expand_as(mu)
        cost = (.35 + .35 * self.raw_K.sigmoid()).expand_as(mu)
        reset = (-.3 + .4 * self.raw_reset.sigmoid()).expand_as(mu)
        tau = (.3 + .9 * self.raw_refractory.sigmoid()).expand_as(mu)
        slope = -.005 - .045 * (self.reward_input(signal) + self.raw_reward).sigmoid()
        if self.boundary_mode == "fixed":
            boundary = self.fixed_boundary.expand_as(mu)
        elif self.boundary_mode == "direct":
            boundary = (self.fixed_boundary + .35 * self.raw_threshold.tanh()).expand_as(mu)
        else:
            boundary = reward_boundary(mu, sigma, rho, cost, reset, tau, slope)
            if self.boundary_mode == "stop_gradient":
                boundary = boundary.detach()
        return dict(mu=mu, sigma=sigma, rho=rho, K=cost, r=reset, tau=tau,
                    slope=slope, boundary=boundary)

    def initial_state(self, batch, anchor):
        signal = anchor.new_zeros(batch, self.width)
        parameters = self.coefficients(signal)
        flow = finite.make_flow(*(parameters[k] for k in ("mu", "sigma", "boundary", "r", "tau")), self.grid)
        return dict(content=signal, signal=signal, recovery=torch.full_like(signal, .5), parameters=parameters,
                    probability=finite.initial_probability(flow, 0.0))

    def forward(self, sequence, dt, observed, state=None):
        batch, length, _ = sequence.shape
        state = self.initial_state(batch, sequence) if state is None else state
        # Last-observation carry makes a missing observation different from x=0.
        signal = self.norm(sequence)
        indices = torch.arange(1, length + 1, device=sequence.device)[None].expand(batch, -1)
        indices = torch.where(observed, indices, torch.zeros_like(indices)).cummax(1).values
        extended = torch.cat((state["signal"][:, None], signal), 1)
        held_signal = extended.gather(1, indices[..., None].expand(-1, -1, self.width))
        fresh = self.coefficients(signal)
        current, previous = {}, {}
        for key in PARAMETERS:
            initial = state["parameters"][key][:, None]
            candidate = torch.cat((initial, fresh[key]), 1)
            current[key] = candidate.gather(1, indices[..., None].expand(-1, -1, self.physical))
            previous[key] = torch.cat((initial, current[key][:, :-1]), 1)
        operator = prepare_interval(previous, current, dt[..., None], self.grid)
        probability, content, held_recovery = state["probability"], state["content"], state["recovery"]
        output, records = [], []
        n = self.grid.cells
        for index in range(length):
            transition = operator["transition"][:, index]
            event_cost = (probability * operator["cost"][:, index]).sum(-1)
            propagated = advance_probability(
                probability, transition, operator_kind=REGENERATIVE_PROBABILITY,
                event_vector=operator["events"][:, index], reward_vector=operator["reward"][:, index])
            probability = propagated["probability"]
            values = {k: v[:, index] for k, v in operator["values"].items()}
            centers = operator["flow"]["centers"][:, index]
            local = {k: v[:, index] for k, v in current.items()}
            active = probability[..., :n]
            mass = active.sum(-1)
            mean = (active * centers).sum(-1) / mass.clamp_min(1e-8)
            variance = (active * (centers - mean[..., None]).square()).sum(-1)
            margin = (active * (local["boundary"][..., None] - centers)).sum(-1)
            j = (probability * values["J"]).sum(-1)
            g = (probability * values["G"]).sum(-1)
            squash_j, squash_g = j / (1 + j.abs()), g / (1 + g.abs())
            if self.channels == "dual":
                features = torch.stack((margin.tanh(), squash_j, squash_g), -1)
            elif self.channels == "single":
                # Same active parameter count: one value and its nonlinear basis.
                features = torch.stack((margin.tanh(), squash_j, squash_j.square()), -1)
            else:
                features = torch.stack((margin.tanh(), mean.tanh(), variance.tanh()), -1)
            information = torch.cat((probability, torch.stack([local[k] for k in PARAMETERS], -1)), -1)
            # Complete the elapsed interval before consuming its new observation.
            keep = torch.exp(-F.softplus(self.raw_decay) * dt[:, index, None] * held_recovery)
            content = keep * content
            gates = (self.gate_input(held_signal[:, index]) + self.gate_state(content)
                     + self.physical_gate(information.flatten(1))
                     + self.feature_gate(features.flatten(1))).reshape(batch, 2, self.width).sigmoid()
            write, recovery = gates.unbind(1)
            write = write * observed[:, index, None]
            held_recovery = torch.where(observed[:, index, None], recovery, held_recovery)
            candidate = torch.tanh(self.content_input(held_signal[:, index]) + self.content_state(content))
            content = (1 - write) * content + write * candidate
            output.append(held_signal[:, index] + self.output(content))
            records.append(dict(activity=propagated["events"], reward=propagated["reward"],
                cost=event_cost, boundary=local["boundary"],
                value=j, intervention=g, probability=probability,
                normalization=propagated["diagnostics"]["actual_l1_correction"]))
        # Materialize retained slices: a last-token view would keep a whole
        # sequence storage alive during inference. Clones preserve BPTT graphs.
        new_state = dict(content=content, signal=held_signal[:, -1].clone(), recovery=held_recovery, probability=probability,
                         parameters={k: v[:, -1].clone() for k, v in current.items()})
        return torch.stack(output, 1), new_state, {
            key: torch.stack([row[key] for row in records], 1) for key in records[0]}


class Classifier(nn.Module):
    def __init__(self, input_dim=64, output_dim=8, width=16, seed=0,
                 boundary="value", channels="dual", physical=2):
        super().__init__()
        self.config = dict(input_dim=input_dim, output_dim=output_dim, width=width, seed=seed,
                           boundary=boundary, channels=channels, physical=physical, seconds_per_dt=1.0)
        with torch.random.fork_rng():
            torch.manual_seed(seed)
            self.frontend = nn.Sequential(nn.Linear(input_dim + 3, width), nn.LayerNorm(width), nn.Tanh())
            self.readout = nn.Linear(width, output_dim)
            self.cell = RewardFlowCell(width, physical, boundary, channels)

    def forward(self, x, dt, observed=None, state=None, return_aux=False):
        if x.ndim != 3 or dt.shape != x.shape[:2] or x.shape[-1] != self.config["input_dim"]:
            raise ValueError("Expected x[B,T,input_dim], dt[B,T]")
        if not bool(torch.isfinite(x).all() and torch.isfinite(dt).all()) or bool((dt < 0).any()):
            raise ValueError("Finite observations and nonnegative physical seconds required")
        observed = torch.ones_like(dt, dtype=torch.bool) if observed is None else observed.bool()
        elapsed = dt.cumsum(1) + (0 if state is None else state["elapsed"][:, None])
        common = torch.cat((x, dt[..., None], elapsed[..., None] / 3.2, observed[..., None]), -1)
        sequence = self.frontend(common)
        sequence, hidden, aux = self.cell(sequence, dt, observed, None if state is None else state["cell"])
        logits = self.readout(sequence)
        if not return_aux:
            return logits
        aux["state"] = dict(elapsed=elapsed[:, -1].clone(), cell=hidden)
        return logits, aux

    def parameter_groups(self):
        groups = {key: [] for key in ("content", "dynamics", "boundary", "reset", "refractory")}
        for name, parameter in self.named_parameters():
            if any(key in name for key in ("raw_K", "raw_threshold", "reward_input", "raw_reward")):
                group = "boundary"
            elif "raw_reset" in name:
                group = "reset"
            elif "raw_refractory" in name:
                group = "refractory"
            elif any(key in name for key in ("drift_input", "mu_bias", "raw_sigma", "raw_rho")):
                group = "dynamics"
            else:
                group = "content"
            groups[group].append((name, parameter))
        return groups

    def freeze(self, group):
        for _, parameter in self.parameter_groups()[group]:
            parameter.requires_grad_(False)
