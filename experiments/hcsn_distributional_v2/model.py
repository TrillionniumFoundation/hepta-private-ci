"""Content models with a retained finite-state regenerative distribution.

The physical process uses a bounded finite-volume CTMC and Erlang refractory
phases. Its J/G features evaluate its own stationary policy. The input-dependent
analytic boundary is optimal only for the corresponding infinite-domain
Brownian/Erlang problem, not for this grid or the classification objective.
"""

from functools import lru_cache
import math

import torch
from torch import nn
from torch.nn import functional as F

from experiments.continuous_spiking_network.baseline import build_baseline
from experiments.hcsn_free_boundary_v1.model import RegenerativeContentCell, parameter_count
from experiments.hcsn_free_boundary_v1.oracle_torch import free_boundary
from . import distribution_kernel as kernel


PHYSICAL_CHANNELS = 8
PHYSICAL_TIME_SCALE = 0.1
DISTRIBUTION_ARMS = (
    "distribution_free_dual", "distribution_conditional_dual",
    "distribution_free_ordinary", "active_mean_collapse_free_dual",
)
MODEL_NAMES = DISTRIBUTION_ARMS + ("legacy_free", "two_gates", "transformer")


def _raw_positive(value):
    return math.log(math.expm1(value))


def _collapse_active(probability, boundary, grid):
    """Replace only active mass by a two-center mean representation.

    Every refractory phase is preserved. This is a controlled information-loss
    ablation, not the previous v1 pressure/cooldown recurrence.
    """
    n = grid.cells
    active = probability[..., :n]
    mass = active.sum(-1)
    spacing = (boundary - grid.lower) / n
    centers = grid.lower + spacing[..., None] * (
        torch.arange(n, device=probability.device, dtype=probability.dtype) + 0.5)
    mean = (active * centers).sum(-1) / mass.clamp_min(torch.finfo(probability.dtype).tiny)
    mean = torch.where(mass > 0, mean, centers[..., 0])
    coordinate = ((mean - grid.lower) / spacing - 0.5).clamp(0, n - 1)
    left = coordinate.floor().long().clamp(max=n - 2)
    fraction = coordinate - left
    collapsed = torch.zeros_like(active).scatter_add(-1, left[..., None],
                                                   (mass * (1 - fraction))[..., None])
    collapsed = collapsed.scatter_add(-1, (left + 1)[..., None],
                                      (mass * fraction)[..., None])
    return torch.cat((collapsed, probability[..., n:]), -1)


class DistributionalContentCell(nn.Module):
    """Retain all active/phase masses and feed the same state to every gate arm."""

    def __init__(self, width, arm="distribution_free_dual", physical_channels=PHYSICAL_CHANNELS,
                 precompute=True):
        super().__init__()
        if arm not in DISTRIBUTION_ARMS:
            raise ValueError(f"Unknown distribution arm: {arm}")
        self.width, self.arm, self.physical_channels = width, arm, physical_channels
        self.precompute = precompute
        self.grid = kernel.Grid(cells=8, lower=-2.0, refractory_stages=2,
                                fixed_rate=8.1, fixed_terms=21, max_duration=0.36,
                                per_token_chunks=True, max_independent_chunks=1048576)
        self.norm = nn.LayerNorm(width)
        self.drift_input = nn.Linear(width, physical_channels, bias=False)
        self.mu_bias = nn.Parameter(torch.zeros(physical_channels))
        self.raw_sigma = nn.Parameter(torch.zeros(physical_channels))
        self.raw_rho = nn.Parameter(torch.zeros(physical_channels))
        self.raw_K = nn.Parameter(torch.zeros(physical_channels))
        self.raw_reset = nn.Parameter(torch.zeros(physical_channels))
        self.raw_refractory = nn.Parameter(torch.zeros(physical_channels))
        if arm == "distribution_conditional_dual":
            self.raw_boundary_gap = nn.Parameter(torch.full((physical_channels,),
                                                            math.log(0.64 / 3.35)))
            self.raw_boundary_slope = nn.Parameter(torch.zeros(physical_channels))
        self.content_input = nn.Linear(width, width)
        self.content_state = nn.Linear(width, width, bias=False)
        self.gate_input = nn.Linear(width, 2 * width)
        self.gate_state = nn.Linear(width, 2 * width, bias=False)
        # All physical arms see the complete probability and the same local
        # physical coefficients, including cost/discount. Analytic features do
        # not receive information withheld from the ordinary-feature control.
        local_information = self.grid.cells + self.grid.refractory_stages + 7
        self.physical_gate = nn.Linear(physical_channels * local_information,
                                      2 * width, bias=False)
        self.feature_gate = nn.Linear(3 * physical_channels, 2 * width, bias=False)
        self.raw_content_rate = nn.Parameter(torch.full((width,), _raw_positive(1.0)))
        self.raw_decay_rate = nn.Parameter(torch.full((width,), _raw_positive(0.04)))
        self.output = nn.Linear(width, width, bias=False)

    def prepare(self, sequence):
        signal = self.norm(sequence)
        mu = 0.1 + 0.4 * torch.tanh(self.drift_input(signal) + self.mu_bias)
        sigma = 0.3 + 0.3 * self.raw_sigma.sigmoid()
        rho = 0.15 + 0.6 * self.raw_rho.sigmoid()
        cost = 0.35 + 0.35 * self.raw_K.sigmoid()
        reset = -0.3 + 0.4 * self.raw_reset.sigmoid()
        refractory = 0.3 + 0.9 * self.raw_refractory.sigmoid()
        if self.arm == "distribution_conditional_dual":
            gap = 0.01 + 3.99 * (self.raw_boundary_gap + self.raw_boundary_slope * mu).sigmoid()
            boundary = cost + gap
        else:
            # The refractory Laplace transform equals exp(-rho * tau_effective).
            m = self.grid.refractory_stages
            tau_effective = m / rho * torch.log1p(rho * refractory / m)
            boundary = free_boundary(mu, sigma, rho, cost, reset, tau_effective)
        return signal, dict(mu=mu, sigma=sigma, rho=rho, K=cost, r=reset,
                            tau=refractory, boundary=boundary)

    def initial_state(self, batch, anchor):
        return dict(content=anchor.new_zeros(batch, self.width), probability=None,
                    boundary=None)

    def advance(self, x, signal, duration, state, local, prepared=None):
        flow = (kernel.make_flow(local["mu"], local["sigma"], local["boundary"],
                                local["r"], local["tau"], grid=self.grid)
                if prepared is None else prepared["flow"])
        probability = state["probability"]
        if probability is None:
            probability = kernel.initial_probability(flow, initial=0.0)
            old_boundary = local["boundary"]
        else:
            old_boundary = state["boundary"]
        if prepared is None:
            propagated = kernel.step(
                probability, old_boundary, local["mu"], local["sigma"],
                local["boundary"], local["r"], local["tau"],
                PHYSICAL_TIME_SCALE * duration, grid=self.grid,
                reward_slope=1.0, reward_intercept=-local["K"])
        else:
            propagated = dict(
                probability=torch.matmul(probability.unsqueeze(-2), prepared["transition"]).squeeze(-2),
                events=(probability * prepared["event_vector"]).sum(-1),
                reward=(probability * prepared["reward_vector"]).sum(-1))
        probability = propagated["probability"]
        if self.arm == "active_mean_collapse_free_dual":
            probability = _collapse_active(probability, local["boundary"], self.grid)
        if self.arm == "distribution_free_ordinary":
            values = dict(eligible_margin=(probability[..., :self.grid.cells] *
                (flow["boundary"][..., None] - flow["centers"])).sum(-1))
        elif prepared is None:
            values = kernel.finite_generator_values(flow, probability, local["rho"], local["K"])
        else:
            vectors = prepared["values"]
            n = self.grid.cells
            values = dict(J_total=(probability * vectors["J"]).sum(-1),
                          G_total=(probability * vectors["G"]).sum(-1),
                          G_eligible=(probability[..., :n] * vectors["active_G"]).sum(-1),
                          J_phase=(probability[..., n:] * vectors["phase_J"]).sum(-1),
                          eligible_margin=(probability[..., :n] *
                            (flow["boundary"][..., None] - flow["centers"])).sum(-1))
        n = self.grid.cells
        spacing = (local["boundary"] - self.grid.lower) / n
        centers = self.grid.lower + spacing[..., None] * (
            torch.arange(n, device=x.device, dtype=x.dtype) + 0.5)
        active = probability[..., :n]
        eligible = active.sum(-1)
        phase = probability[..., n:].sum(-1)
        active_mean = (active * centers).sum(-1) / eligible.clamp_min(1e-12)
        active_mean = torch.where(eligible > 0, active_mean, torch.zeros_like(active_mean))
        variance = (active * (centers - active_mean[..., None]).square()).sum(-1)
        scaled_margin = torch.tanh(values["eligible_margin"])
        if self.arm == "distribution_free_ordinary":
            features = torch.stack((scaled_margin, torch.tanh(active_mean),
                                    torch.tanh(variance)), -1)
        else:
            j, g = values["J_total"], values["G_total"]
            features = torch.stack((scaled_margin, j / (1 + j.abs()), g / (1 + g.abs())), -1)
        information = torch.cat((probability, torch.stack([
            local[key].expand_as(local["mu"]) for key in
            ("mu", "sigma", "rho", "K", "r", "tau", "boundary")], -1)), -1)
        h = state["content"]
        gates = (self.gate_input(signal) + self.gate_state(h)
                 + self.physical_gate(information.flatten(1))
                 + self.feature_gate(features.flatten(1))).reshape(-1, 2, self.width).sigmoid()
        write_gate, recovery_gate = gates.unbind(1)
        write = -torch.expm1(-F.softplus(self.raw_content_rate) * duration * write_gate)
        retention = torch.exp(-F.softplus(self.raw_decay_rate) * duration * recovery_gate)
        candidate = torch.tanh(self.content_input(signal) + self.content_state(h))
        content = retention * ((1 - write) * h + write * candidate)
        new_state = dict(content=content, probability=probability, boundary=local["boundary"])
        aux = dict(activity=propagated["events"], cost=local["K"] * propagated["events"],
                   modeled_reward=propagated["reward"], margin=values["eligible_margin"],
                   probability=probability, flow_mass=probability.sum(-1),
                   active_mass=eligible, refractory_mass=phase, active_center_variance=variance,
                   boundary=local["boundary"], content=content)
        if self.arm != "distribution_free_ordinary":
            aux.update(continuation=values["J_total"], intervention=values["G_total"],
                       eligible_intervention=values["G_eligible"],
                       refractory_continuation=values["J_phase"])
        return x + self.output(content), new_state, aux

    def forward(self, sequence, dt, state=None):
        signal, parameters = self.prepare(sequence)
        state = self.initial_state(sequence.shape[0], sequence) if state is None else state
        prepared = None
        if self.precompute:
            b = parameters["boundary"]
            first_boundary = b[:, :1] if state["boundary"] is None else state["boundary"][:, None]
            old_boundary = torch.cat((first_boundary, b[:, :-1]), 1)
            prepared = kernel.prepare_operator(
                parameters["mu"], parameters["sigma"], b, parameters["r"], parameters["tau"],
                PHYSICAL_TIME_SCALE * dt[..., None], grid=self.grid, old_boundary=old_boundary,
                rho=None if self.arm == "distribution_free_ordinary" else parameters["rho"],
                K=None if self.arm == "distribution_free_ordinary" else parameters["K"], reward_slope=1.0,
                reward_intercept=-parameters["K"])
        outputs, records = [], []
        for index in range(sequence.shape[1]):
            local = {key: value[:, index] if value.ndim == 3 else value
                     for key, value in parameters.items()}
            local_prepared = None
            if prepared is not None:
                local_prepared = {key: prepared[key][:, index]
                                  for key in ("transition", "event_vector", "reward_vector")}
                local_prepared["flow"] = {key: value[:, index] if torch.is_tensor(value) else value
                                          for key, value in prepared["flow"].items()}
                local_prepared["values"] = (None if prepared["values"] is None else
                    {key: value[:, index] for key, value in prepared["values"].items()})
            output, state, aux = self.advance(sequence[:, index], signal[:, index],
                                              dt[:, index, None], state, local, local_prepared)
            outputs.append(output)
            records.append(aux)
        return torch.stack(outputs, 1), state, {
            key: torch.stack([row[key] for row in records], 1) for key in records[0]}


class DistributionalClassifier(nn.Module):
    def __init__(self, input_dim, output_dim, width=32, depth=1, seed=0,
                 arm="distribution_free_dual"):
        super().__init__()
        self.config = dict(name=arm, input_dim=input_dim, output_dim=output_dim,
                           width=width, depth=depth, seed=seed,
                           physical_channels=PHYSICAL_CHANNELS,
                           physical_time_scale=PHYSICAL_TIME_SCALE,
                           grid_cells=8, refractory_stages=2, lower=-2.0,
                           precomputed_operators=True,
                           uniformization_rate=8.1, uniformization_terms=21,
                           max_physical_substep=0.36, per_token_chunks=True,
                           max_independent_chunks=1048576)
        with torch.random.fork_rng():
            torch.manual_seed(seed)
            self.frontend = nn.Sequential(nn.Linear(input_dim + 2, width),
                                          nn.LayerNorm(width), nn.Tanh())
            self.readout = nn.Linear(width, output_dim)
        with torch.random.fork_rng():
            torch.manual_seed(seed + 100003)
            self.layers = nn.ModuleList([DistributionalContentCell(width, arm)
                                        for _ in range(depth)])

    def initial_state(self, batch, anchor=None):
        anchor = next(self.parameters()) if anchor is None else anchor
        return dict(elapsed=anchor.new_zeros(batch),
                    layers=[layer.initial_state(batch, anchor) for layer in self.layers])

    def forward(self, x, dt, return_sequence=False, return_aux=True, state=None):
        if x.ndim != 3 or dt.shape != x.shape[:2] or x.shape[-1] != self.config["input_dim"]:
            raise ValueError("Expected x[B,T,I] and dt[B,T] with configured I")
        if not bool(torch.isfinite(dt).all()) or bool((dt < 0).any()):
            raise ValueError("dt must be finite and nonnegative")
        state = self.initial_state(x.shape[0], x) if state is None else state
        elapsed = state["elapsed"][:, None] + dt.cumsum(1)
        common = torch.cat((x, dt[..., None] / 32, elapsed[..., None] / 32), -1)
        sequence = self.frontend(common)
        next_states, records = [], []
        for layer, old_state in zip(self.layers, state["layers"], strict=True):
            sequence, next_state, record = layer(sequence, dt, old_state)
            next_states.append(next_state)
            records.append(record)
        logits = self.readout(sequence)
        result = logits if return_sequence else logits[:, -1]
        if not return_aux:
            return result
        aux = dict(records[-1])
        aux["layers"] = records
        aux["state"] = dict(elapsed=elapsed[:, -1], layers=next_states)
        aux["total_activity"] = sum(row["activity"].sum() for row in records)
        aux["total_cost"] = sum(row["cost"].sum() for row in records)
        return result, aux

    def step(self, x, dt, state=None):
        logits, aux = self.forward(x[:, None], dt[:, None], state=state)
        return logits, aux["state"], aux

    def parameter_groups(self):
        groups = {key: [] for key in ("content", "dynamics", "boundary", "reset", "refractory")}
        for name, parameter in self.named_parameters():
            if any(key in name for key in ("raw_K", "raw_boundary")):
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

    def counts(self):
        return dict(total=parameter_count(self), frontend=parameter_count(self.frontend),
                    backbone=parameter_count(self.layers), readout=parameter_count(self.readout),
                    groups={key: sum(p.numel() for _, p in entries)
                            for key, entries in self.parameter_groups().items()})


class _LegacyFreeBackbone(nn.Module):
    def __init__(self, width, depth, hidden):
        super().__init__()
        self.input = nn.Identity() if width == hidden else nn.Linear(width, hidden)
        self.output = nn.Identity() if width == hidden else nn.Linear(hidden, width)
        self.layers = nn.ModuleList([RegenerativeContentCell(hidden, "free", "dual")
                                     for _ in range(depth)])

    def forward(self, sequence, dt):
        sequence = self.input(sequence)
        records = []
        for layer in self.layers:
            sequence, _, record = layer(sequence, dt)
            records.append(record)
        return self.output(sequence), dict(layers=records,
            total_activity=sum(r["activity"].sum() for r in records),
            total_cost=sum(r["cost"].sum() for r in records))


def _backbone(name, width, depth, hidden):
    if name == "legacy_free":
        return _LegacyFreeBackbone(width, depth, hidden)
    return build_baseline(name, width, depth, hidden_width=hidden)


@lru_cache(maxsize=32)
def matched_configuration(name, width, depth):
    with torch.random.fork_rng():
        torch.manual_seed(433)
        target = parameter_count(DistributionalClassifier(1, 1, width, depth).layers)
        candidates = []
        for hidden in range(1, 4 * width + 1):
            count = parameter_count(_backbone(name, width, depth, hidden))
            candidates.append((abs(count - target), count, hidden))
    gap, count, hidden = min(candidates)
    return dict(hidden_width=hidden, target_parameters=target, n_parameters=count,
                relative_gap=gap / target, parameter_padding=False)


class MatchedClassifier(nn.Module):
    def __init__(self, name, input_dim, output_dim, width=32, depth=1, seed=0):
        super().__init__()
        self.config = dict(name=name, input_dim=input_dim, output_dim=output_dim,
                           width=width, depth=depth, seed=seed)
        self.matching = dict(matched_configuration(name, width, depth))
        with torch.random.fork_rng():
            torch.manual_seed(seed)
            self.frontend = nn.Sequential(nn.Linear(input_dim + 2, width), nn.LayerNorm(width), nn.Tanh())
            self.readout = nn.Linear(width, output_dim)
        with torch.random.fork_rng():
            torch.manual_seed(seed + 100003)
            self.backbone = _backbone(name, width, depth, self.matching["hidden_width"])

    def forward(self, x, dt, return_sequence=False, return_aux=True):
        common = torch.cat((x, dt[..., None] / 32, dt.cumsum(1)[..., None] / 32), -1)
        sequence, aux = self.backbone(self.frontend(common), dt)
        logits = self.readout(sequence)
        result = logits if return_sequence else logits[:, -1]
        return (result, aux) if return_aux else result

    def parameter_groups(self):
        return {key: [(f"{key}.{name}", p) for name, p in getattr(self, key).named_parameters()]
                for key in ("frontend", "backbone", "readout")}

    def counts(self):
        return dict(total=parameter_count(self), frontend=parameter_count(self.frontend),
                    backbone=parameter_count(self.backbone), readout=parameter_count(self.readout),
                    matching=self.matching)


def build_model(name, input_dim, output_dim, width=32, depth=1, seed=0):
    if name in DISTRIBUTION_ARMS:
        return DistributionalClassifier(input_dim, output_dim, width, depth, seed, name)
    if name in MODEL_NAMES:
        return MatchedClassifier(name, input_dim, output_dim, width, depth, seed)
    raise ValueError(f"Unknown model: {name}")
