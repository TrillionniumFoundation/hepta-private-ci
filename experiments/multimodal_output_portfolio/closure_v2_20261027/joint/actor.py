"""A stochastic latent generator with a likelihood-ratio reward derivative.

All trainable parameters enter the density of a low-dimensional Gaussian.
The frozen encoder, selected transitions, decoder and PNG observer may be
nondifferentiable. Deployment samples exactly the distribution trained here.
"""

from dataclasses import replace
from pathlib import Path

import torch
from torch import nn

from ...v6.data import Observation
from ...v6.neural import NeuralState, parameter_hash
from ...v6.plan_training import ControlledSnapshot, PLANS
from ...repair_20261026.joint.train import apply_plan


class LatentActor(nn.Module):
    def __init__(self, input_size, dimensions, hidden=48, bound=2.):
        super().__init__()
        self.config = dict(input_size=input_size, dimensions=dimensions,
                           hidden=hidden, bound=bound)
        self.network = nn.Sequential(nn.Linear(input_size, hidden), nn.Tanh(),
                                     nn.Linear(hidden, dimensions))
        nn.init.zeros_(self.network[-1].weight)
        nn.init.zeros_(self.network[-1].bias)
        self.bound = bound

    def forward(self, features):
        return self.bound * torch.tanh(self.network(features) / self.bound)


def terminal_state(base, observation, noise):
    if not isinstance(observation, Observation):
        raise TypeError("Only public Observation can enter the latent generator")
    model, gate = base._base._model, base._gate
    initial = model.encode(observation, noise)
    choices = gate(initial.context).argmax(-1)
    groups, positions = [], []
    for index, plan in enumerate(PLANS):
        ids = torch.where(choices == index)[0]
        if len(ids):
            state = NeuralState(*(getattr(initial, field)[ids]
                                  for field in ("h", "image", "text", "context")))
            groups.append(apply_plan(model, state, plan))
            positions.append(ids)
    order = torch.cat(positions).argsort()
    state = NeuralState(*(torch.cat([getattr(group, field) for group in groups])[order]
                          for field in ("h", "image", "text", "context")))
    return state, choices


def state_features(state):
    return torch.cat((state.context, state.h, state.image, state.text), dim=1)


def shift_state(state, coefficients, basis):
    shift = coefficients @ basis
    dh, di, dt = shift.chunk(3, dim=-1)
    return replace(state, h=state.h + dh, image=state.image + di,
                   text=state.text + dt)


def antithetic_gradient(positive_cost, negative_cost, directions, sigma):
    """Unbiased gradient of Gaussian expected cost, before optimizer clipping."""
    if sigma <= 0 or positive_cost.shape != negative_cost.shape:
        raise ValueError("A positive fixed standard deviation and paired costs are required")
    if directions.shape[:-1] != positive_cost.shape:
        raise ValueError("Every sampled direction must have both actual outcomes")
    return ((positive_cost - negative_cost)[..., None] * directions).mean(0) / (2 * sigma)


class LatentSnapshot:
    def __init__(self, base, actor, basis, sigma, metadata=None):
        self.base = base
        self.actor = actor.eval().requires_grad_(False)
        self.basis = basis.detach().cpu().clone()
        self.sigma = float(sigma)
        self.metadata = metadata or {}
        if self.sigma <= 0 or self.basis.shape != (actor.config["dimensions"], 3 * base._base._model.hidden):
            raise ValueError("Latent distribution contract differs")

    @torch.inference_mode()
    def generate(self, observation, base_noise, latent_noise):
        state, choices = terminal_state(self.base, observation, base_noise)
        mean = self.actor(state_features(state))
        if latent_noise.shape != mean.shape:
            raise ValueError("Latent noise shape differs from the trained distribution")
        output = self.base._base._model.decode(shift_state(state, mean + self.sigma * latent_noise, self.basis))
        return output, choices, mean

    def save(self, path):
        torch.save({"schema": "hepta.ndu.latent-score-actor.v1", "config": self.actor.config,
                    "state_dict": self.actor.state_dict(), "basis": self.basis,
                    "sigma": self.sigma, "base_fingerprint": self.base.fingerprint,
                    "actor_fingerprint": parameter_hash(self.actor), "metadata": self.metadata}, path)

    @classmethod
    def load(cls, path, base):
        record = torch.load(Path(path), weights_only=True, map_location="cpu")
        if record["schema"] != "hepta.ndu.latent-score-actor.v1" or record["base_fingerprint"] != base.fingerprint:
            raise ValueError("The actor is bound to a different frozen generator")
        actor = LatentActor(**record["config"])
        actor.load_state_dict(record["state_dict"])
        if parameter_hash(actor) != record["actor_fingerprint"]:
            raise ValueError("Actor state digest differs")
        return cls(base, actor, record["basis"], record["sigma"], record["metadata"])
