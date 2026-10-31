"""Jointly trainable, finite-law cells and public-state action-value heads."""

import json
from pathlib import Path

import torch
from torch import nn

from .dynamics import EventDynamics
from .task import ACTIONS, FEATURE_NAMES
from .temperature import EventTemperature


class JointCell(nn.Module):
    """Enumerate internal states instead of differentiating sampled hard events.

    Both Q1 and Q* heads share every encoder/dynamics parameter. Predictions
    per latent state make sum_z p(z) L(Q_z, target) an actual expectation for
    this finite-state training surrogate. It is not the hard policy return.
    """

    def __init__(self, mode, n_grid=15, hidden=12):
        super().__init__()
        self.mode, self.n_grid, self.hidden = mode, n_grid, hidden
        self.core = (EventTemperature(n_grid) if mode == "first_passage_temperature" else
                     EventDynamics("continuous" if mode == "direct" else mode, n_grid))
        self.content = nn.Sequential(nn.Linear(len(FEATURE_NAMES), hidden), nn.Tanh(),
                                     nn.Linear(hidden, 8), nn.Tanh())
        self.drive = nn.Linear(8, 1)
        self.readout = nn.Sequential(nn.Linear(len(FEATURE_NAMES) + 8 + 4, hidden),
                                     nn.Tanh(), nn.Linear(hidden, 2 * len(ACTIONS)))
        self.double()
        if mode == "direct":
            for parameter in list(self.core.parameters()) + list(self.drive.parameters()):
                parameter.requires_grad_(False)

    def initial(self, batch=1):
        return self.core.initial(batch)

    def parameter_groups(self):
        groups = self.core.parameter_groups()
        groups["dynamics"] = groups["dynamics"] + list(self.drive.parameters())
        groups["noise"] = [self.core.raw_diffusion]
        groups["content"] = list(self.content.parameters())
        groups["readout"] = list(self.readout.parameters())
        return groups

    def encode(self, inputs):
        content = self.content(inputs)
        drive = 1.5 * torch.tanh(self.drive(content).squeeze(-1))
        return content, drive

    def advance(self, mass, inputs, dt=1.0):
        content, drive = self.encode(inputs)
        if self.mode == "direct":
            return mass, mass.new_zeros((mass.shape[0], 2)), content
        new_mass, events = self.core(mass, drive, dt)
        return new_mass, events, content

    def state_action_values(self, inputs, content):
        batch, states = inputs.shape[0], self.core.n_states
        basis = self.core.state_features(torch.eye(states, dtype=inputs.dtype))
        # Raw second moment preserves reset jitter as well as mean amplitude.
        basis = torch.stack((basis[:, 0], basis[:, 1] + basis[:, 0].square(),
                             basis[:, 2], basis[:, 3]), dim=-1)
        if self.mode == "direct":
            basis = torch.zeros_like(basis)
        public = torch.cat((inputs, content), dim=-1)
        joined = torch.cat((public[:, None, :].expand(batch, states, -1),
                            basis[None, :, :].expand(batch, -1, -1)), dim=-1)
        return self.readout(joined).reshape(batch, states, 2, len(ACTIONS))

    def values(self, mass, inputs, content=None):
        if content is None:
            content, _ = self.encode(inputs)
        per_state = self.state_action_values(inputs, content)
        return (mass[:, :, None, None] * per_state).sum(dim=1)

    def configuration(self):
        return {"mode": self.mode, "n_grid": self.n_grid, "hidden": self.hidden}


def save_model(model, path, metadata):
    record = {"configuration": model.configuration(), "metadata": metadata,
              "state_dict": {key: value.detach().cpu().tolist()
                             for key, value in model.state_dict().items()}}
    Path(path).write_text(json.dumps(record, sort_keys=True, allow_nan=False) + "\n")


def load_model(path):
    record = json.loads(Path(path).read_text())
    model = JointCell(**record["configuration"])
    current = model.state_dict()
    model.load_state_dict({key: torch.as_tensor(value, dtype=current[key].dtype)
                           for key, value in record["state_dict"].items()})
    model.eval()
    return model, record["metadata"]
