"""One initial public-state choice among the 21 registered fixed programs.

The head fits positive exponential moments, never hindsight-best plan labels.
After choosing a plan once, the owner executes that plan without using later
drafts to choose actions. An approximate neural fit is not an optimality proof.
"""

import math

import torch
from torch import nn
from torch.nn import functional as F

from .control import PLANS
from .runtime import FEATURE_DIM


GAMMA = 2.0
ACTION_COST = 0.002


def _features(values):
    result = torch.as_tensor(values, dtype=torch.float32, device="cpu").detach()
    if result.ndim != 2 or result.shape[1] != FEATURE_DIM or len(result) < 1 or not torch.isfinite(result).all():
        raise ValueError("route features must be finite [N,673] public roots")
    if not (result[:, -1] == 1).all():
        raise ValueError("route choice is only defined at the initial H=2 root")
    return result


class PlanCritic(nn.Module):
    """CPU float32 positive-Z head; normalizers are saved in state_dict."""

    def __init__(self, seed, hidden_dim=32):
        super().__init__()
        if not isinstance(seed, int) or not 0 <= seed < 2**63 or not isinstance(hidden_dim, int) or hidden_dim < 1:
            raise ValueError("seed must be in [0,2**63) and hidden_dim a positive integer")
        self.seed, self.hidden_dim = seed, hidden_dim
        self.input_dim, self.gamma, self.action_cost = FEATURE_DIM, GAMMA, ACTION_COST
        initialization = torch.Generator(device="cpu").manual_seed(seed)
        with torch.random.fork_rng(devices=[]):
            torch.random.set_rng_state(initialization.get_state())
            self.network = nn.Sequential(nn.Linear(FEATURE_DIM, hidden_dim, device="cpu", dtype=torch.float32), nn.Tanh(), nn.Linear(hidden_dim, len(PLANS), device="cpu", dtype=torch.float32))
        self.register_buffer("feature_mean", torch.zeros(FEATURE_DIM, device="cpu", dtype=torch.float32))
        self.register_buffer("feature_scale", torch.ones(FEATURE_DIM, device="cpu", dtype=torch.float32))
        self.fit_report = {}

    def forward(self, features):
        raw = self.network((features - self.feature_mean) / self.feature_scale)
        return F.softplus(raw) + torch.finfo(raw.dtype).tiny

    @torch.no_grad()
    def predict(self, root_features):
        predictions = self(_features(root_features))
        if not torch.isfinite(predictions).all() or (predictions <= 0).any():
            raise ValueError("route predictions must be finite positive exponential moments")
        return predictions

    @torch.no_grad()
    def choose(self, root_features):
        """Choose once by deterministic argmin; PLANS order breaks exact ties."""
        return self.predict(root_features).argmin(dim=1)


def fit_route(data, seed, config, action_cost=ACTION_COST):
    """Fit actual primary terminal moments from forecast_fit only.

    config has the same hidden_dim/steps_per_horizon/batch_size/learning_rate
    fields as the feedback fitter. All 21 targets are supervised outcomes, not
    an oracle plan index. The training feature census determines normalization.
    """
    if data.get("role") != "forecast_fit" or tuple(tuple(p) for p in data["plans"]) != PLANS:
        raise ValueError("route fitting requires the registered forecast_fit plan census")
    if action_cost != ACTION_COST:
        raise ValueError("route uses the registered 0.002 action penalty")
    all_features = torch.as_tensor(data["features"], dtype=torch.float32, device="cpu")
    if all_features.ndim != 3 or all_features.shape[1:] != (5, FEATURE_DIM):
        raise ValueError("tree features must be [N,5,673]")
    features = _features(all_features[:, 0]).clone()
    utility = torch.as_tensor(data["metrics"]["primary"]["utility"], dtype=torch.float32, device="cpu").detach()
    if utility.shape != (len(features), len(PLANS)) or not torch.isfinite(utility).all():
        raise ValueError("actual primary utilities must be finite [N,21]")
    lengths = torch.tensor([len(p) for p in PLANS], dtype=torch.float32, device="cpu")
    targets = torch.exp(-GAMMA * (utility - action_cost * lengths))
    if not torch.isfinite(targets).all() or (targets <= 0).any():
        raise ValueError("route targets exceed the finite positive float32 range")
    steps, batch_size, learning_rate = config["steps_per_horizon"], config["batch_size"], config["learning_rate"]
    if not isinstance(steps, int) or steps < 1 or not isinstance(batch_size, int) or batch_size < 1 or not math.isfinite(learning_rate) or learning_rate <= 0:
        raise ValueError("positive steps/batch_size and finite positive learning_rate required")
    model = PlanCritic(seed, config["hidden_dim"])
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
            raise ValueError("route fitting produced a non-finite MSE")
        loss.backward()
        optimizer.step()
        if step == 0 or (step + 1) % max(1, steps // 10) == 0 or step + 1 == steps:
            trace.append({"step": step + 1, "minibatch_mse_before_update": float(loss.detach())})
    model.eval().requires_grad_(False)
    final = float(F.mse_loss(model.predict(features), targets))
    if not math.isfinite(initial) or not math.isfinite(final):
        raise ValueError("route full-data fit MSE is not finite")
    model.fit_report = {"seed": seed, "minibatch_seed": seed + 1, "gamma": GAMMA, "action_penalty": action_cost, "rows": len(features), "input_dim": FEATURE_DIM, "plans": len(PLANS), "hidden_dim": model.hidden_dim, "steps": steps, "batch_size": batch_size, "sampled_rows": steps * batch_size, "learning_rate": learning_rate, "optimizer": "Adam", "objective": "MSE_on_Z", "target": "exp(-2*(actual_primary_utility-0.002*plan_length))", "role": "forecast_fit", "normalization": "training_feature_mean_and_population_std", "initial_full_mse": initial, "final_full_mse": final, "target_min": float(targets.min()), "target_max": float(targets.max()), "trace": trace, "conditional_uniform_error_certified": False, "hindsight_best_plan_labels_used": False}
    return model


def save_route(model, path):
    if not isinstance(model, PlanCritic):
        raise TypeError("expected a PlanCritic")
    with open(path, "xb") as stream:
        torch.save({"schema": "hepta.abc.one-shot-route.v1", "config": {"seed": model.seed, "hidden_dim": model.hidden_dim}, "gamma": GAMMA, "action_penalty": ACTION_COST, "plans": PLANS, "state_dict": model.state_dict(), "fit_report": model.fit_report}, stream)


def load_route(path):
    record = torch.load(path, map_location="cpu", weights_only=True)
    if record["schema"] != "hepta.abc.one-shot-route.v1" or record["gamma"] != GAMMA or record["action_penalty"] != ACTION_COST or tuple(tuple(p) for p in record["plans"]) != PLANS:
        raise ValueError("unregistered saved route profile")
    model = PlanCritic(**record["config"])
    model.load_state_dict(record["state_dict"], strict=True)
    if not all(torch.isfinite(value).all() for value in model.state_dict().values()) or (model.feature_scale <= 0).any():
        raise ValueError("invalid saved route weights or feature normalization")
    model.fit_report = record["fit_report"]
    return model.eval().requires_grad_(False)
