"""One shared conditional risk/success head with source-fold Bellman targets."""

from dataclasses import dataclass
import time

import torch
from torch import nn
from torch.nn import functional as F

from ...abc_recovery.control import PLANS
from ...v6.neural import parameter_hash
from .features import COMPACT_DIM, compact_from_full


CONFIG = {"hidden": 64, "steps": 800, "fold_steps": 600, "learning_rate": .002,
          "batch_size": 256, "gamma": 2., "action_cost": .002,
          "success_loss_weight": .05, "source_folds": 2, "success_slack": .02}


class SharedHead(nn.Module):
    """Shared trunk predicts positive action moments and success probabilities."""

    def __init__(self, seed):
        super().__init__()
        self.seed = seed
        with torch.random.fork_rng(devices=[]):
            torch.random.set_rng_state(torch.Generator().manual_seed(seed).get_state())
            self.net = nn.Sequential(nn.Linear(COMPACT_DIM, CONFIG["hidden"]), nn.Tanh(), nn.Linear(CONFIG["hidden"], 10))
        self.register_buffer("mean", torch.zeros(COMPACT_DIM))
        self.register_buffer("scale", torch.ones(COMPACT_DIM))

    def forward(self, x):
        value = self.net((x - self.mean) / self.scale)
        return F.softplus(value[:, :5]) + 1e-8, value[:, 5:].sigmoid()


def pick(moment, success, remaining, slack):
    moment = moment.clone()
    if remaining == 1:
        moment[:, 1] = float("inf")
    if slack is not None:
        available = torch.isfinite(moment)
        best_success = success.masked_fill(~available, float("-inf")).max(-1).values
        moment = moment.masked_fill(success < best_success[:, None] - slack, float("inf"))
    if not torch.isfinite(moment.min(-1).values).all():
        raise ValueError("No finite feasible action")
    return moment.argmin(-1)


def fit_head(x, z, success, *, seed, steps):
    wall, cpu = time.perf_counter_ns(), time.process_time_ns()
    if not (torch.isfinite(x).all() and torch.isfinite(z).all() and (z > 0).all()
            and torch.isfinite(success).all() and ((success >= 0) & (success <= 1)).all()):
        raise ValueError("Invalid public examples or offline targets")
    head = SharedHead(seed)
    with torch.no_grad():
        head.mean.copy_(x.mean(0))
        scale = x.std(0, unbiased=False)
        head.scale.copy_(torch.where(scale > 1e-6, scale, torch.ones_like(scale)))
    optimizer = torch.optim.Adam(head.parameters(), lr=CONFIG["learning_rate"])
    rng = torch.Generator().manual_seed(seed + 1)
    trace = []
    groups = [torch.nonzero(x[:, -1] == horizon).flatten() for horizon in (.5, 1.)]
    groups = [group for group in groups if len(group)]
    for step in range(steps):
        ids = torch.cat([group[torch.randint(len(group), (CONFIG["batch_size"] // len(groups),), generator=rng)] for group in groups])
        optimizer.zero_grad(set_to_none=True)
        moment, probability = head(x[ids])
        risk_loss = F.mse_loss(moment, z[ids])
        success_loss = F.binary_cross_entropy(probability, success[ids])
        loss = risk_loss + CONFIG["success_loss_weight"] * success_loss
        if not torch.isfinite(loss):
            raise ValueError("Nonfinite fit")
        loss.backward(); optimizer.step()
        if step == 0 or (step + 1) % 200 == 0:
            trace.append({"step": step + 1, "moment_MSE": float(risk_loss.detach()), "success_BCE": float(success_loss.detach())})
    head.eval().requires_grad_(False)
    return head, {"seed": seed, "steps": steps, "rows": len(x), "trace": trace,
                  "parameters": sum(p.numel() for p in head.parameters()), "parameter_sha256": parameter_hash(head),
                  "wall_ns": time.perf_counter_ns() - wall, "cpu_ns": time.process_time_ns() - cpu}


def first_horizon(public, utility, success):
    x = public.clone(); x[:, 0, -1] = .5
    z, p = torch.empty((len(x), 5, 5)), torch.empty((len(x), 5, 5))
    z[:, 0], p[:, 0] = utility[:, :5], success[:, :5]
    for first in range(4):
        z[:, first + 1, 0], p[:, first + 1, 0] = utility[:, first + 1], success[:, first + 1]
        z[:, first + 1, 1:] = utility[:, 5 + 4 * first:9 + 4 * first]
        p[:, first + 1, 1:] = success[:, 5 + 4 * first:9 + 4 * first]
    costs = torch.tensor([0., *([CONFIG["action_cost"]] * 4)])
    return x.flatten(0, 1), torch.exp(-CONFIG["gamma"] * (z.flatten(0, 1) - costs)), p.flatten(0, 1)


@dataclass
class CompactController:
    head: SharedHead
    report: dict
    slack: float | None = CONFIG["success_slack"]

    @torch.no_grad()
    def choose(self, x, remaining):
        if x.shape[-1] != COMPACT_DIM or remaining not in (1, 2):
            raise ValueError("Wrong compact state or horizon")
        return pick(*self.head(x), remaining, self.slack)

    @torch.no_grad()
    def paths(self, full):
        public = compact_from_full(full)
        first = self.choose(public[:, 0], 2)
        result = torch.zeros(len(first), dtype=torch.long)
        for action in range(1, 5):
            ids = torch.nonzero(first == action).flatten()
            if len(ids):
                second = self.choose(public[ids, action], 1)
                result[ids] = torch.where(second == 0, action, 5 + (action - 1) * 4 + second - 1)
        return result


def fit(data, seed):
    if data["role"] != "forecast_fit" or (data["pair_start"], data["pair_count"]) != (480, 256):
        raise ValueError("Only historical forecast-fit data permitted")
    if tuple(tuple(p) for p in data["plans"]) != PLANS:
        raise ValueError("Unexpected candidate tree")
    public = compact_from_full(data["features"])
    utility = data["metrics"]["primary"]["utility"]
    success = data["metrics"]["primary"]["joint_fact_correct"]
    cases = torch.tensor(data["cases"])
    fold = cases % CONFIG["source_folds"]
    x1, z1, p1 = first_horizon(public, utility, success)
    z2, p2, reports = torch.empty((len(public), 5)), torch.empty((len(public), 5)), []
    for held_fold in range(CONFIG["source_folds"]):
        keep = fold.repeat_interleave(5) != held_fold
        held = fold == held_fold
        head, report = fit_head(x1[keep], z1[keep], p1[keep], seed=seed + held_fold * 100, steps=CONFIG["fold_steps"])
        with torch.no_grad():
            moment, probability = head(public[held, 1:].flatten(0, 1))
            action = pick(moment, probability, 1, CONFIG["success_slack"])
            rows = torch.arange(len(action))
            z2[held] = torch.cat((torch.exp(-CONFIG["gamma"] * utility[held, :1]),
                torch.exp(torch.tensor(CONFIG["gamma"] * CONFIG["action_cost"])) * moment[rows, action].reshape(-1, 4)), 1)
            p2[held] = torch.cat((success[held, :1], probability[rows, action].reshape(-1, 4)), 1)
        report["held_source_fold"] = held_fold
        reports.append(report)
    head, final = fit_head(torch.cat((x1, public[:, 0])), torch.cat((z1, z2)), torch.cat((p1, p2)),
                           seed=seed + 300, steps=CONFIG["steps"])
    return CompactController(head, {"config": CONFIG, "crossfit": reports, "deployed": final,
        "H2_targets": "other-source-fold H1 selected conditional Z and success; not realized-best future",
        "inputs": "384 public generator latent +192 actual token onehot +remaining horizon; no extra CNN",
        "success_constraint_scope": "approximate conditional prediction, not a population guarantee"})


def save(controller, path):
    with path.open("xb") as stream:
        torch.save({"schema": "hepta.abc4.compact-controller.v1", "seed": controller.head.seed,
                    "state_dict": controller.head.state_dict(), "slack": controller.slack, "report": controller.report}, stream)


def load(path):
    value = torch.load(path, weights_only=True, map_location="cpu")
    if value["schema"] != "hepta.abc4.compact-controller.v1":
        raise ValueError("Unknown compact policy schema")
    head = SharedHead(value["seed"]); head.load_state_dict(value["state_dict"])
    return CompactController(head.eval().requires_grad_(False), value["report"], value["slack"])
