"""Fixed regularized logit projection in the EXISTING linear residual family.

Fit train-only centered teacher logits, not labels or calibration-selected targets.
One reduced float64 SVD per Cell is reused for residual and standalone solutions.
This changes BOTH the objective and solver relative to AdamW/KL. It is ordinary
ridge regression, not an NDU/FBSDE result or a certified retention guarantee.
"""
from __future__ import annotations

import torch

from experiments.shared_stem_cell import consolidation as c, execution as e
from experiments.shared_stem_cell import residual_consolidation as rc

RHO = 0.1  # Fixed before the development trials; no hyperparameter search.


def workspace_bytes(rows, width, classes):
    """Conservative named-tensor allowance; LAPACK/process peak is NOT bounded."""
    e.integer(rows, 1, 16384, "ridge rows")
    e.integer(width, 1, 8192, "ridge width")
    e.integer(classes, 2, 256, "ridge classes")
    p, k = width + 1, min(rows, width + 1)
    return 8 * (3 * rows * p + 3 * k * (rows + p) + 10 * classes * (rows + p) + 10 * k)


@torch.no_grad()
def solve_pair(x, teacher_logits, base_logits):
    """Minimize ||ZW-Y||_F^2 + alpha||W||_F^2, including the bias penalty.

    Z=[x,1], alpha=RHO*||Z||_F^2/columns(Z). The two RHS blocks are
    centered(teacher-base) and centered(teacher). No data standardization,
    test inputs, labels, truncation, iterative optimizer or pseudoinverse cutoff.
    """
    if (not isinstance(x, torch.Tensor) or x.ndim != 2 or x.dtype != torch.float32
            or x.device.type != "cpu" or not bool(torch.isfinite(x).all())):
        raise e.InputError("finite CPU float32 ridge input required")
    if not isinstance(teacher_logits, torch.Tensor) or teacher_logits.ndim != 2:
        raise e.InputError("paired ridge logit matrices required")
    n, d = x.shape
    classes = teacher_logits.shape[1]
    allowance = workspace_bytes(n, d, classes)
    if allowance > c.MAX_BYTES:
        raise e.InputError("ridge workspace budget before allocation")
    for value in (teacher_logits, base_logits):
        if (not isinstance(value, torch.Tensor) or value.shape != (n, classes)
                or value.device.type != "cpu" or value.dtype != torch.float32
                or not bool(torch.isfinite(value).all())):
            raise e.InputError("matching finite teacher/base logits required")
    with torch.random.fork_rng(devices=[]), e.measured() as timing:
        z = torch.cat([x.detach().double(), torch.ones(n, 1, dtype=torch.float64)], 1)
        target = teacher_logits.detach().double()
        target = target - target.mean(-1, keepdim=True)
        base = base_logits.detach().double()
        base = base - base.mean(-1, keepdim=True)
        y = torch.cat([target - base, target], 1)
        alpha = RHO * z.square().sum() / z.shape[1]
        u, singular, vh = torch.linalg.svd(z, full_matrices=False)
        w = vh.T @ ((singular / (singular.square() + alpha)).unsqueeze(-1) * (u.T @ y))
        rhs = z.T @ y
        heads, diagnostics = [], []
        for j in range(2):
            columns = slice(j * classes, (j + 1) * classes)
            precise = w[:, columns]
            deployed = precise.float().double()
            denominator = max(1.0, float(torch.linalg.vector_norm(rhs[:, columns])))
            errors = [float(torch.linalg.vector_norm(z.T @ (z @ a - y[:, columns]) + alpha * a))
                      / denominator for a in (precise, deployed)]
            if (not bool(torch.isfinite(deployed).all()) or not all(torch.isfinite(torch.tensor(errors)))
                    or errors[0] > 1e-10 or errors[1] > 2e-5):
                raise e.InputError("ridge stationarity/materialization check failed")
            model = e.Head(d, classes, "linear", min(8, d)).eval()
            model.base.weight.copy_(deployed[:-1].T.float())
            model.base.bias.copy_(deployed[-1].float())
            heads.append(model.requires_grad_(False))
            diagnostics.append({"normal_residual_float64": errors[0], "normal_residual_float32": errors[1],
                "training_centered_rmse": float((z @ deployed - y[:, columns]).square().mean().sqrt()),
                "objective": float((z @ deployed - y[:, columns]).square().sum() + alpha * deployed.square().sum()),
                **e.parameters(model)})
    rank = int((singular > singular[0] * max(z.shape) * torch.finfo(torch.float64).eps).sum())
    return tuple(heads), {**timing, "rho": RHO, "alpha": float(alpha), "rows": n, "columns": d + 1,
        "numerical_rank_diagnostic": rank, "nullity_diagnostic": d + 1 - rank,
        "effective_degrees_of_freedom": float((singular.square() / (singular.square() + alpha)).sum()),
        "rhs_columns": 2 * classes, "svd_calls": 1, "optimizer_steps": 0,
        "named_tensor_budget_bytes": allowance, "includes_lapack_workspace": False,
        "input_sha256": e.tensor_digest(x), "teacher_logits_sha256": e.tensor_digest(teacher_logits),
        "base_logits_sha256": e.tensor_digest(base_logits), "solutions": diagnostics}


@torch.no_grad()
def fit_ridge(teachers, shared, train_x, train_routes, calibration_x, calibration_routes, calibration_y):
    """Fit two matched linear families without accepting ANY training gold labels."""
    width, classes, teacher_ids = c.bank_identity(teachers)
    cells = len(teachers)
    shared_id = rc.shared_identity(shared, width, classes, cells)
    for x, routes in ((train_x, train_routes), (calibration_x, calibration_routes)):
        c.observations(x, routes, width, cells)
        if set(routes.tolist()) != set(range(cells)):
            raise e.InputError("every Cell needs train and calibration coverage")
    c.labels(calibration_y, len(calibration_x), classes)
    # Inspect EVERY Cell before the first teacher forward or SVD.
    allowance = max(workspace_bytes(int((train_routes == cell).sum()), width, classes) for cell in range(cells))
    count = classes * (width + 1)
    if (allowance + 2 * cells * count * 4 + sum(v["parameter_bytes"] for v in teacher_ids)
            + shared_id["parameter_bytes"] + (len(train_x) + len(calibration_x)) * classes * 32 > c.MAX_BYTES):
        raise e.InputError("ridge whole candidate budget before execution")
    fitted = {mode: [] for mode in rc.MODES}
    solves = []
    with e.measured() as whole:
        with e.measured() as targets_cost:
            teacher = c.bank_logits(teachers, train_x, train_routes)
            base = shared(c.augment(train_x, train_routes, cells))
        for cell in range(cells):
            ids = (train_routes == cell).nonzero(as_tuple=False).flatten()
            heads, receipt = solve_pair(train_x[ids], teacher[ids], base[ids])
            solves.append({"cell": cell, "training_rows": ids.tolist(), **receipt})
            for mode, head in zip(rc.MODES, heads):
                fitted[mode].append(head)
        fitted = {k: tuple(v) for k, v in fitted.items()}
        with e.measured() as calibration_cost:
            probabilities = {"bank": c.bank_logits(teachers, calibration_x, calibration_routes).softmax(-1).tolist(),
                "shared": shared(c.augment(calibration_x, calibration_routes, cells)).softmax(-1).tolist(),
                rc.MODES[0]: rc.corrected_logits(shared, fitted[rc.MODES[0]], calibration_x, calibration_routes, cells)[0].softmax(-1).tolist(),
                rc.MODES[1]: c.bank_logits(fitted[rc.MODES[1]], calibration_x, calibration_routes).softmax(-1).tolist()}
        scores = {k: c.score(p, calibration_y, calibration_routes, cells) for k, p in probabilities.items()}
        sizes = {"bank": sum(v["parameters"] for v in teacher_ids), "shared": shared_id["parameters"],
                 rc.MODES[0]: shared_id["parameters"] + cells * count, rc.MODES[1]: cells * count}
        eligible = ["bank"] + [k for k in ("shared", *rc.MODES) if sizes[k] < sizes["bank"] and all(
            a["correct"] >= b["correct"] for a, b in zip(scores[k]["per_cell"], scores["bank"]["per_cell"]))]
        selected = min(eligible, key=lambda k: (-scores[k]["correct"], sizes[k], scores[k]["nll"], k))
    if c.bank_identity(teachers)[2] != teacher_ids or e.parameters(shared) != shared_id:
        raise e.InputError("ridge fit changed inherited parameters")
    # Reuse the existing frozen residual MODEL/prediction contract, not its KL fitter.
    return fitted, {"schema": "hepta.linear-residual-consolidation.v1", "fitting_profile": "centered_logit_ridge_v1",
        "profile": {"cells": cells, "width": width, "classes": classes}, "selected": selected,
        "teacher_identities": teacher_ids, "shared_identity": shared_id,
        "head_identities": {k: [e.parameters(m) for m in v] for k, v in fitted.items()},
        "parameter_counts": sizes, "eligible": eligible, "calibration_probabilities": probabilities,
        "calibration_scores": scores, "solves": solves, "rho": RHO, "bias_penalized": True,
        "teacher_target_generation": {**targets_cost, "teacher_forwards": cells, "shared_forwards": 1},
        "calibration_cost": calibration_cost, "whole_fitting": whole, "executed_svd_calls": cells,
        "executed_optimizer_steps": 0, "same_objective_as_adamw_kl": False,
        "selection_rule": "all_cell_calibration_nonregression_then_correct_parameters_nll_key",
        "independent_evaluation": False, "retention_certified": False, "production_accepted": False}
