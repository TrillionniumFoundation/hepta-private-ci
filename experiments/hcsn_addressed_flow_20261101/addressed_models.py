"""Learned typed-address memory with matched ordinary/marked-CTMC transport.

The symbolic token schema is an explicit shared architectural prior: four A
addresses, four B aliases, value fields and event-kind fields are separated.
Learned address embeddings produce soft routing. B->A relation writes contain
only address distributions; the value code and class decoder are learned. No
target, dependency index, computed answer or split identity enters this module.

Each address stores state-conditioned value AND occupancy moments. Normalizing
by the matching occupancy removes common scalar attenuation; this deliberately
separates content identity from physical mass. It can cancel part of the event
effect, and therefore is not evidence for a useful analytical increment.
"""

import math

import torch
from torch import nn
from torch.nn import functional as F

from experiments.hcsn_four_stage_flow_20261031.models import ContentModel, STATES


CORES = ("flow", "diagonal")
ADDRESSES = 4
WIDTH = 16
CONTROL_WIDTH = 24


class AddressedModel(nn.Module):
    def __init__(self, core, input_dim=24, classes=8):
        super().__init__()
        if core not in CORES or input_dim != 24 or classes != 8:
            raise ValueError("Typed symbolic model requires flow/diagonal, 24 inputs and 8 classes")
        self.core, self.arm, self.classes = core, core, classes
        self.intervention = None
        self.normalize_occupancy = True
        self.encode = nn.Sequential(nn.Linear(input_dim, CONTROL_WIDTH), nn.Tanh(),
                                    nn.Linear(CONTROL_WIDTH, CONTROL_WIDTH), nn.Tanh())
        self.control = nn.Linear(CONTROL_WIDTH, 2 if core == "flow" else STATES)
        self.physical = nn.Parameter(
            torch.tensor([-1., -1., 0., 4., -6.]) if core == "flow" else
            torch.expm1(torch.tensor([.0005, .002, .008, .032, .128])).log())
        # Tied read/write embeddings give equal input keys equal representations.
        # Their class-free initialization is the same prior as key equality in
        # attention; no value-to-output map is installed here.
        self.address_a = nn.Parameter(torch.empty(ADDRESSES, WIDTH))
        self.address_b = nn.Parameter(torch.empty(ADDRESSES, WIDTH))
        nn.init.orthogonal_(self.address_a)
        nn.init.orthogonal_(self.address_b)
        self.log_temperature = nn.Parameter(torch.tensor(math.log(8.)))
        self.roles = nn.Linear(4, 2)
        nn.init.zeros_(self.roles.weight)
        nn.init.zeros_(self.roles.bias)
        self.value = nn.Linear(classes, WIDTH, bias=False)
        self.read = nn.Sequential(nn.Linear((STATES + 1) * WIDTH + 1, 64), nn.GELU(),
                                  nn.Linear(64, classes))
        self.last_diagnostics = None

    def _addresses(self, fields, embeddings):
        keys = F.normalize(embeddings, dim=-1)
        query = F.normalize(fields @ keys, dim=-1)
        temperature = self.log_temperature.exp().clamp(1., 40.)
        return (temperature * (query @ keys.T)).softmax(-1)

    def _normalized(self, moments):
        # The final feature is transported occupancy, not an external target.
        mass = moments[..., -1].sum(-1, keepdim=True)
        values = moments[..., :-1]
        if self.normalize_occupancy:
            values = values / mass.clamp_min(1e-8)[..., None]
        return values, mass

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
        encoded = self.encode(x)
        a = self._addresses(x[..., :4], self.address_a)
        b = self._addresses(x[..., 19:23], self.address_b)
        gates = self.roles(x[..., 12:16]).sigmoid()
        present_value = (x[..., 4:12].abs().sum(-1) > 0).to(x.dtype)
        present_a = (x[..., :4].abs().sum(-1) > 0).to(x.dtype)
        present_b = (x[..., 19:23].abs().sum(-1) > 0).to(x.dtype)
        content_write = gates[..., 0] * present_a * present_value * observed
        relation_write = gates[..., 1] * present_a * present_b * (1 - present_value) * observed
        payload = torch.cat((self.value(x[..., 4:12]), x.new_ones(batch, steps, 1)), -1)
        relation_payload = torch.cat((a, x.new_ones(batch, steps, 1)), -1)
        content = x.new_zeros(batch, ADDRESSES, STATES, WIDTH + 1)
        relation = x.new_zeros(batch, ADDRESSES, STATES, ADDRESSES + 1)
        if self.core == "flow":
            # Identical probability/marked transport and boundary remap to the
            # previously audited process; no second dynamics implementation.
            matrices = ContentModel._flow_matrices(self, encoded, dt, observed)
            probability = matrices["initial"]
        else:
            probability = x.new_full((batch, STATES), 1 / STATES)
        outputs = []
        for t in range(steps):
            if self.core == "flow":
                probability = (probability[:, None] @ matrices["P"][:, t]).squeeze(1)
                transport = matrices["T"][:, t].transpose(-1, -2)[:, None]
                content, relation = transport @ content, transport @ relation
            else:
                decay = torch.exp(-F.softplus(self.physical)[None] * dt[:, t, None])
                content = content * decay[:, None, :, None]
                relation = relation * decay[:, None, :, None]

            # Read BEFORE the current token can alter policy or either memory.
            relation_values, _ = self._normalized(relation)
            translated = (b[:, t, :, None] * relation_values.sum(-2)).sum(1)
            query = ((1 - present_b[:, t, None]) * a[:, t]
                     + present_b[:, t, None] * translated)
            content_values, mass = self._normalized(content)
            selected = (query[:, :, None, None] * content_values).sum(1)
            confidence = (query * mass.squeeze(-1)).sum(-1, keepdim=True)
            features = torch.cat((selected.sum(1), selected.flatten(1), confidence), -1)
            outputs.append(self.read(features))

            if self.core == "flow":
                probability = (probability[:, None] @ matrices["R"][:, t]).squeeze(1)
                remap = matrices["MR"][:, t].transpose(-1, -2)[:, None]
                content, relation = remap @ content, remap @ relation
                write_distribution = probability
            else:
                write_distribution = self.control(encoded[:, t]).softmax(-1)
            content_gate = content_write[:, t, None] * a[:, t]
            relation_gate = relation_write[:, t, None] * b[:, t]
            new_content = write_distribution[:, None, :, None] * payload[:, t, None, None, :]
            new_relation = write_distribution[:, None, :, None] * relation_payload[:, t, None, None, :]
            content = ((1 - content_gate[..., None, None]) * content
                       + content_gate[..., None, None] * new_content)
            relation = ((1 - relation_gate[..., None, None]) * relation
                        + relation_gate[..., None, None] * new_relation)
        self.last_diagnostics = {
            "content_gate_mean": float(content_write.detach().mean()),
            "relation_gate_mean": float(relation_write.detach().mean()),
            "address_temperature": float(self.log_temperature.detach().exp().clamp(1., 40.)),
            "content_mass_min": float(content.detach()[..., -1].sum(-1).min()),
            "content_mass_max": float(content.detach()[..., -1].sum(-1).max()),
            "normalize_occupancy": self.normalize_occupancy,
            "intervention": self.intervention,
        }
        return torch.stack(outputs, 1)

    def resource_shape(self, sequence_length):
        memory = ADDRESSES * STATES * (WIDTH + 1 + ADDRESSES + 1)
        return dict(parameters=sum(parameter.numel() for parameter in self.parameters()),
                    persistent_state_scalars=memory + (STATES + 2 if self.core == "flow" else 0),
                    content_scalars=ADDRESSES * STATES * (WIDTH + 1),
                    relation_scalars=ADDRESSES * STATES * (ADDRESSES + 1),
                    matrix_precision="float64" if self.core == "flow" else None,
                    content_precision="float32", compiled=False,
                    sequence_length=sequence_length,
                    prior="Shared typed fields, tied soft key equality and B-to-A relation memory",
                    normalization="Per-address matching occupancy; common attenuation can cancel")
