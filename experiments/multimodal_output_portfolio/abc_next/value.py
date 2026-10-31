"""Source-cross-fitted conditional moments and matched one-shot controls.

All heads regress positive exponential moments. Out-of-fold first-horizon
predictions produce second-horizon targets; no realized best grandchild is a
Bellman label. These finite neural regressions have no optimality certificate.
"""

from dataclasses import dataclass
import json
import math

import torch
from torch import nn
from torch.nn import functional as F

from ..abc_recovery.control import PLANS
from ..abc_recovery.critic import terminal_targets
from ..v6.neural import parameter_hash
from ..v7.data import VIEWS
from .settings import MANIFEST


GAMMA, ACTION_COST = 2., .002
CONFIG = {"steps": 600, "batch_size": 256, "learning_rate": .003,
          "folds": 2, "fold_unit": "source_pair", "normalization": "fit_only"}
CANDIDATES = (("base", 32), ("base", 128), ("enriched", 32), ("enriched", 128))
DOMINATED_PLANS = tuple(i for i, plan in enumerate(PLANS) if plan and plan[-1] == "refine_semantic")


def features(values, mode):
    if values.shape[-1] != 763 or mode not in {"base", "enriched"}:
        raise ValueError("Expected enriched public features and registered mode")
    return values if mode == "enriched" else torch.cat((values[..., :672], values[..., -1:]), -1)


class MomentHead(nn.Module):
    """Frozen normalizers and a small positive conditional-moment approximator."""

    def __init__(self, input_dim, outputs, hidden, seed):
        super().__init__()
        self.config = dict(input_dim=input_dim, outputs=outputs, hidden=hidden, seed=seed)
        with torch.random.fork_rng(devices=[]):
            torch.random.set_rng_state(torch.Generator().manual_seed(seed).get_state())
            self.network = nn.Sequential(nn.Linear(input_dim, hidden), nn.Tanh(), nn.Linear(hidden, outputs))
        self.register_buffer("mean", torch.zeros(input_dim))
        self.register_buffer("scale", torch.ones(input_dim))

    def forward(self, value):
        return F.softplus(self.network((value - self.mean) / self.scale)) + 1e-8


def fit_head(x, y, *, hidden, seed):
    if x.ndim != 2 or y.ndim != 2 or len(x) != len(y) or not len(x):
        raise ValueError("Nonempty paired feature and moment matrices required")
    if not torch.isfinite(x).all() or not torch.isfinite(y).all() or (y <= 0).any():
        raise ValueError("Invalid public features or exponential targets")
    head = MomentHead(x.shape[1], y.shape[1], hidden, seed)
    with torch.no_grad():
        head.mean.copy_(x.mean(0))
        scale = x.std(0, unbiased=False)
        head.scale.copy_(torch.where(scale > 1e-6, scale, torch.ones_like(scale)))
    optimizer = torch.optim.Adam(head.parameters(), lr=CONFIG["learning_rate"])
    rng = torch.Generator().manual_seed(seed + 1)
    with torch.no_grad():
        initial = float(F.mse_loss(head(x), y))
    trace = []
    for step in range(CONFIG["steps"]):
        ids = torch.randint(len(x), (min(CONFIG["batch_size"], len(x)),), generator=rng)
        optimizer.zero_grad(set_to_none=True)
        loss = F.mse_loss(head(x[ids]), y[ids])
        if not torch.isfinite(loss):
            raise ValueError("Nonfinite conditional value fit")
        loss.backward()
        optimizer.step()
        if step == 0 or (step + 1) % 100 == 0:
            trace.append({"step": step + 1, "minibatch_MSE": float(loss.detach())})
    head.eval().requires_grad_(False)
    with torch.no_grad():
        final = float(F.mse_loss(head(x), y))
    if not math.isfinite(final) or any(not torch.isfinite(p).all() for p in head.state_dict().values()):
        raise ValueError("Nonfinite final conditional-value model")
    return head, {"config": head.config, "fit": CONFIG, "rows": len(x), "trace": trace,
                  "initial_full_MSE": initial, "final_full_MSE": final,
                  "parameter_sha256": parameter_hash(head), "objective": "MSE_on_Z"}


@dataclass
class Controller:
    mode: str
    hidden: int
    one: MomentHead
    two: MomentHead
    route: MomentHead
    report: dict

    @torch.no_grad()
    def choose(self, public, remaining):
        if remaining not in (1, 2):
            raise ValueError("Horizon must be 1 or 2")
        prediction = (self.one if remaining == 1 else self.two)(features(public, self.mode))
        if not torch.isfinite(prediction).all() or (prediction <= 0).any():
            raise ValueError("Invalid deployed moment prediction")
        if remaining == 1:
            # Semantic updates no emitted content at H1 and costs .002; stop
            # strictly dominates it for every target and every future draw.
            prediction[:, 1] = float("inf")
        return prediction.argmin(-1)

    @torch.no_grad()
    def choose_plan(self, public):
        prediction = self.route(features(public, self.mode))
        if not torch.isfinite(prediction).all() or (prediction <= 0).any():
            raise ValueError("Invalid deployed route moment prediction")
        prediction[:, DOMINATED_PLANS] = float("inf")
        return prediction.argmin(-1)

    @torch.no_grad()
    def paths(self, public):
        first = self.choose(public[:, 0], 2)
        result = torch.zeros(len(first), dtype=torch.long)
        for action in range(1, 5):
            ids = torch.nonzero(first == action).flatten()
            if len(ids):
                second = self.choose(public[ids, action], 1)
                result[ids] = torch.where(second == 0, action, 5 + (action - 1) * 4 + second - 1)
        return result


def one_step_examples(public, utility):
    x = public.clone()
    x[:, 0, -1] = .5
    y = torch.empty((len(x), 5, 5))
    y[:, 0] = utility[:, :5]
    for first in range(4):
        y[:, first + 1, 0] = utility[:, first + 1]
        y[:, first + 1, 1:] = utility[:, 5 + 4 * first:9 + 4 * first]
    return x.flatten(0, 1), terminal_targets(y.flatten(0, 1), GAMMA, ACTION_COST)


def fit_controller(data, mode, hidden, seed):
    if data["role"] != "forecast_fit" or (mode, hidden) not in CANDIDATES:
        raise ValueError("Unregistered source role or architecture")
    if (data.get("pair_start"), data.get("pair_count"), data.get("scenarios_per_source")) != (480, 256, 2):
        raise ValueError("Wrong forecast-fit source interval")
    if tuple(tuple(plan) for plan in data["plans"]) != PLANS:
        raise ValueError("Candidate plan order differs")
    expected = {(case, view, scenario) for case in range(480, 736) for view in VIEWS for scenario in range(2)}
    census = list(zip(data["cases"], data["views"], data["scenarios"]))
    if len(census) != len(expected) or set(census) != expected or len(data["source_ids"]) != len(census):
        raise ValueError("Incomplete or duplicated source/view/scenario census")
    registered = json.loads(MANIFEST.read_text())["roles"]["forecast_fit"]["source_ids"]
    if any(tuple(ids) != tuple(registered[2 * case:2 * case + 2]) for case, ids in zip(data["cases"], data["source_ids"])):
        raise ValueError("Cases do not bind the registered source identities")
    if data["features"].shape != (4096, 5, 763) or data["metrics"]["primary"]["utility"].shape != (4096, 21):
        raise ValueError("Wrong feature or outcome census")
    public = features(data["features"], mode)
    utility = data["metrics"]["primary"]["utility"]
    cases = torch.tensor(data["cases"], dtype=torch.long)
    folds = cases % CONFIG["folds"]
    if len(torch.unique(cases)) < 2 or set(folds.tolist()) != {0, 1}:
        raise ValueError("Both source folds must be populated")
    x, y = one_step_examples(public, utility)
    repeated_folds = folds.repeat_interleave(5)
    backups = torch.empty((len(public), 5))
    reports = []
    for fold in range(2):
        keep, held = repeated_folds != fold, folds == fold
        one, report = fit_head(x[keep], y[keep], hidden=hidden, seed=seed + 100 * fold)
        with torch.no_grad():
            predicted = one(public[held, 1:].flatten(0, 1)).reshape(-1, 4, 5)
            predicted[:, :, 1] = float("inf")
            continuation = predicted.min(-1).values
            backups[held] = torch.cat((torch.exp(-GAMMA * utility[held, :1]),
                                      torch.exp(torch.tensor(GAMMA * ACTION_COST)) * continuation), 1)
        report.update({"held_source_fold": fold, "fit_unique_sources": len(torch.unique(cases[folds != fold])),
                       "held_unique_sources": len(torch.unique(cases[held]))})
        reports.append(report)
    one, one_report = fit_head(x, y, hidden=hidden, seed=seed + 300)
    two, two_report = fit_head(public[:, 0], backups, hidden=hidden, seed=seed + 400)
    lengths = torch.tensor([len(plan) for plan in PLANS])
    route, route_report = fit_head(public[:, 0], torch.exp(-GAMMA * (utility - ACTION_COST * lengths)),
                                   hidden=hidden, seed=seed + 500)
    report = {"mode": mode, "hidden": hidden, "seed": seed, "cross_fit_heads": reports,
              "deployed_one_step": one_report, "deployed_two_step": two_report, "one_shot": route_report,
              "backup": "source_out_of_fold_Q1_min_on_actual_observed_child",
              "all_source_views_and_scenarios_share_fold": True,
              "H1_semantic_strict_dominance_enforced_for_all_candidates": True,
              "H2_semantic_is_available": True,
              "deployed_Q1_refit_differs_from_fold_heads": True,
              "grandchild_realized_best_labels_used": False, "conditional_uniform_error_certified": False}
    return Controller(mode, hidden, one, two, route, report)


def save_controller(controller, path):
    with path.open("xb") as stream:
        torch.save({"schema": "hepta.abc-next.crossfit-value.v1", "mode": controller.mode,
                    "hidden": controller.hidden, "report": controller.report,
                    "heads": [{"config": h.config, "state_dict": h.state_dict()}
                              for h in (controller.one, controller.two, controller.route)]}, stream)


def load_controller(path):
    record = torch.load(path, map_location="cpu", weights_only=True)
    if record["schema"] != "hepta.abc-next.crossfit-value.v1":
        raise ValueError("Unknown controller schema")
    heads = []
    for saved in record["heads"]:
        head = MomentHead(**saved["config"])
        head.load_state_dict(saved["state_dict"])
        heads.append(head.eval().requires_grad_(False))
    return Controller(record["mode"], record["hidden"], *heads, record["report"])
