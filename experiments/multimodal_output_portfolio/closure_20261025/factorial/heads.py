"""Frozen public-state gate and final-step critic for a factorial experiment."""

import math

import torch
from torch import nn
from torch.nn import functional as F

from ...abc_recovery.runtime import ACTIONS
from ...abc_recovery.trees import PLANS
from ...v6.forecast import RidgeHead


GAMMA = 2.
ACTION_PRICE = .002


class Gate(nn.Module):
    def __init__(self):
        super().__init__()
        self.net = nn.Sequential(nn.Linear(384, 64), nn.Tanh(), nn.Linear(64, len(PLANS)))

    def forward(self, features):
        return self.net(features)


def objective(logits, outcomes, profile):
    """Both arms use exact finite plan gradients with detached actual rewards."""
    if outcomes.ndim != 3 or outcomes.shape[:2] != logits.shape:
        raise ValueError("Expected case/plan/scenario rewards")
    if not torch.isfinite(outcomes).all() or not torch.isfinite(logits).all():
        raise ValueError("Nonfinite gate input")
    if profile == "mean":
        return -(logits.softmax(1) * outcomes.detach().mean(2)).sum(1).mean()
    if profile == "entropic":
        values = F.log_softmax(logits.double(), 1)[:, :, None] - GAMMA * outcomes.detach().double()
        return (torch.logsumexp(values.flatten(), 0) - math.log(outcomes.shape[0] * outcomes.shape[2])) / GAMMA
    raise ValueError("Unknown gate objective")


def child_columns(child):
    first = ACTIONS[child]
    return [PLANS.index((first,)), *(PLANS.index((first, second)) for second in ACTIONS[1:])]


def adjusted(utilities):
    return utilities - torch.tensor([ACTION_PRICE * len(plan) for plan in PLANS], dtype=utilities.dtype)


def fit(data, seed):
    features = data["features"]
    roots = features[:, 0, :384].reshape(-1, 2, 384)
    if not torch.equal(roots[:, 0], roots[:, 1]):
        raise ValueError("Gate context must be identical across scenario draws")
    outcomes = adjusted(data["utility"]["primary"]).reshape(-1, 2, len(PLANS)).transpose(1, 2)
    gates, histories = {}, {}
    for profile in ("mean", "entropic"):
        with torch.random.fork_rng(devices=[]):
            torch.manual_seed(seed + 20261025)
            gate = Gate()
        optimizer = torch.optim.Adam(gate.parameters(), lr=.003)
        rng, history = torch.Generator().manual_seed(seed + 101), []
        for step in range(500):
            ids = torch.randperm(len(roots), generator=rng)[:64]
            loss = objective(gate(roots[ids, 0]), outcomes[ids], profile)
            optimizer.zero_grad(set_to_none=True)
            loss.backward()
            optimizer.step()
            if step % 50 == 0 or step == 499:
                history.append({"step": step + 1, "objective": float(loss.detach())})
        gates[profile] = gate.eval().requires_grad_(False)
        histories[profile] = history
    # Predict actual exp(-gamma U) for stop and four next actions. The labels
    # contain one independent future draw per current public node, never a
    # hindsight-best grandchild. Test sources do not enter fitting or selection.
    x = torch.cat([features[:, child] for child in range(1, 5)])
    y = torch.cat([torch.exp(-GAMMA * data["utility"]["primary"][:, child_columns(child)])
                   for child in range(1, 5)])
    critic = RidgeHead.fit(x, y, ridge=32.)
    return gates, critic, histories


@torch.inference_mode()
def select(gate, critic, features, dynamic):
    """Only public current features are accepted, with no outcomes or IDs."""
    result = gate(features[:, 0, :384]).argmax(1)
    if not dynamic:
        return result
    for child in range(1, 5):
        first = ACTIONS[child]
        ids = torch.tensor([i for i, plan in enumerate(PLANS) if plan and plan[0] == first])
        rows = torch.isin(result, ids).nonzero().flatten()
        if not len(rows):
            continue
        moment = critic(features[rows, child]).clamp(math.exp(-2), math.exp(2))
        value = -moment.log() / GAMMA
        value[:, 1:] -= ACTION_PRICE
        # At the final step semantic changes h but preserves the actual draft;
        # under a positive action price it is exactly dominated by stopping.
        value[:, 1] = -torch.inf
        action = value.argmax(1)
        columns = torch.tensor(child_columns(child))
        result[rows] = columns[action]
    return result


def pick_fixed(data, allocation_only=False):
    candidates = [i for i, plan in enumerate(PLANS)
                  if not allocation_only or all(a in {"refine_image", "refine_text"} for a in plan)]
    moment = torch.exp(-GAMMA * adjusted(data["utility"]["primary"])).mean(0)
    return min(candidates, key=lambda i: float(moment[i]))


def save(path, gates, critic, fixed, allocation):
    torch.save({"gates": {k: v.state_dict() for k, v in gates.items()},
                "critic": critic.state_dict(), "fixed": fixed, "allocation": allocation,
                "schema": "hepta.closure.factorial.heads.v1"}, path)


def load(path):
    record = torch.load(path, map_location="cpu", weights_only=True)
    if record.get("schema") != "hepta.closure.factorial.heads.v1":
        raise ValueError("Unknown factorial checkpoint")
    gates, critic = {}, RidgeHead(673, 5)
    for name, state in record["gates"].items():
        gate = Gate()
        gate.load_state_dict(state, strict=True)
        gates[name] = gate.eval().requires_grad_(False)
    critic.load_state_dict(record["critic"], strict=True)
    return gates, critic.eval().requires_grad_(False), record["fixed"], record["allocation"]
