"""Post-baseline, equal-capacity analytic-feature replacement experiment.

All seven arms retain the same full physical state and coefficients. The ladder
replaces ordinary summaries with margin, continuation and genuine first-event
probability. It therefore measures feature engineering, not hidden-information
removal. No frozen v2 source is changed by this separate model family.
"""

import math

import torch
from torch import nn
from torch.nn import functional as F

from experiments.hcsn_distributional_v2 import distribution_kernel as kernel
from experiments.hcsn_distributional_v2.model import (
    DistributionalClassifier, DistributionalContentCell, PHYSICAL_CHANNELS,
    PHYSICAL_TIME_SCALE)
from experiments.hcsn_distributional_v2.stable_probability import advance_probability
from experiments.hcsn_free_boundary_v1.oracle_torch import free_boundary
from .risk_kernel import first_event_operator, first_event_probability


MODEL_NAMES = ("risk_margin", "risk_margin_j", "risk_margin_j_risk",
               "risk_ordinary_two_gates", "risk_fixed_full", "risk_direct_full",
               "risk_conditional_full")


class RiskContentCell(DistributionalContentCell):
    def __init__(self, width, arm, physical_channels=PHYSICAL_CHANNELS):
        if arm not in MODEL_NAMES:
            raise ValueError(f"Unknown risk-study arm: {arm}")
        super().__init__(width, "distribution_free_dual", physical_channels)
        self.study_arm = arm
        self.use_j = arm in ("risk_margin_j", "risk_margin_j_risk", "risk_fixed_full",
                             "risk_direct_full", "risk_conditional_full")
        self.use_risk = arm in ("risk_margin_j_risk", "risk_fixed_full", "risk_direct_full",
                                "risk_conditional_full")
        if arm in ("risk_direct_full", "risk_conditional_full"):
            self.raw_boundary_gap = nn.Parameter(torch.full((physical_channels,), math.log(.85 / 3.14)))
        if arm == "risk_conditional_full":
            self.raw_boundary_slope = nn.Parameter(torch.zeros(physical_channels))

    def prepare(self, sequence):
        signal = self.norm(sequence)
        mu = .1 + .4 * torch.tanh(self.drift_input(signal) + self.mu_bias)
        sigma = .3 + .3 * self.raw_sigma.sigmoid()
        rho = .15 + .6 * self.raw_rho.sigmoid()
        cost = .35 + .35 * self.raw_K.sigmoid()
        reset = -.3 + .4 * self.raw_reset.sigmoid()
        refractory = .3 + .9 * self.raw_refractory.sigmoid()
        if self.study_arm == "risk_fixed_full":
            boundary = torch.full_like(mu, 1.2)
        elif self.study_arm == "risk_direct_full":
            boundary = (.35 + 3.99 * self.raw_boundary_gap.sigmoid()).expand_as(mu)
        elif self.study_arm == "risk_conditional_full":
            boundary = .35 + 3.99 * (self.raw_boundary_gap + self.raw_boundary_slope * mu).sigmoid()
        else:
            m = self.grid.refractory_stages
            tau_effective = m / rho * torch.log1p(rho * refractory / m)
            boundary = free_boundary(mu, sigma, rho, cost, reset, tau_effective)
        return signal, dict(mu=mu, sigma=sigma, rho=rho, K=cost, r=reset,
                            tau=refractory, boundary=boundary)

    def advance(self, x, signal, duration, state, local, prepared):
        flow = prepared["flow"]
        prior = state["probability"]
        if prior is None:
            prior = kernel.initial_probability(flow, initial=0.0)
        advanced = advance_probability(prior, prepared["transition"],
            operator_kind="regenerative_probability", event_vector=prepared["event_vector"],
            reward_vector=prepared["reward_vector"])
        probability = advanced["probability"]
        n = self.grid.cells
        active = probability[..., :n]
        eligible, phase = active.sum(-1), probability[..., n:].sum(-1)
        mean = (active * flow["centers"]).sum(-1) / eligible.clamp_min(1e-12)
        mean = torch.where(eligible > 0, mean, torch.zeros_like(mean))
        variance = (active * (flow["centers"] - mean[..., None]).square()).sum(-1)
        margin = (active * (flow["boundary"][..., None] - flow["centers"])).sum(-1)
        m, a, v = margin.tanh(), mean.tanh(), variance.tanh()
        continuation = ((probability * prepared["J"]).sum(-1) if self.use_j else None)
        risk = (first_event_probability(prior, prepared["risk"])["risk"].to(x.dtype)
                if self.use_risk else None)
        if self.study_arm == "risk_ordinary_two_gates":
            features = torch.stack((a, v, eligible), -1)
        elif self.study_arm == "risk_margin":
            features = torch.stack((m, a, v), -1)
        else:
            j = continuation / (1 + continuation.abs())
            features = torch.stack((m, j, risk if self.use_risk else v), -1)
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
        aux = dict(activity=advanced["events"], cost=local["K"] * advanced["events"],
                   modeled_reward=advanced["reward"], margin=margin,
                   probability=probability, flow_mass=probability.sum(-1),
                   active_mass=eligible, refractory_mass=phase, active_center_variance=variance,
                   boundary=local["boundary"], content=content)
        # Diagnostic keys are namespaced and retained for every token. They
        # describe the regenerative projection, never the killed survival map.
        for key, value in advanced["diagnostics"].items():
            if torch.is_tensor(value):
                aux["projection_" + key] = value.expand_as(eligible)
        if self.use_j:
            aux["continuation"] = continuation
        if self.use_risk:
            aux["first_event_probability"] = risk
        return x + self.output(content), new_state, aux

    def forward(self, sequence, dt, state=None):
        signal, parameters = self.prepare(sequence)
        state = self.initial_state(sequence.shape[0], sequence) if state is None else state
        b = parameters["boundary"]
        first_boundary = b[:, :1] if state["boundary"] is None else state["boundary"][:, None]
        old_boundary = torch.cat((first_boundary, b[:, :-1]), 1)
        prepared = kernel.prepare_operator(
            parameters["mu"], parameters["sigma"], b, parameters["r"], parameters["tau"],
            PHYSICAL_TIME_SCALE * dt[..., None], grid=self.grid, old_boundary=old_boundary,
            rho=parameters["rho"] if self.use_j else None,
            K=parameters["K"] if self.use_j else None,
            reward_slope=1.0, reward_intercept=-parameters["K"])
        risk = first_event_operator(prepared["flow"], old_boundary,
                                   PHYSICAL_TIME_SCALE * dt[..., None]) if self.use_risk else None
        outputs, records = [], []
        for index in range(sequence.shape[1]):
            local = {key: value[:, index] if value.ndim == 3 else value
                     for key, value in parameters.items()}
            operator = {key: prepared[key][:, index]
                        for key in ("transition", "event_vector", "reward_vector")}
            operator["flow"] = {key: value[:, index] if torch.is_tensor(value) else value
                                for key, value in prepared["flow"].items()}
            if self.use_j:
                operator["J"] = prepared["values"]["J"][:, index]
            if self.use_risk:
                operator["risk"] = {key: risk[key][:, index]
                                    for key in ("survival_transition", "risk_vector")}
            output, state, aux = self.advance(sequence[:, index], signal[:, index],
                dt[:, index, None], state, local, operator)
            outputs.append(output)
            records.append(aux)
        return torch.stack(outputs, 1), state, {
            key: torch.stack([row[key] for row in records], 1) for key in records[0]}


class RiskClassifier(DistributionalClassifier):
    def __init__(self, arm, input_dim, output_dim, width=32, depth=1, seed=0):
        nn.Module.__init__(self)
        self.config = dict(name=arm, input_dim=input_dim, output_dim=output_dim,
            width=width, depth=depth, seed=seed, physical_channels=PHYSICAL_CHANNELS,
            physical_time_scale=PHYSICAL_TIME_SCALE, grid_cells=8, refractory_stages=2,
            lower=-2.0, precomputed_operators=True, uniformization_rate=8.1,
            uniformization_terms=21, max_physical_substep=.36, per_token_chunks=True,
            max_independent_chunks=1048576, state_projection="bounded_regenerative_only",
            risk="first_event_in_current_interval_including_boundary_jump",
            feature_study="equal_capacity_replacement_with_common_full_physical_information")
        with torch.random.fork_rng():
            torch.manual_seed(seed)
            self.frontend = nn.Sequential(nn.Linear(input_dim + 2, width), nn.LayerNorm(width), nn.Tanh())
            self.readout = nn.Linear(width, output_dim)
        with torch.random.fork_rng():
            torch.manual_seed(seed + 100003)
            self.layers = nn.ModuleList([RiskContentCell(width, arm) for _ in range(depth)])


def build_model(name, input_dim, output_dim, width=32, depth=1, seed=0):
    return RiskClassifier(name, input_dim, output_dim, width, depth, seed)
