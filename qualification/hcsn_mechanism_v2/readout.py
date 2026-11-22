"""Autograd and direct solutions of exactly the same conditional ridge problem.

The optimizer receives X and y, never the direct solution or an oracle stopping
target. Numerical optimality is assessed afterwards. Program weights are the
previous public semantic program, whose historical authoring cost is unknown.
"""

import time

import torch

from qualification.hcsn_confirmatory_v1.semantic_program import write_readout

from .representation import ridge_fit


def objective(x, y, weight, bias, ridge):
    residual = x @ weight + bias - y.reshape(-1)
    return residual.square().mean() + ridge / len(x) * weight.square().sum()


def semantic_state(task, names, scaler):
    started = time.perf_counter()
    weights, bias = write_readout(task, names)
    raw = torch.tensor(weights, dtype=torch.float64)
    mean = torch.as_tensor(scaler["mean"], dtype=raw.dtype)
    scale = torch.as_tensor(scaler["scale"], dtype=raw.dtype)
    return {
        "weight": raw * scale,
        "bias": torch.tensor(bias, dtype=raw.dtype) + raw @ mean,
        "assembly_seconds": time.perf_counter() - started,
        "historical_authoring_seconds": None,
        "historical_authoring_tokens": None,
        "historical_authoring_api_cost": None,
        "origin": "hcsn_confirmatory_v1/semantic_program.py; reused unchanged",
    }


def optimality(x, y, state, ridge, optimum):
    w = torch.as_tensor(state["weight"], dtype=x.dtype)
    b = torch.as_tensor(state["bias"], dtype=x.dtype)
    residual = x @ w + b - y.reshape(-1)
    grad = torch.cat(
        (2 * (x.T @ residual + ridge * w) / len(x), 2 * residual.mean().reshape(1))
    )
    design = torch.cat((x, torch.ones_like(x[:, :1])), 1)
    penalty = torch.eye(design.shape[1], dtype=x.dtype) * ridge
    penalty[-1, -1] = 0
    hessian = 2 * (design.T @ design + penalty) / len(x)
    minimum = float(torch.linalg.eigvalsh(hessian)[0])
    value = float(objective(x, y, w, b, ridge))
    reference = float(objective(x, y, optimum["weight"], optimum["bias"], ridge))
    return {
        "objective": value,
        "direct_objective": reference,
        "objective_gap": value - reference,
        "gradient_inf": float(grad.abs().max()),
        "hessian_min_eigenvalue": minimum,
        "gradient_objective_bound": float(grad.square().sum()) / (2 * minimum)
        if minimum > 0
        else None,
        "prediction_max_difference": float(
            (x @ w + b - x @ optimum["weight"] - optimum["bias"]).abs().max()
        ),
    }


def solve_bp(x, y, ridge, initial, config):
    """L-BFGS with actual reverse-mode derivatives and a fixed evaluation cap."""
    started, cpu_started = time.perf_counter(), time.process_time()
    w = (
        torch.as_tensor(initial["weight"], dtype=x.dtype)
        .clone()
        .detach()
        .requires_grad_()
    )
    b = (
        torch.as_tensor(initial["bias"], dtype=x.dtype)
        .clone()
        .detach()
        .requires_grad_()
    )
    optimizer = torch.optim.LBFGS(
        [w, b],
        lr=1.0,
        max_iter=config["max_iterations"],
        max_eval=config["max_evaluations"],
        tolerance_grad=config["gradient_tolerance"],
        tolerance_change=config["change_tolerance"],
        history_size=50,
        line_search_fn="strong_wolfe",
    )
    setup = time.perf_counter() - started
    counters = {"forward_evaluations": 0, "backward_evaluations": 0}
    trace = []

    def closure():
        optimizer.zero_grad(set_to_none=True)
        loss = objective(x, y, w, b, ridge)
        if not bool(torch.isfinite(loss)):
            raise FloatingPointError("nonfinite conditional BP objective")
        loss.backward()
        if not all(
            p.grad is not None and bool(torch.isfinite(p.grad).all()) for p in (w, b)
        ):
            raise FloatingPointError("nonfinite conditional BP gradient")
        counters["forward_evaluations"] += 1
        counters["backward_evaluations"] += 1
        count = counters["forward_evaluations"]
        if count == 1 or count in config["checkpoints"]:
            trace.append(
                {
                    "function_evaluations": count,
                    "objective": float(loss.detach()),
                    "gradient_inf": max(float(p.grad.abs().max()) for p in (w, b)),
                    "elapsed_seconds": time.perf_counter() - started,
                    "point_kind": "line-search trial; not a selected final checkpoint",
                }
            )
        return loss

    optimizer.step(closure)
    with torch.no_grad():
        if not all(bool(torch.isfinite(p).all()) for p in (w, b)):
            raise FloatingPointError("nonfinite conditional BP state")
        output = {"weight": w.detach().clone(), "bias": b.detach().clone()}
    return output, {
        **counters,
        "optimizer_iterations": int(optimizer.state[w].get("n_iter", 0)),
        "optimizer_setup_seconds": setup,
        "adaptation_seconds": time.perf_counter() - started,
        "cpu_seconds": time.process_time() - cpu_started,
        "trace": trace,
        "training_label_rows_read": len(x) * counters["forward_evaluations"],
        "stopping_uses_direct_solution": False,
        "max_evaluations_note": "Torch checks max_eval after an iteration; line search may exceed it",
    }


def solve_arm(method, task, names, scaler, x, y, config):
    start, cpu_start = time.perf_counter(), time.process_time()
    zero = {"weight": x.new_zeros(x.shape[1]), "bias": x.new_zeros(())}
    semantic = None
    if method in ("semantic_program", "program_then_bp"):
        semantic = semantic_state(task, names, scaler)
    if method == "direct":
        state = ridge_fit(x, y, ridge=config["ridge"])
        cost = {
            "forward_evaluations": 0,
            "backward_evaluations": 0,
            "training_label_rows_read": len(x),
            "optimizer_iterations": 0,
        }
    elif method in ("local_bp", "program_then_bp"):
        state, cost = solve_bp(x, y, config["ridge"], semantic or zero, config)
    elif method == "semantic_program":
        state, cost = (
            semantic,
            {
                "forward_evaluations": 0,
                "backward_evaluations": 0,
                "training_label_rows_read": 0,
                "optimizer_iterations": 0,
            },
        )
    else:
        raise ValueError("unknown conditional method")
    cost.update(
        total_arm_seconds=time.perf_counter() - start,
        total_arm_cpu_seconds=time.process_time() - cpu_start,
    )
    if semantic is not None:
        cost["semantic_assembly_seconds"] = semantic["assembly_seconds"]
        cost["semantic_authoring_seconds"] = None
        cost["semantic_authoring_tokens"] = None
        cost["semantic_authoring_api_cost"] = None
    return state, cost


def warmup(config):
    """Shared, label-free toy startup; charged separately, never discarded."""
    start, cpu_start = time.perf_counter(), time.process_time()
    x = torch.tensor(
        [[-1.0, 0.0], [0.0, 1.0], [1.0, -1.0], [2.0, 1.0]], dtype=torch.float64
    )
    y = torch.tensor([0.1, 0.2, 0.4, 0.7], dtype=x.dtype)
    short = {**config, "max_iterations": 2, "max_evaluations": 5}
    solve_bp(
        x,
        y,
        config["ridge"],
        {"weight": x.new_zeros(2), "bias": x.new_zeros(())},
        short,
    )
    ridge_fit(x, y, ridge=config["ridge"])
    return {
        "wall_seconds": time.perf_counter() - start,
        "cpu_seconds": time.process_time() - cpu_start,
        "scope": "shared cold optimizer and SVD initialization, retained in process total",
    }
