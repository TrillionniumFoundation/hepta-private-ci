"""Matched information, boundary, channel and parameter-freeze controls.

These are new experimental models. The sealed v2 and acceleration modules are
imported read-only. J/G evaluate a fixed regenerative policy; no classification
optimality is inferred. Every physical feature arm receives the same complete
probability and physical coefficients through its ordinary physical gate.
"""

import math

import torch
from torch import nn
from torch.nn import functional as F

from experiments.hcsn_conservative_acceleration_v1 import kernel as accelerated
from experiments.hcsn_distributional_v2 import distribution_kernel as kernel
from experiments.hcsn_distributional_v2 import model as original
from experiments.hcsn_distributional_v2 import stable_probability
from experiments.hcsn_free_boundary_v1.oracle_torch import free_boundary


GROUPS = ("content", "dynamics", "boundary", "reset", "refractory")
PHYSICAL_ARMS = (
    "value_jg", *("freeze_" + group for group in GROUPS),
    "fixed_jg", "learned_jg", "fixed_ordinary", "learned_ordinary", "value_margin", "value_j", "value_g",
    "value_fh", "value_ordinary",
)
BASELINES = ("two_gates", "transformer", "lif_snn", "mamba1")
ARMS = PHYSICAL_ARMS + BASELINES


def first_event_vectors(flow, rho, horizon):
    """F and H for the *next* firing from every active/refractory state.

    Current coefficients and boundary are held fixed for the forecast horizon.
    Existing refractory phases complete normally; the first later firing kills
    the process, so it cannot reset and fire again. A matrix exponential of an
    augmented killed generator integrates its event flux. It is never passed
    to the regenerative unit-mass normalization routine.
    """
    n, stages = flow["grid"].cells, flow["grid"].refractory_stages
    if stages < 1:
        raise ValueError("This registered risk control requires refractory phases")
    rate = flow["grid"].fixed_rate
    augmented_jump = accelerated._jump_matrix(flow, rate)
    size = n + stages
    jump = augmented_jump[..., :size, :size]
    kill_edge = F.pad(flow["exit_rate"][..., None, None] / rate,
                      (n, stages - 1, n - 1, stages))
    identity = torch.eye(size, dtype=jump.dtype, device=jump.device)
    killed = (jump - kill_edge - identity) * rate
    event = F.pad(flow["exit_rate"][..., None], (n - 1, stages))
    rho = torch.broadcast_to(rho, flow["mu"].shape)
    horizon = torch.broadcast_to(horizon, flow["mu"].shape)
    if bool((rho <= 0).any()) or bool((horizon < 0).any()):
        raise ValueError("Positive discount and nonnegative horizon required")
    discounts = torch.stack((torch.zeros_like(rho), rho), -1)
    generators = killed[..., None, :, :] - discounts[..., :, None, None] * identity
    top = torch.cat((generators, event[..., None, :, None].expand(
        *event.shape[:-1], 2, size, 1)), -1)
    bottom = top.new_zeros((*top.shape[:-2], 1, size + 1))
    generators = torch.cat((top, bottom), -2)
    exponential = torch.matrix_exp(generators * horizon[..., None, None, None])
    vectors = exponential[..., :size, size]
    return dict(F=vectors[..., 0, :], H=vectors[..., 1, :])


class ClosureCell(original.DistributionalContentCell):
    """Keep the regenerative law and change one declared modeling component."""

    def __init__(self, width, arm):
        super().__init__(width, arm="distribution_free_dual", precompute=True)
        self.control_arm = arm
        if arm.startswith("learned_"):
            # b = .7 + 2.6 sigmoid(a); a starts at the same fixed b=1.3.
            self.raw_threshold = nn.Parameter(torch.full(
                (self.physical_channels,), math.log(0.6 / 2.0)))
        if arm.startswith("fixed_"):
            self.register_buffer("fixed_threshold", torch.full((self.physical_channels,), 1.3))

    def prepare(self, sequence):
        signal = self.norm(sequence)
        mu = 0.1 + 0.4 * torch.tanh(self.drift_input(signal) + self.mu_bias)
        sigma = 0.3 + 0.3 * self.raw_sigma.sigmoid()
        rho = 0.15 + 0.6 * self.raw_rho.sigmoid()
        cost = 0.35 + 0.35 * self.raw_K.sigmoid()
        reset = -0.3 + 0.4 * self.raw_reset.sigmoid()
        refractory = 0.3 + 0.9 * self.raw_refractory.sigmoid()
        if self.control_arm.startswith("fixed_"):
            boundary = self.fixed_threshold.expand_as(mu)
        elif self.control_arm.startswith("learned_"):
            boundary = (0.7 + 2.6 * self.raw_threshold.sigmoid()).expand_as(mu)
        else:
            stages = self.grid.refractory_stages
            delay = stages / rho * torch.log1p(rho * refractory / stages)
            boundary = free_boundary(mu, sigma, rho, cost, reset, delay)
        return signal, dict(mu=mu, sigma=sigma, rho=rho, K=cost, r=reset,
                            tau=refractory, boundary=boundary)

    def feature_coordinates(self, margin, j, g, mean, variance, risk):
        m = torch.tanh(margin)
        j, g = j / (1 + j.abs()), g / (1 + g.abs())
        if self.control_arm == "value_margin":
            return torch.stack((m, m.square(), m.pow(3)), -1)
        if self.control_arm == "value_j":
            return torch.stack((m, j, j.square()), -1)
        if self.control_arm == "value_g":
            return torch.stack((m, g, g.square()), -1)
        if self.control_arm == "value_fh":
            return torch.stack((m, risk["F"], risk["H"]), -1)
        if self.control_arm.endswith("_ordinary"):
            return torch.stack((m, torch.tanh(mean), torch.tanh(variance)), -1)
        return torch.stack((m, j, g), -1)

    def forward(self, sequence, dt, state=None):
        signal, params = self.prepare(sequence)
        state = self.initial_state(len(sequence), sequence) if state is None else state
        boundary = params["boundary"]
        first = boundary[:, :1] if state["boundary"] is None else state["boundary"][:, None]
        old = torch.cat((first, boundary[:, :-1]), 1)
        need_values = (self.control_arm not in ("value_margin", "value_fh")
                       and not self.control_arm.endswith("_ordinary"))
        prepared = accelerated.prepare_operator(
            params["mu"], params["sigma"], boundary, params["r"], params["tau"],
            original.PHYSICAL_TIME_SCALE * dt[..., None], grid=self.grid,
            old_boundary=old, rho=params["rho"] if need_values else None,
            K=params["K"] if need_values else None, reward_slope=1.0,
            reward_intercept=-params["K"])
        risk_vectors = None
        if self.control_arm == "value_fh":
            risk_vectors = first_event_vectors(prepared["flow"], params["rho"],
                original.PHYSICAL_TIME_SCALE * dt[..., None])
        outputs, records = [], []
        n = self.grid.cells
        for index in range(sequence.shape[1]):
            local = {key: value[:, index] if value.ndim == 3 else value
                     for key, value in params.items()}
            probability = state["probability"]
            centers = prepared["flow"]["centers"][:, index]
            if probability is None:
                flow = {key: value[:, index] if torch.is_tensor(value) else value
                        for key, value in prepared["flow"].items()}
                probability = kernel.initial_probability(flow, initial=0.0)
            propagated = stable_probability.advance_probability(
                probability, prepared["transition"][:, index],
                operator_kind=stable_probability.REGENERATIVE_PROBABILITY,
                event_vector=prepared["event_vector"][:, index],
                reward_vector=prepared["reward_vector"][:, index])
            probability = propagated["probability"]
            active = probability[..., :n]
            eligible = active.sum(-1)
            mean = (active * centers).sum(-1) / eligible.clamp_min(1e-12)
            mean = torch.where(eligible > 0, mean, torch.zeros_like(mean))
            variance = (active * (centers - mean[..., None]).square()).sum(-1)
            margin = (active * (local["boundary"][..., None] - centers)).sum(-1)
            j, g = torch.zeros_like(margin), torch.zeros_like(margin)
            if need_values:
                j = (probability * prepared["values"]["J"][:, index]).sum(-1)
                g = (probability * prepared["values"]["G"][:, index]).sum(-1)
            risk = (None if risk_vectors is None else {
                key: (probability * value[:, index]).sum(-1)
                for key, value in risk_vectors.items()})
            features = self.feature_coordinates(margin, j, g, mean, variance, risk)
            information = torch.cat((probability, torch.stack([
                local[key].expand_as(local["mu"]) for key in
                ("mu", "sigma", "rho", "K", "r", "tau", "boundary")], -1)), -1)
            h, duration = state["content"], dt[:, index, None]
            gates = (self.gate_input(signal[:, index]) + self.gate_state(h)
                     + self.physical_gate(information.flatten(1))
                     + self.feature_gate(features.flatten(1))).reshape(-1, 2, self.width).sigmoid()
            write_gate, recovery_gate = gates.unbind(1)
            write = -torch.expm1(-F.softplus(self.raw_content_rate) * duration * write_gate)
            retention = torch.exp(-F.softplus(self.raw_decay_rate) * duration * recovery_gate)
            candidate = torch.tanh(self.content_input(signal[:, index]) + self.content_state(h))
            content = retention * ((1 - write) * h + write * candidate)
            state = dict(content=content, probability=probability, boundary=local["boundary"])
            outputs.append(sequence[:, index] + self.output(content))
            diagnostics = propagated["diagnostics"]
            record = dict(probability=probability, boundary=local["boundary"],
                          activity=propagated["events"], cost=local["K"] * propagated["events"],
                          refractory_mass=probability[..., n:].sum(-1), margin=margin,
                          feature_coordinates=features,
                          normalization_l1_correction=diagnostics["actual_l1_correction"],
                          raw_probability_mass_defect=(diagnostics["pre_projection_mass"] - 1).abs())
            if risk is not None:
                record.update(next_first_event_F=risk["F"], next_first_event_H=risk["H"])
            if need_values:
                record.update(policy_J=j, policy_G=g)
            records.append(record)
        return torch.stack(outputs, 1), state, {
            key: torch.stack([row[key] for row in records], 1) for key in records[0]}


class ClosureClassifier(original.DistributionalClassifier):
    def __init__(self, arm, input_dim=64, output_dim=8, width=32, depth=1, seed=0):
        super().__init__(input_dim, output_dim, width, depth, seed)
        with torch.random.fork_rng():
            torch.manual_seed(seed + 100003)
            self.layers = nn.ModuleList([ClosureCell(width, arm) for _ in range(depth)])
        self.config.update(name=arm, study="hcsn_blocker_closure_v1", feature_basis=3)
        self.frozen_group = arm.removeprefix("freeze_") if arm.startswith("freeze_") else None
        if self.frozen_group is not None:
            for _, parameter in self.parameter_groups()[self.frozen_group]:
                parameter.requires_grad_(False)

    def parameter_groups(self):
        groups = {key: [] for key in GROUPS}
        for name, parameter in self.named_parameters():
            if "raw_K" in name or "raw_threshold" in name:
                key = "boundary"
            elif "raw_reset" in name:
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
        parts = {key: sum(p.numel() for p in getattr(self, key).parameters())
                 for key in ("frontend", "layers", "readout")}
        return dict(total=sum(parts.values()), backbone=parts.pop("layers"), **parts,
            trainable=sum(p.numel() for p in self.parameters() if p.requires_grad),
            groups={key: sum(p.numel() for _, p in entries)
                    for key, entries in self.parameter_groups().items()}, frozen_group=self.frozen_group)


def build(arm, input_dim=64, output_dim=8, width=32, depth=1, seed=0):
    if arm in PHYSICAL_ARMS:
        return ClosureClassifier(arm, input_dim, output_dim, width, depth, seed)
    if arm in BASELINES:
        model = original.MatchedClassifier(arm, input_dim, output_dim, width, depth, seed)
        if arm == "transformer":
            # Refine the *active* FFN width, not a padding tensor, so the whole
            # family satisfies the stricter max-minus-min 3% size contract.
            hidden = model.matching["hidden_width"]
            target = model.matching["target_parameters"]
            old_count = sum(p.numel() for p in model.backbone.parameters())
            ffn_width = max(1, round(4 * hidden + (target - old_count) / (depth * (2 * hidden + 1))))
            with torch.random.fork_rng():
                torch.manual_seed(seed + 370003)
                for block in model.backbone.blocks:
                    block.ffn = nn.Sequential(nn.Linear(hidden, ffn_width), nn.GELU(),
                                              nn.Linear(ffn_width, hidden))
            count = sum(p.numel() for p in model.backbone.parameters())
            model.matching.update(ffn_width=ffn_width, n_parameters=count,
                relative_gap=abs(count - target) / target, parameter_padding=False)
            model.config.update(ffn_width=ffn_width, ffn_initialization_seed=seed + 370003)
        return model
    raise ValueError("Unknown registered content arm: " + arm)
