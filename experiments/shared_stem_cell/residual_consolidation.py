"""Freeze a shared Head; learn one small linear correction per observed Cell.

Use the original feature, not only shared logits: a logit-only correction cannot
recover information the shared Head discarded. Compare against identically fitted
standalone linear teachers. This is ordinary teacher KL, not NDU, a retention
certificate, a new serving owner or a production selection. All input data here
are development data; no test labels enter fitting or calibration selection.
"""
from __future__ import annotations

import torch

from experiments.shared_stem_cell import consolidation as c, execution as e

MODES = ("residual_corrected", "linear_distilled")


def shared_identity(shared, width, classes, cells):
    if (type(shared) is not e.Head or shared.kind != "gated" or shared.training
            or shared.base.in_features != width + cells or shared.base.out_features != classes
            or any(p.requires_grad or p.dtype != torch.float32 or p.device.type != "cpu"
                   or not bool(torch.isfinite(p).all()) for p in shared.parameters())):
        raise e.InputError("frozen conditioned shared Head required")
    return e.parameters(shared)


@torch.no_grad()
def corrected_logits(shared, corrections, x, routes, cells):
    """Internal numeric kernel. Public predict validates identities first."""
    result = shared(c.augment(x, routes, cells))
    calls = [{"component": "shared", "rows": list(range(len(x)))}]
    for cell in routes.unique(sorted=True).tolist():
        ids = (routes == cell).nonzero(as_tuple=False).flatten()
        result[ids] += corrections[cell](x[ids])
        calls.append({"component": f"residual-{cell}", "rows": ids.tolist()})
    return result, calls


def fit_residuals(teachers, shared, train_x, train_routes, train_y, calibration_x,
                  calibration_routes, calibration_y, *, steps=40, seed=17):
    """Fixed shared-supervised backbone; zero residual preserves its initial function."""
    width, classes, teacher_ids = c.bank_identity(teachers)
    cells = len(teachers)
    shared_id = shared_identity(shared, width, classes, cells)
    e.integer(steps, 1, 1000, "residual steps")
    e.integer(seed, 0, 2**31-1, "residual seed")
    for x, r, y in ((train_x, train_routes, train_y), (calibration_x, calibration_routes, calibration_y)):
        c.observations(x, r, width, cells); c.labels(y, len(x), classes)
        if set(r.tolist()) != set(range(cells)):
            raise e.InputError("all Cells need training AND calibration coverage")
    count = classes * (width + 1)
    # Bound all candidate tensors and logits, not an assertion about full process RSS.
    if (sum(v["parameter_bytes"] for v in teacher_ids) + shared_id["parameter_bytes"]
            + (2*cells+2)*count*4 + (len(train_x)+len(calibration_x))*classes*16 > c.MAX_BYTES):
        raise e.InputError("residual candidate tensor budget before allocation")
    fitted = {mode: [] for mode in MODES}
    training = {mode: [] for mode in MODES}
    with torch.random.fork_rng(devices=[]), e.measured() as whole:
        with torch.no_grad(), e.measured() as target_cost:
            targets = (c.bank_logits(teachers, train_x, train_routes)/2).softmax(-1)
            baseline = shared(c.augment(train_x, train_routes, cells))
            if not bool(torch.isfinite(baseline).all()):
                raise e.InputError("nonfinite shared training logits")
        for cell in range(cells):
            ids = (train_routes == cell).nonzero(as_tuple=False).flatten()
            torch.manual_seed(seed + cell)
            initial = e.Head(width, classes, "linear", min(8, width))
            with torch.no_grad():
                for value in initial.parameters(): value.zero_()
            for mode in MODES:
                model, cost = e.fit(initial, train_x[ids], train_y[ids], steps=steps, seed=seed,
                    soft_targets=targets[ids], soft_weight=1.0, temperature=2.0,
                    base_logits=baseline[ids] if mode == "residual_corrected" else None)
                fitted[mode].append(model.eval().requires_grad_(False))
                training[mode].append({**cost, "cell": cell})
            if training[MODES[0]][-1]["minibatch_sha256"] != training[MODES[1]][-1]["minibatch_sha256"]:
                raise e.InputError("residual/standalone teacher sampling mismatch")
        fitted = {k: tuple(v) for k,v in fitted.items()}
        with torch.no_grad(), e.measured() as calibration_cost:
            probabilities = {"bank": c.bank_logits(teachers, calibration_x, calibration_routes).softmax(-1).tolist(),
                "shared": shared(c.augment(calibration_x, calibration_routes, cells)).softmax(-1).tolist(),
                "residual_corrected": corrected_logits(shared, fitted[MODES[0]], calibration_x, calibration_routes, cells)[0].softmax(-1).tolist(),
                "linear_distilled": c.bank_logits(fitted[MODES[1]], calibration_x, calibration_routes).softmax(-1).tolist()}
        metrics = {k: c.score(p, calibration_y, calibration_routes, cells) for k,p in probabilities.items()}
        sizes = {"bank": sum(v["parameters"] for v in teacher_ids), "shared": shared_id["parameters"],
                 "residual_corrected": shared_id["parameters"] + cells*count, "linear_distilled": cells*count}
        eligible = ["bank"] + [k for k in ("shared", *MODES) if sizes[k] < sizes["bank"] and all(
            a["correct"] >= b["correct"] for a,b in zip(metrics[k]["per_cell"], metrics["bank"]["per_cell"]))]
        selected = min(eligible, key=lambda k: (-metrics[k]["correct"], sizes[k], metrics[k]["nll"], k))
    if c.bank_identity(teachers)[2] != teacher_ids or e.parameters(shared) != shared_id:
        raise e.InputError("residual fitting changed inherited models")
    receipt = {"schema": "hepta.linear-residual-consolidation.v1", "selected": selected,
        "profile": {"cells": cells, "width": width, "classes": classes}, "teacher_identities": teacher_ids,
        "shared_identity": shared_id, "shared_source": "fixed_supervised_candidate",
        "head_identities": {k: [e.parameters(m) for m in v] for k,v in fitted.items()},
        "parameter_counts": sizes, "training": training, "eligible": eligible,
        "calibration_probabilities": probabilities, "calibration_scores": metrics,
        "target_generation": {**target_cost, "teacher_forwards": cells, "shared_forwards": 1,
            "teacher_probability_sha256": e.tensor_digest(targets), "base_logits_sha256": e.tensor_digest(baseline)},
        "calibration_cost": calibration_cost, "whole_fitting": whole,
        "executed_optimizer_steps": 2*cells*steps, "temperature": 2.0,
        "selection_rule": "all_cell_calibration_nonregression_then_correct_parameters_nll_key",
        "independent_evaluation": False, "retention_certified": False, "production_accepted": False}
    return fitted, receipt


@torch.no_grad()
def predict(teachers, shared, fitted, receipt, x, routes):
    """Retain bank/shared controls and charge the extra residual forward explicitly."""
    width, classes, teacher_ids = c.bank_identity(teachers)
    cells = len(teachers)
    c.observations(x, routes, width, cells)
    shared_id = shared_identity(shared, width, classes, cells)
    if (receipt.get("schema") != "hepta.linear-residual-consolidation.v1"
            or receipt.get("profile") != {"cells": cells, "width": width, "classes": classes}
            or receipt.get("teacher_identities") != teacher_ids or receipt.get("shared_identity") != shared_id
            or receipt.get("production_accepted") is not False or receipt.get("selected") not in ("bank", "shared", *MODES)
            or set(fitted) != set(MODES) or any(type(v) is not tuple or len(v) != cells for v in fitted.values())):
        raise e.InputError("frozen residual source/profile drift")
    for mode, heads in fitted.items():
        for cell, model in enumerate(heads):
            if (type(model) is not e.Head or model.kind != "linear" or model.training
                    or model.base.in_features != width or model.base.out_features != classes
                    or any(p.requires_grad or p.device.type != "cpu" or p.dtype != torch.float32
                           or not bool(torch.isfinite(p).all()) for p in model.parameters())
                    or e.parameters(model) != receipt["head_identities"][mode][cell]):
                raise e.InputError("residual Head changed before inference")
    linear = sum(e.parameters(m)["parameters"] for m in fitted[MODES[1]])
    sizes = {"bank": sum(v["parameters"] for v in teacher_ids), "shared": shared_id["parameters"],
             "linear_distilled": linear, "residual_corrected": shared_id["parameters"] +
                sum(e.parameters(m)["parameters"] for m in fitted[MODES[0]])}
    if receipt.get("parameter_counts") != sizes:
        raise e.InputError("residual shared-once parameter accounting drift")
    predictions, costs = {}, {}
    for mode in ("bank", "shared", *MODES):
        with e.measured() as timing:
            if mode == "residual_corrected":
                values, calls = corrected_logits(shared, fitted[mode], x, routes, cells)
            elif mode == "shared":
                values = shared(c.augment(x, routes, cells))
                calls = [{"component": "shared", "rows": list(range(len(x)))}]
            else:
                bank = teachers if mode == "bank" else fitted[mode]
                values = c.bank_logits(bank, x, routes)
                calls = [{"component": f"{mode}-{cell}", "rows": (routes == cell).nonzero(as_tuple=False).flatten().tolist()}
                         for cell in routes.unique(sorted=True).tolist()]
            if values.shape != (len(x), classes) or not bool(torch.isfinite(values).all()):
                raise e.InputError("nonfinite residual comparison output")
            predictions[mode] = values.softmax(-1).tolist()
        costs[mode] = {**timing, "calls": calls, "head_forward_calls": len(calls),
            "head_rows_processed": sum(len(v["rows"]) for v in calls), "encoder_calls": 0}
    return {"predictions": predictions, "inference_costs": costs, "selected": receipt["selected"]}
