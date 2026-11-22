"""Variable projection keeps encoder BP and solves only the linear readout.

For fixed training normalization and positive ridge, the conditional minimizer
is unique. The envelope derivative differentiates the objective with respect to
the encoder while holding that minimizer fixed. Operators are rebuilt whenever
encoder weights change; there is no cross-weight action or feature cache.
"""

import time

import torch

from qualification.hcsn_confirmatory_v1.joint import OUTER, build
from qualification.hcsn_confirmatory_v1.run import features

from .representation import fit_scaler, ridge_fit


def install_readout(model, fitted):
    with torch.no_grad():
        model.readout.weight.copy_(fitted["weight"][None])
        model.readout.bias.copy_(fitted["bias"].reshape(1))


def prepare(task, train, floor, ridge):
    model = build(task)
    x, names = features(model.flow, train)
    scaler = fit_scaler(x, "bounded_floor", floor)
    with torch.no_grad():
        model.mean.copy_(scaler["mean"])
        model.scale.copy_(scaler["scale"])
    x = (x - model.mean) / model.scale
    fitted = ridge_fit(x, torch.from_numpy(train["y"]), ridge=ridge)
    install_readout(model, fitted)
    return model, scaler, names


def parameter_mode(model, method):
    eligible = tuple("flow." + name for name in OUTER)
    if method == "joint_bp":
        eligible += ("readout.weight", "readout.bias")
    elif method not in ("profile_bp", "program_profile_bp"):
        raise ValueError("unknown outer adaptation method")
    for name, parameter in model.named_parameters():
        parameter.requires_grad_(name in eligible)
    return eligible


def forward_loss(model, data, ridge, profile):
    """Return the objective and separately measured conditional-solve cost."""
    start = time.perf_counter()
    x, _ = features(model.flow, data, grad=torch.is_grad_enabled())
    x = (x - model.mean) / model.scale
    y = torch.from_numpy(data["y"][:, 0])
    feature_seconds = time.perf_counter() - start
    solve_seconds = 0.0
    if profile:
        start = time.perf_counter()
        with torch.no_grad():
            fitted = ridge_fit(x.detach(), y, ridge=ridge)
            install_readout(model, fitted)
        solve_seconds = time.perf_counter() - start
    prediction = model.readout(x).squeeze(-1)
    loss = (prediction - y).square().mean() + ridge / len(
        x
    ) * model.readout.weight.square().sum()
    if not bool(torch.isfinite(loss)):
        raise FloatingPointError("nonfinite outer adaptation objective")
    return loss, {
        "feature_seconds": feature_seconds,
        "conditional_solve_seconds": solve_seconds,
        "conditional_solves": int(profile),
        "forward_rows": len(x),
    }


def backward_step(model, data, ridge, profile):
    for parameter in model.parameters():
        parameter.grad = None
    loss, cost = forward_loss(model, data, ridge, profile)
    start = time.perf_counter()
    loss.backward()
    eligible = [p for p in model.parameters() if p.requires_grad]
    if not all(
        p.grad is not None and bool(torch.isfinite(p.grad).all()) for p in eligible
    ):
        raise FloatingPointError("missing or nonfinite outer derivative")
    gradient = max(float(p.grad.detach().abs().max()) for p in eligible)
    cost.update(
        backward_seconds=time.perf_counter() - start,
        backward_rows=len(data["x"]),
        backward_passes=1,
    )
    return float(loss.detach()), gradient, cost
