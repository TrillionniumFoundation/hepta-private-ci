"""Common causal key routing and query loss for the separate content study.

Keys are supplied symbolic addresses, not learned semantic retrieval. Each core
receives exactly the same routed stream; the addressor never reads labels.
This adapter does not qualify a pretrained encoder or a real media experiment.
"""

import math

import torch
from torch import nn
from torch.nn import functional as F

from .baselines import make_encoder
from .cells import ValueKernelCell
from .stream_time import stream_held_inputs


class ContentValueCell(ValueKernelCell):
    """HX ablations with no allocated, unused channel coefficients.

    Margin uses the same learned financial boundary but only log(V/b).
    Smooth uses two ordinary sigmoid features and no financial computation.
    Counts remain unequal: this removes dead coefficients, not that mismatch.
    """

    def __init__(self, input_size, hidden_size, variant):
        channels = {"hx_dual": "dual", "hx_call": "call", "hx_risk": "risk",
                    "margin_only": "dual", "smooth_gate": "dual"}
        if variant not in channels:
            raise ValueError("unknown content value-cell variant")
        super().__init__(input_size, hidden_size, channel=channels[variant],
                         kernel="softplus" if variant == "smooth_gate" else "hx")
        self.variant = variant
        feature_count = 2 if variant in {"hx_dual", "smooth_gate"} else 1
        self.rate_features = nn.Parameter(torch.full((feature_count, hidden_size), .25))
        self.value_features = nn.Parameter(torch.full((feature_count, hidden_size), .25))

    def _base_boundary(self, params):
        if self.variant == "smooth_gate":
            return torch.ones_like(self.raw_financial[0])
        return super()._base_boundary(params)

    def financial_parameters(self):
        return None if self.variant == "smooth_gate" else super().financial_parameters()

    def _features(self, inputs, memory, params, base_boundary):
        if self.variant == "smooth_gate":
            return torch.stack((torch.sigmoid(self.margin_input(inputs) + .2*memory),
                                torch.sigmoid(self.boundary_input(inputs))))
        if self.variant == "margin_only":
            value = params.principal*(2.4 + 2*torch.sigmoid(self.margin_input(inputs) + .2*memory))
            margin = torch.log(value/base_boundary) - .25*torch.tanh(self.boundary_input(inputs))
            if not bool(torch.isfinite(margin).all()) or bool((margin < 0).any()):
                raise ValueError("content margin is outside the continuation domain")
            return margin.unsqueeze(0)
        features = super()._features(inputs, memory, params, base_boundary)
        return features[:1] if self.variant == "hx_call" else (
            features[1:] if self.variant == "hx_risk" else features)


def route_content(inputs, keys, values):
    """Map one-hot WRITE/QUERY/NOISE/SILENCE into independent key streams.

    WRITE is routed only to its key. NOISE payload remains visible to every
    core, identified as noise. QUERY's key only selects the readout; changing a
    query address never changes the core state. Time still advances on queries.
    Unaddressed writes appear as silence; noise may change the neural state.
    """
    if inputs.ndim != 3 or inputs.shape[-1] != 4 + keys + values:
        raise ValueError("invalid content input layout")
    if inputs.shape[0] < 1 or inputs.shape[1] < 1 or not bool(torch.isfinite(inputs).all()):
        raise ValueError("content inputs must be nonempty and finite")
    kinds, addresses, payload = inputs[..., :4], inputs[..., 4:4+keys], inputs[..., 4+keys:]
    if not bool(((inputs == 0) | (inputs == 1)).all()) or not bool((kinds.sum(-1) == 1).all()):
        raise ValueError("symbolic content requires one-hot kinds and binary fields")
    writes, queries, noise, silence = kinds.unbind(-1)
    if (not bool((addresses.sum(-1) == writes+queries+noise).all())
            or not bool((payload.sum(-1) == writes+noise).all())):
        raise ValueError("event addresses or payload visibility are invalid")
    write_mask = writes[..., None]*addresses
    routed_payload = payload[..., None, :]*(write_mask[..., None]+noise[..., None, None])
    typed = torch.stack((write_mask, queries[..., None].expand_as(write_mask),
                         noise[..., None].expand_as(write_mask),
                         silence[..., None]+writes[..., None]-write_mask), dim=-1)
    routed = torch.cat((typed, routed_payload), dim=-1)
    return routed.permute(0, 2, 1, 3).reshape(-1, inputs.shape[1], values+4)


class AddressedContentModel(nn.Module):
    """Identical identity encoder, symbolic addressor and query head contract.

    Baseline-specific temporal cores have their actual parameter counts. Uniform
    physical intervals are required here; irregular intervals must use an
    explicitly supported streaming adapter, never an averaged dt.
    """

    def __init__(self, core, *, keys, values, hidden_size, device="cpu"):
        super().__init__()
        if min(keys, values, hidden_size) < 1:
            raise ValueError("content dimensions must be positive")
        self.keys, self.values = keys, values
        if core in {"hx_dual", "hx_call", "hx_risk", "margin_only", "smooth_gate"}:
            self.core = ContentValueCell(values+4, hidden_size, core)
        else:
            self.core = make_encoder(core, values+4, hidden_size, device=device)
        self.head = nn.Linear(hidden_size, values+1)
        self.to(device)

    def encode(self, inputs, dt=.1):
        if isinstance(dt, bool) or not isinstance(dt, (int, float)) or not math.isfinite(dt) or dt <= 0:
            raise ValueError("uniform positive scalar dt is required")
        routed = route_content(inputs, self.keys, self.values)
        encoded = self.core(routed, dt=dt)
        return encoded.reshape(inputs.shape[0], self.keys, inputs.shape[1], -1).transpose(1, 2)

    def forward(self, inputs, dt=.1):
        states = self.encode(inputs, dt)
        return self._query_logits(states, inputs)

    def stream(self, inputs, time_edges_seconds, *, initial_state=None, subdivisions=1,
               seconds_per_model_time=1.0):
        """HX/smooth-gate physical-time stream with all key states preserved.

        Optional baselines require their own qualified state/time adapters.
        No state is reset by a query; a fresh episode passes initial_state=None.
        """
        edges = tuple(time_edges_seconds)
        if (len(edges) != inputs.shape[1]+1 or any(isinstance(value, bool) for value in edges)
                or not all(math.isfinite(value) for value in edges)
                or any(right <= left for left, right in zip(edges, edges[1:]))):
            raise ValueError("typed content events require strictly positive physical intervals")
        trace = stream_held_inputs(self.core, route_content(inputs, self.keys, self.values),
                                   edges, initial_state=initial_state,
                                   subdivisions=subdivisions,
                                   seconds_per_model_time=seconds_per_model_time)
        states = trace.memory.reshape(inputs.shape[0], self.keys, inputs.shape[1], -1).transpose(1, 2)
        return self._query_logits(states, inputs), trace.state

    def _query_logits(self, states, inputs):
        addresses = inputs[..., 4:4+self.keys].argmax(-1)
        selected = states.gather(2, addresses[..., None, None].expand(
            -1, -1, 1, states.shape[-1])).squeeze(2)
        # Preserve the same per-event linear dispatch when a stream is chunked.
        # Flattening batch*time can select different BLAS kernels after resume.
        return torch.stack([self.head(value) for value in selected.unbind(1)], 1)


def query_loss(logits, targets, query_mask):
    """Cross entropy only on observed queries; targets never enter the model."""
    if (logits.ndim != 3 or logits.shape[-1] < 1 or logits.shape[:2] != targets.shape
            or query_mask.shape != targets.shape
            or query_mask.dtype != torch.bool or targets.dtype != torch.long):
        raise ValueError("invalid query loss shapes or dtypes")
    if not bool(query_mask.any()) or not bool((targets[~query_mask] == -100).all()):
        raise ValueError("query targets are empty or leak outside the mask")
    if (not bool(((targets[query_mask] >= 0) & (targets[query_mask] < logits.shape[-1])).all())
            or not bool(torch.isfinite(logits).all())):
        raise ValueError("query target classes or logits are invalid")
    return F.cross_entropy(logits[query_mask], targets[query_mask])


def parameter_activity(model):
    """Report a lower bound from one backward pass, not structural capacity.

    A present gradient tensor does not imply that all its entries participate.
    Zero derivatives may also be caused by this particular input or saturation.
    """
    rows = []
    for name, parameter in model.named_parameters():
        gradient = parameter.grad
        rows.append(dict(name=name, stored=parameter.numel(), trainable=parameter.requires_grad,
                         nonzero_gradient=None if gradient is None else int(torch.count_nonzero(gradient)),
                         finite_gradient=None if gradient is None else bool(torch.isfinite(gradient).all())))
    return dict(stored=sum(row["stored"] for row in rows),
                trainable=sum(row["stored"] for row in rows if row["trainable"]),
                observed_nonzero_gradient=sum(row["nonzero_gradient"] or 0 for row in rows),
                structural_activity_certified=False, parameter_match_qualified=False, parameters=rows)
