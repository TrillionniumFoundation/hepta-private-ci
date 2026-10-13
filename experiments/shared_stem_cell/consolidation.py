"""Route-conditioned consolidation of existing Cell Heads, not a new Stem.

One observed Cell index is appended as a one-hot input to ONE existing gated Head.
Teacher targets come only from that row's designated Cell, never an ensemble mean.
Train/calibration-only fitting, fixed objectives/budgets and no-change control.
This is ordinary supervised/KL distillation, NOT general NDU, learned routing,
optimizer continuation, generator consolidation or production artifact selection.
"""
from __future__ import annotations

import torch
from torch.nn import functional as F

from experiments.shared_stem_cell import execution as e
from experiments.shared_stem_cell.head_artifacts import _shape_count

MAX_BYTES = 64 * 1024**2
STUDENTS = ("supervised", "distilled", "mixed")
ARMS = ("bank", "shared_frozen", *STUDENTS)


def observations(x, routes, width, cells):
    """Bound complete numeric inputs before one-hot expansion or Head execution."""
    if (not isinstance(x, torch.Tensor) or x.ndim != 2 or x.dtype != torch.float32
            or x.device.type != "cpu" or not 1 <= len(x) <= 16384 or x.shape[1] != width
            or (len(x) * (width + cells) * 4) > MAX_BYTES
            or not bool(torch.isfinite(x).all()) or not isinstance(routes, torch.Tensor)
            or routes.device.type != "cpu" or routes.dtype != torch.long or routes.shape != (len(x),)
            or bool(((routes < 0) | (routes >= cells)).any())):
        raise e.InputError("bounded features and exact observed Cell indices required")


def labels(y, n, classes):
    if (not isinstance(y, torch.Tensor) or y.dtype != torch.long or y.device.type != "cpu"
            or y.shape != (n,) or bool(((y < 0) | (y >= classes)).any())):
        raise e.InputError("bounded training/calibration labels required")


def bank_identity(teachers):
    if type(teachers) is not tuple or not 2 <= len(teachers) <= 64:
        raise e.InputError("2..64 explicitly ordered Cell teachers required")
    for t in teachers:
        if (type(t) is not e.Head or t.kind != "gated" or t.training
                or any(p.requires_grad or p.device.type != "cpu" or p.dtype != torch.float32
                       or not bool(torch.isfinite(p).all()) for p in t.parameters())):
            raise e.InputError("frozen finite CPU gated teachers required")
    width, classes = teachers[0].base.in_features, teachers[0].base.out_features
    if any((t.base.in_features, t.base.out_features) != (width, classes) for t in teachers):
        raise e.InputError("all teachers need identical feature and class schemas")
    identities = [e.parameters(t) for t in teachers]
    if (width + len(teachers) > 8192
            or sum(p["parameter_bytes"] for p in identities) > MAX_BYTES):
        raise e.InputError("teacher bank or conditioned width budget")
    return width, classes, identities


@torch.no_grad()
def bank_logits(teachers, x, routes):
    width, classes = teachers[0].base.in_features, teachers[0].base.out_features
    observations(x, routes, width, len(teachers))
    result = torch.empty(len(x), classes)
    for cell in routes.unique(sorted=True).tolist():
        ids = (routes == cell).nonzero(as_tuple=False).flatten()
        result[ids] = teachers[cell](x[ids])
    if not bool(torch.isfinite(result).all()):
        raise e.InputError("nonfinite routed teacher output")
    return result


def augment(x, routes, cells):
    return torch.cat([x.detach(), F.one_hot(routes, cells).to(torch.float32)], -1)


def score(probabilities, y, routes, cells):
    p = torch.tensor(probabilities, dtype=torch.float32)
    if (p.ndim != 2 or p.shape[0] != len(y) or not 2 <= p.shape[1] <= 256
            or not bool(torch.isfinite(p).all()) or bool(((p < 0) | (p > 1)).any())
            or not torch.allclose(p.sum(-1), torch.ones(len(y)), atol=1e-5, rtol=0)):
        raise e.InputError("complete finite normalized probabilities required")
    labels(y, len(p), p.shape[1])
    if (not isinstance(routes, torch.Tensor) or routes.dtype != torch.long
            or routes.device.type != "cpu" or routes.shape != (len(p),)
            or bool(((routes < 0) | (routes >= cells)).any())):
        raise e.InputError("complete score route vector required")
    correct = p.argmax(-1) == y
    return {"correct": int(correct.sum()), "cases": len(y), "accuracy": float(correct.float().mean()),
        "nll": float(-p[torch.arange(len(p)), y].clamp_min(1e-12).log().mean()),
        "per_cell": [{"cell": i, "cases": int((routes == i).sum()),
                      "correct": int(correct[routes == i].sum())} for i in range(cells)]}


def fit_students(teachers, train_x, train_routes, train_y, calibration_x, calibration_routes,
                 calibration_y, *, steps=40, seed=17):
    """No holdout argument; retain original bank and compare equal student budgets."""
    width, classes, before = bank_identity(teachers)
    e.integer(steps, 1, 1000, "consolidation steps")
    e.integer(seed, 0, 2**31-1, "consolidation seed")
    cells = len(teachers)
    for x, r, y in ((train_x, train_routes, train_y), (calibration_x, calibration_routes, calibration_y)):
        observations(x, r, width, cells); labels(y, len(x), classes)
        if set(r.tolist()) != set(range(cells)):
            raise e.InputError("every Cell needs train AND calibration coverage")
    count = _shape_count({"width": width + cells, "classes": classes, "kind": "gated", "rank": min(8, width)})
    if 4 * count * 5 > MAX_BYTES:
        raise e.InputError("consolidation live candidate parameter budget")
    with torch.random.fork_rng(devices=[]), e.measured() as whole:
        z = augment(train_x, train_routes, cells)
        calibration_z = augment(calibration_x, calibration_routes, cells)
        with e.measured() as teacher_cost:
            target = (bank_logits(teachers, train_x, train_routes) / 2.0).softmax(-1)
        torch.manual_seed(seed)
        initial = e.Head(width + cells, classes, "gated", min(8, width)).eval()
        models = {"shared_frozen": initial}
        training = {}
        for name, weight in zip(STUDENTS, (0.0, 1.0, 0.5)):
            models[name], training[name] = e.fit(initial, z, train_y, steps=steps, seed=seed,
                soft_targets=target, soft_weight=weight, temperature=2.0)
            training[name]["teacher_weight"] = weight
        for model in models.values():
            model.eval().requires_grad_(False)
        with torch.no_grad(), e.measured() as calibration_cost:
            probabilities = {"bank": bank_logits(teachers, calibration_x, calibration_routes).softmax(-1).tolist()}
            probabilities.update({name: model(calibration_z).softmax(-1).tolist() for name, model in models.items()})
        metrics = {name: score(p, calibration_y, calibration_routes, cells) for name, p in probabilities.items()}
        # Measured per-Cell non-regression ONLY on calibration; not a confidence bound.
        bank_counts = [r["correct"] for r in metrics["bank"]["per_cell"]]
        sizes = {"bank": sum(p["parameters"] for p in before), **{k: e.parameters(v)["parameters"] for k, v in models.items()}}
        eligible = ["bank"] + [k for k in models if sizes[k] < sizes["bank"] and all(
            r["correct"] >= floor for r, floor in zip(metrics[k]["per_cell"], bank_counts))]
        selected = min(eligible, key=lambda k: (-metrics[k]["correct"], sizes[k], metrics[k]["nll"], k))
    if before != bank_identity(teachers)[2]:
        raise e.InputError("consolidation changed teacher parameters")
    if len({r["minibatch_sha256"] for r in training.values()}) != 1:
        raise e.InputError("student comparator sampling mismatch")
    receipt = {"schema": "hepta.route-conditioned-consolidation.v1", "selected": selected,
        "teacher_identities": before, "students": {k: e.parameters(v) for k,v in models.items()},
        "route_profile": {"kind": "observed_cell_one_hot", "cells": cells, "input_width": width},
        "training": training, "temperature": 2.0, "calibration_probabilities": probabilities,
        "calibration_scores": metrics, "eligible": eligible,
        "selection_rule": "per_cell_calibration_nonregression_then_correct_count_parameters_nll_key",
        "parameter_counts": sizes, "training_target_sha256": e.tensor_digest(target),
        "teacher_target_generation": {**teacher_cost, "rows": len(train_x), "forward_calls": cells},
        "calibration_cost": calibration_cost, "whole_fitting": whole,
        "executed_student_steps": sum(r["steps"] for r in training.values()),
        "external_holdout_required": True, "independent_evaluation": False, "production_accepted": False}
    return models, receipt


@torch.no_grad()
def predict(teachers, models, receipt, x, routes):
    """Score existing bank and frozen candidates; no targets or fitting are admitted."""
    width, _, ids = bank_identity(teachers)
    observations(x, routes, width, len(teachers))
    if (receipt["route_profile"] != {"kind": "observed_cell_one_hot", "cells": len(teachers), "input_width": width}
            or receipt["selected"] not in ARMS or receipt["production_accepted"] is not False
            or set(models) != {"shared_frozen", *STUDENTS} or receipt["teacher_identities"] != ids
            or receipt["students"] != {k: e.parameters(v) for k,v in models.items()}
            or any(m.training or any(p.requires_grad for p in m.parameters()) for m in models.values())):
        raise e.InputError("frozen consolidation identity changed")
    values, costs = {}, {}
    with e.measured() as routing:
        z = augment(x, routes, len(teachers))
    with e.measured() as timing:
        values["bank"] = bank_logits(teachers, x, routes).softmax(-1).tolist()
    costs["bank"] = {**timing, "rows": len(x), "forward_calls": len(routes.unique())}
    for name, model in models.items():
        with e.measured() as timing:
            p = model(z).softmax(-1)
            if not bool(torch.isfinite(p).all()):
                raise e.InputError("nonfinite shared Head probabilities")
            values[name] = p.tolist()
        costs[name] = {**timing, "rows": len(x), "forward_calls": 1}
    return {"predictions": values, "inference_costs": costs, "shared_input_preparation": routing}
