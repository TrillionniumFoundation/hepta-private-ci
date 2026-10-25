"""Paired conditional-moment advantages and a frozen-teacher actor."""

from dataclasses import dataclass

import torch
from torch import nn
from torch.nn import functional as F

from .features import DIM


GAMMA = 2.
ACTION_COST = .002
CONFIG = {"critic_hidden": 64, "actor_hidden": 32, "steps": 600,
          "fold_steps": 400, "batch": 256, "lr": .002, "folds": 2}


class Head(nn.Module):
    """Fixed schema, fit-only normalization, finite deployed parameters."""

    def __init__(self, width, outputs, seed):
        super().__init__()
        self.config = {"width": width, "outputs": outputs, "seed": seed}
        with torch.random.fork_rng(devices=[]):
            torch.manual_seed(seed)
            self.net = nn.Sequential(nn.Linear(DIM, width), nn.Tanh(), nn.Linear(width, outputs))
        self.register_buffer("mean", torch.zeros(DIM))
        self.register_buffer("scale", torch.ones(DIM))

    def forward(self, x):
        if x.ndim != 2 or x.shape[1] != DIM or not torch.isfinite(x).all():
            raise ValueError("Invalid public input")
        y = self.net((x - self.mean) / self.scale)
        if not torch.isfinite(y).all():
            raise ValueError("Nonfinite model output")
        return y


def action_values(head, x, remaining):
    delta = head(x)
    values = torch.cat((torch.zeros((len(x), 1)), delta), 1)
    if remaining == 1:
        values[:, 1] = float("inf")
    elif remaining != 2:
        raise ValueError("Only H1/H2 actions are registered")
    return values


def actor_values(head, x, remaining):
    logits = head(x).clone()
    if remaining == 1:
        logits[:, 1] = -float("inf")
    elif remaining != 2:
        raise ValueError("Only H1/H2 actions are registered")
    return logits.softmax(-1)


def fit_head(x, target, *, width, outputs, seed, steps, actor=False):
    if len(x) == 0 or len(x) != len(target) or not torch.isfinite(target).all():
        raise ValueError("Incomplete/nonfinite offline labels")
    head = Head(width, outputs, seed)
    with torch.no_grad():
        head.mean.copy_(x.mean(0))
        scale = x.std(0, unbiased=False)
        head.scale.copy_(torch.where(scale > 1e-6, scale, torch.ones_like(scale)))
    optimizer = torch.optim.Adam(head.parameters(), lr=CONFIG["lr"])
    rng = torch.Generator().manual_seed(seed + 1)
    trace = []
    for step in range(steps):
        ids = torch.randint(len(x), (CONFIG["batch"],), generator=rng)
        prediction = head(x[ids])
        loss = F.cross_entropy(prediction, target[ids]) if actor else F.mse_loss(prediction, target[ids])
        if not torch.isfinite(loss):
            raise ValueError("Nonfinite training objective")
        optimizer.zero_grad(); loss.backward(); optimizer.step()
        if step == 0 or (step + 1) % 200 == 0:
            trace.append({"step": step + 1, "loss": float(loss.detach())})
    head.eval().requires_grad_(False)
    if any(not torch.isfinite(p).all() for p in head.state_dict().values()):
        raise ValueError("Nonfinite final parameters")
    return head, trace


def h1_examples(public, utilities):
    """Same-node action-minus-stop samples, without taking a future maximum."""
    if utilities.shape != (len(public), 21):
        raise ValueError("All 21 potential paths required offline")
    x = public.clone(); x[:, 0, -1] = .5
    outcome = torch.empty((len(x), 5, 5))
    outcome[:, 0] = utilities[:, :5]
    for first in range(4):
        outcome[:, first + 1, 0] = utilities[:, first + 1]
        outcome[:, first + 1, 1:] = utilities[:, 5 + 4 * first:9 + 4 * first]
    costs = torch.tensor([0., ACTION_COST, ACTION_COST, ACTION_COST, ACTION_COST])
    moments = torch.exp(-GAMMA * (outcome - costs))
    delta = moments[..., 1:] - moments[..., :1]
    return x.flatten(0, 1), delta.flatten(0, 1), moments


def fit_pair(public, utilities, cases, seed):
    x1, differences, moments = h1_examples(public, utilities)
    folds = cases % CONFIG["folds"]
    root_targets = torch.empty((len(public), 4))
    oof = torch.empty_like(differences)
    fold_records = []
    for held in range(CONFIG["folds"]):
        train = folds.repeat_interleave(5) != held
        test = folds == held
        model, trace = fit_head(x1[train], differences[train], width=CONFIG["critic_hidden"],
                               outputs=4, seed=seed + held, steps=CONFIG["fold_steps"])
        with torch.no_grad():
            oof[~train] = model(x1[~train])
            child = public[test, 1:].flatten(0, 1)
            chosen = action_values(model, child, 1).argmin(-1)
            # Choice uses only pre-grandchild state. The held-out actual result
            # is then a label, not information available to that choice.
            terminal = moments[test, 1:].flatten(0, 1)[torch.arange(len(chosen)), chosen]
            backed = torch.exp(torch.tensor(GAMMA * ACTION_COST)) * terminal.reshape(-1, 4)
            root_targets[test] = backed - torch.exp(-GAMMA * utilities[test, :1])
        fold_records.append({"held_fold": held, "fit_source_pairs": int(torch.unique(cases[~test]).numel()),
                             "held_source_pairs": int(torch.unique(cases[test]).numel()), "trace": trace})
    model, trace = fit_head(torch.cat((x1, public[:, 0])), torch.cat((differences, root_targets)),
                           width=CONFIG["critic_hidden"], outputs=4, seed=seed + 10, steps=CONFIG["steps"])
    return model, {"folds": fold_records, "full_trace": trace,
                   "oof_paired_moment_MSE": float((oof - differences).square().mean()),
                   "oof_vs_zero_baseline_MSE": float(differences.square().mean()),
                   "scope": "realized same-node paired labels; no uniform conditional-error certificate"}


@dataclass
class Bundle:
    critic: Head
    actor: Head
    threshold: float | None

    @torch.no_grad()
    def propose(self, public, remaining):
        probabilities = actor_values(self.actor, public, remaining)
        confidence, action = probabilities.max(-1)
        paired = action_values(self.critic, public, remaining)
        pair_action = paired.argmin(-1)
        take = (action == pair_action) & (confidence >= self.threshold) if self.threshold is not None else torch.zeros_like(action, dtype=torch.bool)
        return action, pair_action, take, confidence, paired


def save(bundle, path):
    with path.open("xb") as stream:
        torch.save({"schema": "hepta.closure.public-paired-actor.v1", "threshold": bundle.threshold,
                    **{k: {"config": getattr(bundle, k).config, "state": getattr(bundle, k).state_dict()}
                       for k in ("critic", "actor")}}, stream)


def load(path):
    record = torch.load(path, map_location="cpu", weights_only=True)
    if record["schema"] != "hepta.closure.public-paired-actor.v1":
        raise ValueError("Unknown actor bundle")
    heads = []
    for name in ("critic", "actor"):
        head = Head(**record[name]["config"]); head.load_state_dict(record[name]["state"], strict=True)
        if any(not torch.isfinite(p).all() for p in head.state_dict().values()):
            raise ValueError("Invalid deployed parameter")
        heads.append(head.eval().requires_grad_(False))
    return Bundle(*heads, record["threshold"])
