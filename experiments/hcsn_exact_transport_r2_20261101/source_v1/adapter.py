"""Exact causal addressed recurrence with a batched stateless decoder.

The original decoder outputs never enter the recurrence. Materialize the same
pre-write features at every time, then apply its pointwise Linear/GELU/Linear
map once. A scripted recurrence is optional. Neither backend caches tensors,
changes CTMC generators, or changes the information available at a time step.
"""

import time

import torch
from torch import nn

from experiments.hcsn_addressed_flow_20261101.addressed_models import AddressedModel
from experiments.hcsn_propagation_perf_20261101.fused_addressed import prepare


_SCRIPTED_FEATURES = None


def recurrence_features(a: torch.Tensor, b: torch.Tensor, present_b: torch.Tensor,
                        content_write: torch.Tensor, relation_write: torch.Tensor,
                        payload: torch.Tensor, relation_payload: torch.Tensor,
                        probability: torch.Tensor, p: torch.Tensor, transition: torch.Tensor,
                        remap: torch.Tensor, marked_remap: torch.Tensor,
                        normalize: bool):
    batch, steps = a.size(0), a.size(1)
    content = payload.new_zeros((batch, a.size(-1), probability.size(-1), payload.size(-1)))
    relation = payload.new_zeros((batch, a.size(-1), probability.size(-1), relation_payload.size(-1)))
    features: list[torch.Tensor] = []
    for t in range(steps):
        probability = (probability[:, None] @ p[:, t]).squeeze(1)
        transport = transition[:, t].transpose(-1, -2)[:, None]
        content, relation = transport @ content, transport @ relation

        relation_mass = relation[..., -1].sum(-1, keepdim=True)
        relation_values = relation[..., :-1]
        if normalize:
            relation_values = relation_values / relation_mass.clamp_min(1e-8)[..., None]
        translated = (b[:, t, :, None] * relation_values.sum(-2)).sum(1)
        query = ((1 - present_b[:, t, None]) * a[:, t]
                 + present_b[:, t, None] * translated)
        mass = content[..., -1].sum(-1, keepdim=True)
        content_values = content[..., :-1]
        if normalize:
            content_values = content_values / mass.clamp_min(1e-8)[..., None]
        selected = (query[:, :, None, None] * content_values).sum(1)
        confidence = (query * mass.squeeze(-1)).sum(-1, keepdim=True)
        features.append(torch.cat((selected.sum(1), selected.flatten(1), confidence), -1))

        probability = (probability[:, None] @ remap[:, t]).squeeze(1)
        instantaneous = marked_remap[:, t].transpose(-1, -2)[:, None]
        content, relation = instantaneous @ content, instantaneous @ relation
        content_gate = content_write[:, t, None] * a[:, t]
        relation_gate = relation_write[:, t, None] * b[:, t]
        new_content = probability[:, None, :, None] * payload[:, t, None, None, :]
        new_relation = probability[:, None, :, None] * relation_payload[:, t, None, None, :]
        content = ((1 - content_gate[..., None, None]) * content
                   + content_gate[..., None, None] * new_content)
        relation = ((1 - relation_gate[..., None, None]) * relation
                    + relation_gate[..., None, None] * new_relation)
    return torch.stack(features, 1), content


class ExactAddressedAdapter(nn.Module):
    """Opt-in callable sharing the original model's live parameters.

    The wrapper accepts the same x/dt/observed inputs, returns every original
    time-step logit, and supports gradients and optimizer updates. The original
    module stays callable. Unsupported stateful or batch-mixing decoders are
    rejected before installation; only the audited pointwise decoder is allowed.
    """

    def __init__(self, original, recurrence="eager"):
        super().__init__()
        if type(original) is not AddressedModel or original.core != "flow":
            raise ValueError("The exact adapter requires the original addressed Flow model")
        layers = list(original.read.children())
        if (type(original.read) is not nn.Sequential or len(layers) != 3
                or [type(layer) for layer in layers] != [nn.Linear, nn.GELU, nn.Linear]
                or (layers[0].in_features, layers[0].out_features,
                    layers[2].in_features, layers[2].out_features) != (97, 64, 64, 8)):
            raise ValueError("Only the original pointwise Linear/GELU/Linear decoder is supported")
        if recurrence not in ("eager", "scripted"):
            raise ValueError("Unknown recurrence backend")
        self.original = original
        self.recurrence_backend = recurrence
        self.compile_cpu_seconds = 0.0
        self.compile_wall_seconds = 0.0
        self.compiled_here = False
        if recurrence == "scripted":
            global _SCRIPTED_FEATURES
            if _SCRIPTED_FEATURES is None:
                cpu, wall = time.process_time(), time.perf_counter()
                _SCRIPTED_FEATURES = torch.jit.script(recurrence_features)
                self.compile_cpu_seconds = time.process_time() - cpu
                self.compile_wall_seconds = time.perf_counter() - wall
                self.compiled_here = True

    def forward(self, x, dt, observed):
        if x.ndim != 3 or x.shape[-1] != 24 or dt.shape != x.shape[:2] or observed.shape != dt.shape:
            raise ValueError("Expected x[B,T,24], dt[B,T], observed[B,T]")
        if observed.dtype != torch.bool:
            raise ValueError("Observation mask must be boolean")
        if (not bool(torch.isfinite(x).all()) or not bool(torch.isfinite(dt).all())
                or bool((dt < 0).any())):
            raise ValueError("Finite inputs and nonnegative duration required")
        batch, steps = dt.shape
        if batch < 1 or steps < 1:
            raise ValueError("Nonempty batch and sequence required")
        model = self.original
        encoded = model.encode(x)
        a = model._addresses(x[..., :4], model.address_a)
        b = model._addresses(x[..., 19:23], model.address_b)
        gates = model.roles(x[..., 12:16]).sigmoid()
        present_value = (x[..., 4:12].abs().sum(-1) > 0).to(x.dtype)
        present_a = (x[..., :4].abs().sum(-1) > 0).to(x.dtype)
        present_b = (x[..., 19:23].abs().sum(-1) > 0).to(x.dtype)
        content_write = gates[..., 0] * present_a * present_value * observed
        relation_write = gates[..., 1] * present_a * present_b * (1 - present_value) * observed
        payload = torch.cat((model.value(x[..., 4:12]), x.new_ones(batch, steps, 1)), -1)
        relation_payload = torch.cat((a, x.new_ones(batch, steps, 1)), -1)
        matrices = prepare(model, encoded, dt, observed)
        recurrence = _SCRIPTED_FEATURES if self.recurrence_backend == "scripted" else recurrence_features
        features, content = recurrence(
            a, b, present_b, content_write, relation_write, payload, relation_payload,
            matrices["initial"], matrices["P"], matrices["T"], matrices["R"], matrices["MR"],
            model.normalize_occupancy)
        # This decoder operates only on the final feature axis. No cross-time
        # operation or future token is introduced by batching its leading axes.
        output = model.read(features)
        model.last_diagnostics = {
            "content_gate_mean": float(content_write.detach().mean()),
            "relation_gate_mean": float(relation_write.detach().mean()),
            "address_temperature": float(model.log_temperature.detach().exp().clamp(1., 40.)),
            "content_mass_min": float(content.detach()[..., -1].sum(-1).min()),
            "content_mass_max": float(content.detach()[..., -1].sum(-1).max()),
            "normalize_occupancy": model.normalize_occupancy,
            "intervention": model.intervention,
        }
        return output
