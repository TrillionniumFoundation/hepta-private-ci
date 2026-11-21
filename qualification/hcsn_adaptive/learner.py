"""Six readout learners under one eligible parameter mask and cost ledger.

ProgrammaticEdit is a deterministic residual-correlation coordinate baseline.
It does not reproduce MIT agent-discovered weight-space programming. Ridge is
closed form only because features are frozen. No claim is made for nonlinear
representation learning without backpropagation.
"""

from dataclasses import asdict, dataclass
import hashlib
import json
from pathlib import Path
import platform
import random
import time

import numpy as np
import torch
from torch import nn
from torch.nn.utils import parameters_to_vector, vector_to_parameters

from .budget import BudgetExhausted, CostLedger
from .checkpoint import load_checkpoint, save_checkpoint


METHODS = ("frozen", "ridge", "bp", "zeroth_order", "programmatic_edit", "edit_then_bp")


@dataclass(frozen=True)
class LearnerConfig:
    steps: int = 64
    batch_size: int = 64
    evaluate_every: int = 8
    learning_rate: float = 0.02
    ridge: float = 0.001
    perturbation: float = 0.01
    trust_radius: float = 0.25
    minimum_dev_gain: float = 1e-12

    def __post_init__(self):
        if (min(self.steps, self.batch_size, self.evaluate_every) < 1
                or min(self.learning_rate, self.ridge, self.perturbation, self.trust_radius) <= 0
                or self.minimum_dev_gain < 0):
            raise ValueError("invalid learner configuration")


def _synchronize(tensor):
    if tensor.is_cuda:
        torch.cuda.synchronize(tensor.device)


def _loss(model, features, targets):
    loss = (model(features) - targets).square().mean()
    if not torch.isfinite(loss):
        raise FloatingPointError("nonfinite learner loss")
    return loss


def _objective(model, features, targets, weight_penalty):
    """Common training objective; development selection retains plain task MSE."""
    return _loss(model, features, targets) + weight_penalty * model.weight.square().sum()


def _ridge(model, x, y, regularizer):
    design = torch.cat((x, torch.ones_like(x[:, :1])), dim=1)
    penalty = torch.eye(design.shape[1], dtype=x.dtype, device=x.device) * regularizer
    penalty[-1, -1] = 0  # The common bias is not penalized.
    weights = torch.linalg.solve(design.T @ design + penalty, design.T @ y)
    model.weight.copy_(weights[:-1].T)
    model.bias.copy_(weights[-1])


def _programmatic_edit(model, x, y, radius, ridge_penalty):
    design = torch.cat((x, torch.ones_like(x[:, :1])), dim=1)
    residual = y - model(x)
    penalty = design.new_full((design.shape[1],), ridge_penalty)
    penalty[-1] = 0
    current = torch.cat((model.weight.T, model.bias[None]), 0)
    norm = (design.square().sum(0) + penalty).clamp_min(torch.finfo(x.dtype).eps)
    correlation = design.T @ residual - penalty[:, None] * current
    # Best one-coordinate least-squares decrease in the declared readout basis.
    scores = correlation.square() / norm[:, None]
    flat = int(scores.argmax())
    coordinate, output = flat // y.shape[1], flat % y.shape[1]
    delta = (correlation[coordinate, output] / norm[coordinate]).clamp(-radius, radius)
    if coordinate == x.shape[1]:
        model.bias[output].add_(delta)
    else:
        model.weight[output, coordinate].add_(delta)


def _zero_order(model, x, y, generator, config, weight_penalty):
    base = parameters_to_vector(model.parameters()).detach().clone()
    direction = (torch.randint(0, 2, base.shape, generator=generator) * 2 - 1).to(base)
    vector_to_parameters(base + config.perturbation * direction, model.parameters())
    plus = _objective(model, x, y, weight_penalty)
    vector_to_parameters(base - config.perturbation * direction, model.parameters())
    minus = _objective(model, x, y, weight_penalty)
    delta = -config.learning_rate * (plus - minus) / (2 * config.perturbation) * direction
    delta *= min(1.0, config.trust_radius / max(float(delta.norm()), 1e-30))
    vector_to_parameters(base + delta, model.parameters())


def fit_readout(train_x, train_y, dev_x, dev_y, *, method, seed, budget,
                directory, identity, config=None, resume=False, stop_after=None):
    """Return the dev-selected model and report; no final-test data are accepted."""
    started = time.perf_counter()
    if method not in METHODS:
        raise ValueError("unknown learner")
    config = config or LearnerConfig()
    tensors = (train_x, train_y, dev_x, dev_y)
    if any(t.requires_grad for t in tensors):
        raise ValueError("frozen features and targets must have requires_grad=False")
    if (train_x.ndim != 2 or train_y.ndim != 2 or dev_x.ndim != 2 or dev_y.ndim != 2
            or len(train_x) != len(train_y) or len(dev_x) != len(dev_y)
            or train_x.shape[1] != dev_x.shape[1] or train_y.shape[1] != dev_y.shape[1]
            or min(len(train_x), len(dev_x)) < 1
            or any(t.dtype != train_x.dtype or t.device != train_x.device for t in tensors)
            or any(not torch.isfinite(t).all() for t in tensors)):
        raise ValueError("finite nonempty train/dev feature and target matrices required")
    binding = {"requested_identity": identity, "seed": seed, "method": method,
               "config": asdict(config), "mask": ["readout.weight", "readout.bias"],
               "runtime": [platform.python_version(), str(torch.__version__), np.__version__,
                           str(train_x.device), str(train_x.dtype)],
               "data": [hashlib.sha256(str(tuple(t.shape)).encode()
                                       + t.cpu().contiguous().numpy().tobytes()).hexdigest()
                        for t in tensors],
               "code": {name: hashlib.sha256(Path(__file__).with_name(name).read_bytes()).hexdigest()
                        for name in ("learner.py", "budget.py", "checkpoint.py")}}
    effective_identity = hashlib.sha256(json.dumps(binding, sort_keys=True).encode()).hexdigest()
    directory = Path(directory)
    checkpoint = directory / "checkpoint.pt"
    if directory.exists() and (directory / "cost.jsonl").exists() and not resume:
        raise FileExistsError("existing attempt requires explicit resume")
    ledger = CostLedger(directory / "cost.jsonl", budget, effective_identity, started_at=started)
    random.seed(seed)
    np.random.seed(seed % 2**32)
    torch.manual_seed(seed)
    model = nn.Linear(train_x.shape[1], train_y.shape[1]).to(train_x)
    optimizer = torch.optim.Adam(model.parameters(), lr=config.learning_rate)
    generator = torch.Generator(device="cpu").manual_seed(seed ^ 0x5EED)
    controller = dict(step=0, best_step=0, best_dev=None, initial_dev=None,
                      best_state={key: value.detach().clone() for key, value in model.state_dict().items()},
                      status="running", method=method, config=asdict(config), history=[],
                      seed=seed, recovery_discarded_operations=0)
    if resume:
        controller = load_checkpoint(checkpoint, identity=effective_identity, model=model,
                                     optimizer=optimizer, generator=generator, ledger=ledger)
        if (controller["method"] != method or controller["config"] != asdict(config)
                or controller["seed"] != seed):
            raise ValueError("learner method or configuration changed on resume")
    def save():
        save_checkpoint(checkpoint, identity=effective_identity, model=model, optimizer=optimizer,
                        controller=controller, generator=generator, ledger=ledger)

    def evaluate():
        with ledger.operation("development_selection", forward_examples=len(dev_x),
                              development_queries=1), torch.no_grad():
            value = float(_loss(model, dev_x, dev_y))
            if controller["initial_dev"] is None:
                controller["initial_dev"] = value
            if controller["best_dev"] is None or value < controller["best_dev"] - config.minimum_dev_gain:
                controller["best_dev"] = value
                controller["best_step"] = controller["step"]
                controller["best_state"] = {key: tensor.detach().clone()
                                             for key, tensor in model.state_dict().items()}
            controller["history"].append({"step": controller["step"], "dev_mse": value})
            _synchronize(train_x)

    maximum_steps = 0 if method == "frozen" else (1 if method == "ridge" else config.steps)
    weight_penalty = config.ridge / (len(train_x) * train_y.shape[1])
    try:
        if controller["initial_dev"] is None:
            evaluate()
            save()
        while controller["step"] < maximum_steps and controller["status"] in ("running", "paused"):
            if stop_after is not None and controller["step"] >= stop_after:
                controller["status"] = "paused"
                save()
                break
            controller["status"] = "running"
            phase = ("programmatic_edit" if method == "edit_then_bp"
                     and controller["step"] < config.steps // 2 else
                     ("bp" if method == "edit_then_bp" else method))
            batch = len(train_x) if phase in ("ridge", "programmatic_edit") else min(
                config.batch_size, len(train_x))
            forwards = 0 if phase == "ridge" else batch * (2 if phase == "zeroth_order" else 1)
            with ledger.operation(phase, training_examples=max(batch, forwards),
                                  forward_examples=forwards,
                                  backward_examples=batch if phase == "bp" else 0, proposals=1):
                indices = (torch.arange(len(train_x)) if batch == len(train_x) else
                           torch.randperm(len(train_x), generator=generator)[:batch]).to(train_x.device)
                x, y = train_x[indices], train_y[indices]
                if phase == "bp":
                    optimizer.zero_grad(set_to_none=True)
                    _objective(model, x, y, weight_penalty).backward()
                    nn.utils.clip_grad_norm_(model.parameters(), config.trust_radius)
                    optimizer.step()
                else:
                    with torch.no_grad():
                        if phase == "ridge":
                            _ridge(model, x, y, config.ridge)
                        elif phase == "programmatic_edit":
                            _programmatic_edit(model, x, y, config.trust_radius, config.ridge)
                        else:
                            _zero_order(model, x, y, generator, config, weight_penalty)
                if not all(torch.isfinite(parameter).all() for parameter in model.parameters()):
                    raise FloatingPointError("nonfinite learner parameters")
                _synchronize(train_x)
            controller["step"] += 1
            if controller["step"] % config.evaluate_every == 0 or controller["step"] == maximum_steps:
                evaluate()
            save()
        if controller["status"] == "running":
            controller["status"] = "completed"
    except BudgetExhausted as exc:
        controller.update(status="budget_exhausted", stop_reason=str(exc))
    except (RuntimeError, FloatingPointError) as exc:
        controller.update(status="failed", stop_reason=type(exc).__name__ + ": " + str(exc))
    save()
    model.load_state_dict(controller["best_state"])
    report = {key: value for key, value in controller.items() if key != "best_state"}
    report.update(identity=effective_identity, binding=binding, seed=seed, cost=ledger.snapshot(),
                  outcome=("Unavailable" if controller["best_dev"] is None else
                           ("NoUpdate" if controller["best_step"] == 0 else "Candidate")),
                  eligible_parameter_mask=["readout.weight", "readout.bias"],
                  eligible_parameters=sum(parameter.numel() for parameter in model.parameters()),
                  training_objective={"task": "mean_squared_error", "ridge_lambda": config.ridge,
                                      "weight_penalty_coefficient": weight_penalty, "bias_penalized": False},
                  features_frozen=True,
                  editing_claim="deterministic coordinate baseline; not an agent-discovered MIT reproduction")
    return model, report
