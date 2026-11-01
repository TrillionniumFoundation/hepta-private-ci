"""Matched input interface and explicit primary/secondary model comparisons."""

import torch
from torch import nn

from experiments.hcsn_validation_r12_20261031.content.models import ContentEncoder, DualGate, WIDTH
from experiments.hcsn_validation_r12_20261031.content.upstream.baseline import build_baseline, match_parameter_budget
from experiments.hcsn_validation_r14_20261101.content.engine import all_logits, model_hash
from .data import TASKS
from .law_core import DistributionContentCore


FAMILIES = ("ordinary_distribution", "analytic_distribution", "ordinary_dual",
            "analytic_fixed", "mamba1", "transformer")
PRIMARY = ("ordinary_distribution", "analytic_distribution")


def configurations():
    core = DistributionContentCore("analytic_distribution", width=WIDTH, seed=0)
    target = sum(p.numel() for p in core.parameters())
    configs = {name: {} for name in FAMILIES}
    for name in PRIMARY:
        configs[name] = dict(core.config, family=name)
    for name in ("mamba1", "transformer"):
        configs[name] = match_parameter_budget(name, WIDTH, target, candidates=range(2, 33))
    return configs


class Model(nn.Module):
    def __init__(self, task, family, seed, core_config=None):
        super().__init__()
        self.config = dict(task=task, family=family, seed=seed, core_config=core_config or {})
        with torch.random.fork_rng():
            torch.manual_seed(seed)
            self.encoder = ContentEncoder(TASKS[task][0])
            self.readout = nn.Linear(WIDTH, TASKS[task][1])
            if family in PRIMARY:
                settings = dict(core_config or {})
                settings.update(family=family, width=WIDTH, seed=seed + 1701)
                self.core = DistributionContentCore(**settings)
                self.config["core_config"] = dict(self.core.config)
            elif family in ("ordinary_dual", "analytic_fixed"):
                self.core = DualGate("analytic" if family == "analytic_fixed" else family, seed + 1701)
            else:
                self.core = build_baseline(family, WIDTH, hidden_width=core_config["hidden_width"])

    def forward(self, x, dt):
        return all_logits(self, x, dt)[:, -1]

    def state_size(self, length):
        family = self.config["family"]
        if family in PRIMARY:
            # Upper cemetery is retained as an explicit component.
            return (len(self.core.positions) + 1) * (WIDTH + 1)
        if family in ("ordinary_dual", "analytic_fixed"):
            return WIDTH
        hidden = self.config["core_config"]["hidden_width"]
        if family == "mamba1":
            return 2 * hidden * (16 + 4)
        return 2 * length * hidden  # KV only; temporaries are excluded.


def restore(checkpoint, family):
    item = checkpoint["models"][family]
    model = Model(**item["config"])
    model.load_state_dict(item["state"])
    model.eval()
    return model


def traced_logits(model, x, dt):
    """Observe actual posterior truncation without changing the recurrent law."""
    if model.config["family"] not in PRIMARY:
        return all_logits(model, x, dt), None
    encoded = model.encoder(x, dt)
    state = model.core.initial_state(len(x), x.device, x.dtype)
    states = [x.new_zeros((len(x), WIDTH))]
    upper = [state["probability"][:, -1]]
    mass_error = [(state["probability"].sum(-1) - 1).abs()]
    minimum = [state["probability"].min(-1).values]
    for index in range(x.shape[1]):
        feature, state = model.core.step(encoded[:, index], state, dt[:, index])
        states.append(feature)
        probability = state["probability"]
        upper.append(probability[:, -1])
        mass_error.append((probability.sum(-1) - 1).abs())
        minimum.append(probability.min(-1).values)
    return model.readout(torch.stack(states, 1)), dict(
        upper_loss_prefix=torch.stack(upper, 1),
        mass_error_prefix=torch.stack(mass_error, 1),
        minimum_probability_prefix=torch.stack(minimum, 1))
