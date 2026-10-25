"""Offline fitted, approximate H=2 control; public-feature-only greedy inference.

Gamma>0 heads fit positive Z itself by MSE, never a log-target. Gamma=0
heads fit expected remaining cost minus utility. A two-step target uses the
frozen one-step head on actual sampled child features, not realized best
grandchildren. The model and these backups carry no optimality certificate.
"""

import math

import torch
from torch import nn
from torch.nn import functional as F


ACTIONS = ("stop", "refine_semantic", "refine_image", "refine_text", "couple")


def _profile(gamma):
    gamma = float(gamma)
    if not math.isfinite(gamma) or gamma < 0:
        raise ValueError("gamma must be finite and nonnegative")
    return gamma


def _features(values, dimension=None):
    result = torch.as_tensor(values, dtype=torch.float32, device="cpu").detach()
    if result.ndim != 2 or min(result.shape) < 1 or (dimension is not None and result.shape[1] != dimension):
        raise ValueError("features must be a nonempty [N,D] matrix with the fitted dimension")
    if not torch.isfinite(result).all():
        raise ValueError("features must be finite")
    return result


def _costs(values, rows):
    result = torch.as_tensor(values, dtype=torch.float32, device="cpu").detach()
    if result.ndim == 0:
        result = result.expand(rows, 4)
    elif result.shape == (4,):
        result = result.unsqueeze(0).expand(rows, 4)
    if result.shape != (rows, 4) or not torch.isfinite(result).all() or (result < 0).any():
        raise ValueError("action_costs must be finite nonnegative scalar, [4], or [N,4]")
    return result


def _mask(values, shape):
    result = torch.as_tensor(values, device="cpu")
    if result.dtype != torch.bool or tuple(result.shape) != tuple(shape) or not result.any(dim=-1).all():
        raise ValueError("feasible_mask must be boolean, correctly shaped, with a feasible action per row")
    return result


def terminal_targets(utilities, gamma, action_costs=0.002):
    """Offline one-step targets from actual utilities [N,5]; stop always costs 0."""
    gamma = _profile(gamma)
    utilities = _features(utilities, len(ACTIONS))
    costs = torch.cat((torch.zeros(len(utilities), 1, dtype=torch.float32, device="cpu"), _costs(action_costs, len(utilities))), dim=1)
    losses = costs - utilities
    targets = losses if gamma == 0 else torch.exp(gamma * losses)
    if not torch.isfinite(targets).all() or (gamma > 0 and (targets <= 0).any()):
        raise ValueError("terminal targets overflowed or underflowed the finite positive float32 range")
    return targets


class ActionCritic(nn.Module):
    """A CPU float32 head for one fixed remaining horizon and risk profile.

    Construct from input_dim/gamma/remaining/seed/hidden_dim, then load state_dict
    for inference. Feature normalization is part of that state_dict. fit_report
    is aggregate training metadata and should be saved separately by the caller.
    """

    def __init__(self, input_dim, gamma, remaining, seed, hidden_dim=32):
        super().__init__()
        if remaining not in (1, 2) or not isinstance(input_dim, int) or input_dim < 1 or not isinstance(hidden_dim, int) or hidden_dim < 1:
            raise ValueError("remaining must be 1 or 2 and network dimensions positive integers")
        if not isinstance(seed, int) or not 0 <= seed < 2**63:
            raise ValueError("seed must be an integer in [0, 2**63)")
        self.input_dim, self.gamma, self.remaining = input_dim, _profile(gamma), remaining
        self.seed, self.hidden_dim = seed, hidden_dim
        # Only CPU RNG is forked and seeded; caller's streams are unchanged.
        initialization = torch.Generator(device="cpu").manual_seed(seed)
        with torch.random.fork_rng(devices=[]):
            torch.random.set_rng_state(initialization.get_state())
            self.network = nn.Sequential(nn.Linear(input_dim, hidden_dim, dtype=torch.float32, device="cpu"), nn.Tanh(), nn.Linear(hidden_dim, len(ACTIONS), dtype=torch.float32, device="cpu"))
        self.register_buffer("feature_mean", torch.zeros(input_dim, dtype=torch.float32, device="cpu"))
        self.register_buffer("feature_scale", torch.ones(input_dim, dtype=torch.float32, device="cpu"))
        self.fit_report = {}

    def forward(self, features):
        raw = self.network((features - self.feature_mean) / self.feature_scale)
        return raw if self.gamma == 0 else F.softplus(raw) + torch.finfo(raw.dtype).tiny

    @torch.no_grad()
    def predict(self, features):
        values = self(_features(features, self.input_dim))
        if not torch.isfinite(values).all() or (self.gamma > 0 and (values <= 0).any()):
            raise ValueError("critic prediction is not finite or has an invalid exponential moment")
        return values


def _fit(features, targets, seed, steps, gamma, remaining, hidden_dim, learning_rate, batch_size):
    features = _features(features).clone()
    targets = torch.as_tensor(targets, dtype=torch.float32, device="cpu").detach().clone()
    gamma = _profile(gamma)
    if targets.shape != (len(features), len(ACTIONS)) or not torch.isfinite(targets).all() or (gamma > 0 and (targets <= 0).any()):
        raise ValueError("targets must be finite [N,5] and strictly positive for gamma>0")
    if not isinstance(steps, int) or steps < 1 or not isinstance(batch_size, int) or batch_size < 1 or not math.isfinite(learning_rate) or learning_rate <= 0:
        raise ValueError("steps/batch_size must be positive integers and learning_rate finite positive")
    model = ActionCritic(features.shape[1], gamma, remaining, seed, hidden_dim)
    with torch.no_grad():
        model.feature_mean.copy_(features.mean(dim=0))
        scale = features.std(dim=0, unbiased=False)
        model.feature_scale.copy_(torch.where(scale > 1e-6, scale, torch.ones_like(scale)))
    initial = float(F.mse_loss(model.predict(features), targets))
    optimizer = torch.optim.Adam(model.parameters(), lr=learning_rate)
    generator = torch.Generator(device="cpu").manual_seed(seed + 1)
    batch_size = min(batch_size, len(features))
    trace = []
    for step in range(steps):
        indices = torch.arange(len(features), device="cpu") if batch_size == len(features) else torch.randint(len(features), (batch_size,), generator=generator, device="cpu")
        optimizer.zero_grad(set_to_none=True)
        loss = F.mse_loss(model(features[indices]), targets[indices])
        if not torch.isfinite(loss):
            raise ValueError("critic fit produced a non-finite MSE")
        loss.backward()
        optimizer.step()
        if step == 0 or (step + 1) % max(1, steps // 10) == 0 or step + 1 == steps:
            trace.append({"step": step + 1, "minibatch_mse_before_update": float(loss.detach())})
    model.eval()
    final = float(F.mse_loss(model.predict(features), targets))
    if not math.isfinite(initial) or not math.isfinite(final):
        raise ValueError("critic full-data fit MSE is not finite")
    model.fit_report = {"gamma": gamma, "remaining": remaining, "seed": seed, "minibatch_seed": seed + 1, "steps": steps, "batch_size": batch_size, "rows": len(features), "sampled_rows": steps * batch_size, "input_dim": model.input_dim, "hidden_dim": hidden_dim, "learning_rate": learning_rate, "optimizer": "Adam", "objective": "MSE_on_Z" if gamma > 0 else "MSE_on_cost_minus_utility", "normalization": "training_feature_mean_and_population_std", "initial_full_mse": initial, "final_full_mse": final, "target_min": float(targets.min()), "target_max": float(targets.max()), "trace": trace}
    return model


def fit_one_step(features, targets, seed, steps, *, gamma=2.0, hidden_dim=32, batch_size=256, learning_rate=0.003):
    """Fit explicit offline [N,5] targets; include root and child one-step states.

    The caller controls source groups and constructs targets from actual emitted
    utilities. No source independence or target provenance is inferred here.
    """
    return _fit(features, targets, seed, steps, gamma, 1, hidden_dim, learning_rate, batch_size)


@torch.no_grad()
def bootstrap_two_step_targets(stop_utility, child_features, one_step_model, action_costs=0.002, child_feasible_mask=None):
    """Offline sampled-child backup; no realized grandchild utilities are accepted.

    Each row's four child states are actual first-action outcomes. Their costs
    remain paired with their frozen predicted continuation values. Multiple
    stochastic rows may share a root; regression, not this minimum, averages
    those first-action outcomes. The minimum is over feasible next actions only.
    """
    if not isinstance(one_step_model, ActionCritic) or one_step_model.remaining != 1:
        raise ValueError("backup requires a one-step ActionCritic")
    children = torch.as_tensor(child_features, dtype=torch.float32, device="cpu").detach()
    stop = torch.as_tensor(stop_utility, dtype=torch.float32, device="cpu").detach()
    if children.ndim != 3 or children.shape[1:] != (4, one_step_model.input_dim) or len(children) < 1 or stop.shape != (len(children),) or not torch.isfinite(stop).all():
        raise ValueError("child_features must be [N,4,D] and stop_utility finite [N]")
    predictions = one_step_model.predict(children.reshape(-1, one_step_model.input_dim)).reshape(len(children), 4, len(ACTIONS))
    if child_feasible_mask is not None:
        predictions = predictions.masked_fill(~_mask(child_feasible_mask, predictions.shape), float("inf"))
    continuation = predictions.min(dim=-1).values
    costs = _costs(action_costs, len(children))
    gamma = one_step_model.gamma
    if gamma == 0:
        targets = torch.cat((-stop[:, None], costs + continuation), dim=1)
    else:
        targets = torch.cat((torch.exp(-gamma * stop[:, None]), torch.exp(gamma * costs) * continuation), dim=1)
    if not torch.isfinite(targets).all() or (gamma > 0 and (targets <= 0).any()):
        raise ValueError("two-step targets are not finite valid moments/costs")
    return targets.detach()


def fit_two_step(root_features, stop_utility, child_features, one_step_model, seed, steps, *, gamma=None, action_costs=0.002, child_feasible_mask=None, hidden_dim=32, batch_size=256, learning_rate=0.003):
    """Fit approximate DP using a fixed Q1 prediction backup, never a future oracle."""
    if not isinstance(one_step_model, ActionCritic):
        raise ValueError("one_step_model must be an ActionCritic")
    if gamma is not None and _profile(gamma) != one_step_model.gamma:
        raise ValueError("both remaining horizons must use the same fixed gamma")
    roots = _features(root_features, one_step_model.input_dim)
    targets = bootstrap_two_step_targets(stop_utility, child_features, one_step_model, action_costs, child_feasible_mask)
    model = _fit(roots, targets, seed, steps, one_step_model.gamma, 2, hidden_dim, learning_rate, batch_size)
    model.fit_report["backup"] = "frozen_Q1_minimum_on_actual_child_features"
    model.fit_report["realized_grandchild_labels_used"] = False
    return model


class FiniteHorizonCritic:
    """Public inference uses features, remaining horizon, and feasible mask only."""

    def __init__(self, one_step_model, two_step_model):
        if not isinstance(one_step_model, ActionCritic) or not isinstance(two_step_model, ActionCritic) or (one_step_model.remaining, two_step_model.remaining) != (1, 2) or one_step_model.gamma != two_step_model.gamma or one_step_model.input_dim != two_step_model.input_dim:
            raise ValueError("heads must have matching dimensions/gamma and horizons 1,2")
        self.one_step_model, self.two_step_model = one_step_model, two_step_model

    @torch.no_grad()
    def action_values(self, features, remaining, feasible_mask):
        features = _features(features, self.one_step_model.input_dim)
        counts = torch.as_tensor(remaining, device="cpu")
        if counts.ndim == 0:
            counts = counts.expand(len(features))
        if counts.shape != (len(features),) or ((counts != 1) & (counts != 2)).any():
            raise ValueError("remaining must be 1 or 2, scalar or [N]")
        mask = _mask(feasible_mask, (len(features), len(ACTIONS)))
        result = torch.empty(len(features), len(ACTIONS), dtype=torch.float32, device="cpu")
        for horizon, model in ((1, self.one_step_model), (2, self.two_step_model)):
            rows = counts == horizon
            if rows.any():
                result[rows] = model.predict(features[rows])
        return result.masked_fill(~mask, float("inf"))

    def select_actions(self, features, remaining, feasible_mask):
        """Deterministic argmin, with ACTIONS order breaking exact ties."""
        return self.action_values(features, remaining, feasible_mask).argmin(dim=1)
