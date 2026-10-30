"""Backend-injected copies of the sealed distributional content model.

Trainable parameters, initialization, values, content gates and recurrence match
the v2 model. Only operator preparation and the explicitly selected probability
profile change. ``raw`` retains v2's multiplication; ``stable`` invokes the
separately published, strictly tagged roundoff normalization. Both backends use
the same profile in a comparison. No frozen source is patched at runtime.
"""

import torch
from torch import nn
from torch.nn import functional as F

from experiments.hcsn_distributional_v2 import distribution_kernel as reference
from experiments.hcsn_distributional_v2 import model as original
from experiments.hcsn_distributional_v2 import stable_probability


BACKENDS = ("reference", "accelerated")
PROFILES = ("raw", "stable")
DISTRIBUTION_ARMS = original.DISTRIBUTION_ARMS


def operator_backend(name):
    if name == "reference":
        return reference.prepare_operator
    if name == "accelerated":
        from .kernel import prepare_operator

        return prepare_operator
    raise ValueError(f"Unknown operator backend: {name}")


class DistributionalContentCell(original.DistributionalContentCell):
    """Keep the original trainable graph and select its numerical backend."""

    def __init__(self, width, arm="distribution_free_dual",
                 physical_channels=original.PHYSICAL_CHANNELS, precompute=True,
                 backend="accelerated", profile="stable"):
        if backend not in BACKENDS or profile not in PROFILES:
            raise ValueError("Unknown operator backend or probability profile")
        super().__init__(width, arm, physical_channels, precompute)
        self.backend, self.profile = backend, profile

    def advance(self, x, signal, duration, state, local, prepared=None):
        """The v2 advance body, with explicit propagation/profile injection.

        The added diagnostics detach only their reporting tensors. Probability
        normalization itself participates in autograd. It is never applied to
        a killed/no-event operator, and no negative value is clipped.
        """
        if prepared is None:
            old = local["boundary"] if state["boundary"] is None else state["boundary"]
            prepared = operator_backend(self.backend)(
                local["mu"], local["sigma"], local["boundary"], local["r"], local["tau"],
                original.PHYSICAL_TIME_SCALE * duration, grid=self.grid,
                old_boundary=old,
                rho=None if self.arm == "distribution_free_ordinary" else local["rho"],
                K=None if self.arm == "distribution_free_ordinary" else local["K"],
                reward_slope=1.0, reward_intercept=-local["K"])
        flow = prepared["flow"]
        probability = state["probability"]
        if probability is None:
            probability = reference.initial_probability(flow, initial=0.0)

        if self.profile == "stable":
            propagated = stable_probability.advance_probability(
                probability, prepared["transition"],
                operator_kind=stable_probability.REGENERATIVE_PROBABILITY,
                event_vector=prepared["event_vector"],
                reward_vector=prepared["reward_vector"])
            diagnostics = propagated["diagnostics"]
            correction = diagnostics["actual_l1_correction"]
            raw_defect = (diagnostics["pre_projection_mass"] - 1).abs()
            row_defect = diagnostics["maximum_transition_row_mass_defect"]
        else:
            propagated = dict(
                probability=torch.matmul(probability.unsqueeze(-2),
                                         prepared["transition"]).squeeze(-2),
                events=(probability * prepared["event_vector"]).sum(-1),
                reward=(probability * prepared["reward_vector"]).sum(-1))
            raw_defect = (propagated["probability"].sum(-1, dtype=torch.float64) - 1).abs().detach()
            row_defect = (prepared["transition"].sum(-1, dtype=torch.float64) - 1).abs().amax(-1).detach()
            correction = torch.zeros_like(raw_defect)
        probability = propagated["probability"]
        if self.arm == "active_mean_collapse_free_dual":
            probability = original._collapse_active(probability, local["boundary"], self.grid)
        if self.arm == "distribution_free_ordinary":
            values = dict(eligible_margin=(probability[..., :self.grid.cells] *
                (flow["boundary"][..., None] - flow["centers"])).sum(-1))
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
                   boundary=local["boundary"], content=content,
                   normalization_l1_correction=correction,
                   raw_probability_mass_defect=raw_defect,
                   transition_row_mass_defect=row_defect)
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
            first = b[:, :1] if state["boundary"] is None else state["boundary"][:, None]
            old_boundary = torch.cat((first, b[:, :-1]), 1)
            prepared = operator_backend(self.backend)(
                parameters["mu"], parameters["sigma"], b, parameters["r"], parameters["tau"],
                original.PHYSICAL_TIME_SCALE * dt[..., None], grid=self.grid,
                old_boundary=old_boundary,
                rho=None if self.arm == "distribution_free_ordinary" else parameters["rho"],
                K=None if self.arm == "distribution_free_ordinary" else parameters["K"],
                reward_slope=1.0, reward_intercept=-parameters["K"])
        outputs, records = [], []
        for index in range(sequence.shape[1]):
            local = {key: value[:, index] if value.ndim == 3 else value
                     for key, value in parameters.items()}
            item = None
            if prepared is not None:
                item = {key: prepared[key][:, index]
                        for key in ("transition", "event_vector", "reward_vector")}
                item["flow"] = {key: value[:, index] if torch.is_tensor(value) else value
                                for key, value in prepared["flow"].items()}
                item["values"] = (None if prepared["values"] is None else
                    {key: value[:, index] for key, value in prepared["values"].items()})
            output, state, aux = self.advance(sequence[:, index], signal[:, index],
                                              dt[:, index, None], state, local, item)
            outputs.append(output)
            records.append(aux)
        return torch.stack(outputs, 1), state, {
            key: torch.stack([row[key] for row in records], 1) for key in records[0]}


class DistributionalClassifier(original.DistributionalClassifier):
    """State-dict-compatible classifier with no additional trainable value."""

    def __init__(self, input_dim, output_dim, width=32, depth=1, seed=0,
                 arm="distribution_free_dual", backend="accelerated", profile="stable"):
        if backend not in BACKENDS or profile not in PROFILES:
            raise ValueError("Unknown operator backend or probability profile")
        super().__init__(input_dim, output_dim, width, depth, seed, arm)
        with torch.random.fork_rng():
            torch.manual_seed(seed + 100003)
            self.layers = nn.ModuleList([
                DistributionalContentCell(width, arm, backend=backend, profile=profile)
                for _ in range(depth)])
        self.backend, self.profile = backend, profile
        self.config.update(operator_backend=backend, probability_profile=profile)


def build_model(name, input_dim, output_dim, width=32, depth=1, seed=0,
                backend="accelerated", profile="stable"):
    if name not in DISTRIBUTION_ARMS:
        raise ValueError("The acceleration wrapper supports distributional arms only")
    return DistributionalClassifier(input_dim, output_dim, width, depth, seed,
                                   name, backend, profile)
