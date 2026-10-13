"""Executable controls for split, modality fusion, recurrence and consolidation.

These pure candidate operators consume actual tensors from the existing encoder
owner. Tensor fixtures test mechanics only. No new NDU subject, runtime owner,
artifact selection, topology activation, or external-effect authority is added.
"""
from __future__ import annotations

from copy import deepcopy

import torch
from torch import nn
from torch.nn import functional as F

from experiments.shared_stem_cell.execution import (
    Head, InputError, fit, integer, measured, parameters,
)


def _features(x, dimension=2):
    if (not isinstance(x, torch.Tensor) or x.ndim != dimension
            or x.device.type != "cpu" or x.dtype != torch.float32
            or not 1 <= len(x) <= 16384 or not bool(torch.isfinite(x).all())):
        raise InputError("finite bounded CPU feature tensor required")


class RoutedSplit(nn.Module):
    """Function-preserving inheritance; observed route is available to ALL arms."""
    def __init__(self, parent, route_count=2):
        super().__init__()
        integer(route_count, 2, 8, "route count")
        self.experts = nn.ModuleList([deepcopy(parent) for _ in range(route_count)])

    def forward(self, x):
        routes = x[:, -1]
        if not bool(((routes >= 0) & (routes < len(self.experts)) & (routes == routes.floor())).all()):
            raise InputError("route must be an observed bounded integer, not a target")
        result = None
        for route, expert in enumerate(self.experts):
            ids = (routes == route).nonzero(as_tuple=False).flatten()
            if len(ids):
                local = expert(x[ids])
                if result is None:
                    result = local.new_zeros((len(x), local.shape[1]))
                result[ids] = local
        return result


def split_trial(train_x, train_y, test_x, *, classes, steps=40, seed=17, extra=None):
    """No test targets; compare inherited parent, continuation, split and width."""
    _features(train_x)
    _features(test_x)
    if train_x.shape[1] != test_x.shape[1]:
        raise InputError("train/test feature dimension")
    torch.manual_seed(seed)
    initial = Head(train_x.shape[1], classes, "linear", min(8, train_x.shape[1]))
    parent, shared_cost = fit(initial, train_x, train_y, steps=steps, seed=seed)
    inherited = RoutedSplit(parent)
    with torch.no_grad():
        if not torch.allclose(parent(test_x), inherited(test_x), rtol=1e-6, atol=1e-6):
            raise InputError("split failed floating-point function preservation")
    total_budget = parameters(inherited)["parameters"]
    # Wide unsplit MLP receives precisely the same features, including route.
    width = (total_budget - classes) // (train_x.shape[1] + classes + 1)
    if width < 1:
        raise InputError("no admissible equal-budget wide comparator")
    torch.manual_seed(seed)
    wider = nn.Sequential(nn.Linear(train_x.shape[1], width), nn.Tanh(), nn.Linear(width, classes))
    controls = {"parent_no_change": parent}
    costs = {"parent_no_change": {"steps": 0, **parameters(parent)}}
    for name, model in (("parent_continued", parent), ("inherited_split", inherited)):
        controls[name], costs[name] = fit(model, train_x, train_y, steps=steps, seed=seed)
    # This arm did not inherit parent training; charge the same total step budget.
    controls["larger_unsplit"], costs["larger_unsplit"] = fit(
        wider, train_x, train_y, steps=2 * steps, seed=seed)
    missing = []
    if extra is not None:
        extra_x, extra_y = extra
        _features(extra_x)
        if extra_x.shape[1] != train_x.shape[1] or len(extra_y) != len(extra_x):
            raise InputError("extra-data shape")
        controls["more_data"], costs["more_data"] = fit(
            parent, torch.cat([train_x, extra_x]), torch.cat([train_y, extra_y]),
            steps=steps, seed=seed)
    else:
        missing.append("more_data: distinct earlier training material not supplied")
    with torch.no_grad():
        predictions = {name: model(test_x).softmax(-1).tolist() for name, model in controls.items()}
    return {"predictions": predictions, "costs": costs, "common_parent_training": shared_cost,
            "split_parameter_budget": total_budget,
            "larger_unsplit_parameter_gap": total_budget - parameters(wider)["parameters"],
            "route_feature_shared_by_all_arms": True, "missing": missing,
            "topology_activation": False, "independent_future_gain": None}


class FusionHead(nn.Module):
    """Train connectors, preserving slot order/masks; never train the input towers."""
    def __init__(self, shapes, classes, width=8):
        super().__init__()
        if not shapes or not set(shapes) <= {"text", "image", "audio", "video"}:
            raise InputError("known modalities required")
        self.names = tuple(sorted(shapes))
        self.shapes = shapes
        for slots, features in shapes.values():
            integer(slots, 1, 64, "token slots")
            integer(features, 1, 8192, "tower width")
        self.connectors = nn.ModuleDict({k: nn.Linear(shapes[k][1], width) for k in self.names})
        size = sum(shapes[k][0] * (width + 1) for k in self.names)
        self.readout = nn.Linear(size, classes)

    def forward(self, inputs):
        values = []
        for name in self.names:
            x, mask, timestamps = inputs[name]
            _features(x, 3)
            if tuple(x.shape[1:]) != tuple(self.shapes[name]) or mask.shape != x.shape[:2] or mask.dtype != torch.bool:
                raise InputError("modality tensor/mask shape")
            if timestamps.shape != mask.shape or not bool(torch.isfinite(timestamps).all()):
                raise InputError("timestamp shape/value")
            for row, valid in zip(timestamps, mask):
                selected = row[valid]
                if len(selected) > 1 and not bool((selected[1:] > selected[:-1]).all()):
                    raise InputError("temporal order must be strictly increasing")
            y = torch.tanh(self.connectors[name](x.detach()))
            y = y * mask.unsqueeze(-1)
            # Ordered slots and explicit presence distinguish absence from zero.
            values.append(torch.cat([y, mask.unsqueeze(-1).float()], -1).flatten(1))
        return self.readout(torch.cat(values, 1))


def modality_trial(train, labels, test, *, classes, steps=40, seed=17):
    """Real connector SGD and each unimodal baseline; untrusted tower provenance."""
    if set(train) != set(test):
        raise InputError("modality sets differ")
    predictions, frozen_predictions, costs = {}, {}, {}
    n = len(labels)
    if n < 1:
        raise InputError("empty modality training data")
    selections = list(dict.fromkeys([tuple(sorted(train)), *((name,) for name in sorted(train))]))
    for selected in selections:
        torch.manual_seed(seed)
        shapes = {k: tuple(train[k][0].shape[1:]) for k in selected}
        model = FusionHead(shapes, classes)
        subset = {k: train[k] for k in selected}
        if any(len(v[0]) != n for v in subset.values()):
            raise InputError("unpaired training modalities")
        name = "+".join(selected)
        with torch.no_grad():
            frozen_predictions[name] = model({k: test[k] for k in selected}).softmax(-1).tolist()
        frozen_identity = parameters(model)
        optimizer = torch.optim.AdamW(model.parameters(), lr=0.01, weight_decay=0)
        with measured() as timing:
            for _ in range(integer(steps, 1, 1000, "connector steps")):
                optimizer.zero_grad(set_to_none=True)
                loss = F.cross_entropy(model(subset), labels)
                loss.backward()
                nn.utils.clip_grad_norm_(model.parameters(), 1, error_if_nonfinite=True)
                optimizer.step()
        name = "+".join(selected)
        with torch.no_grad():
            predictions[name] = model({k: test[k] for k in selected}).softmax(-1).tolist()
        costs[name] = {**timing, **parameters(model), "steps": steps, "examples_processed": steps * n,
                       "same_init_frozen": frozen_identity}
    return {"predictions": predictions, "frozen_predictions": frozen_predictions, "costs": costs,
            "tower_provenance_independently_verified": False,
            "semantic_quality": None, "production_accepted": False}


class RecurrentReader(nn.Module):
    def __init__(self, width, classes):
        super().__init__()
        self.core = nn.GRUCell(width, width)
        self.readout = nn.Linear(width, classes)

    def step(self, observation, state):
        state = self.core(observation.detach(), state)
        return state, self.readout(state)


def _critic_features(probabilities, depth, horizon):
    top = probabilities.max(-1).values
    entropy = -(probabilities * probabilities.clamp_min(1e-8).log()).sum(-1)
    return torch.stack([torch.ones_like(top), top, entropy,
                        torch.full_like(top, depth / horizon)], -1)


def recurrent_trial(train_x, train_y, calibration_x, calibration_y, test_x,
                    *, classes, steps=40, depth=4, step_cost=0.01, seed=17):
    """Four arms, genuine early halt; NDU is an explicitly LINEAR special case.

    Fit a frozen conditional continuation-advantage estimator on calibration,
    not on held-out outcomes. No general stochastic/FBSDE claim is made.
    """
    for value in (train_x, calibration_x, test_x):
        _features(value, 3)
    integer(depth, 2, 16, "depth")
    if not math_finite_cost(step_cost) or any(v.shape[1:] != train_x.shape[1:] for v in (calibration_x, test_x)):
        raise InputError("cost or recurrent shape")
    torch.manual_seed(seed)
    model = RecurrentReader(train_x.shape[2], classes)
    optimizer = torch.optim.AdamW(model.parameters(), lr=0.01, weight_decay=0)
    with measured() as training:
        for step in range(integer(steps, 1, 1000, "recurrent steps")):
            optimizer.zero_grad(set_to_none=True)
            state = torch.zeros(len(train_x), train_x.shape[2])
            losses = []
            for t in range(depth):
                state, logits = model.step(train_x[:, t % train_x.shape[1]], state)
                losses.append(F.cross_entropy(logits, train_y))
            torch.stack(losses).mean().backward()
            nn.utils.clip_grad_norm_(model.parameters(), 1, error_if_nonfinite=True)
            optimizer.step()
    model.eval()
    with torch.no_grad():
        state = torch.zeros(len(calibration_x), train_x.shape[2])
        probabilities = []
        for t in range(depth):
            state, logits = model.step(calibration_x[:, t % calibration_x.shape[1]], state)
            probabilities.append(logits.softmax(-1))
        final_correct = (probabilities[-1].argmax(-1) == calibration_y).float()
        inputs = torch.cat([_critic_features(p, t + 1, depth) for t, p in enumerate(probabilities[:-1])])
        targets = torch.cat([final_correct - (p.argmax(-1) == calibration_y).float()
                             for p in probabilities[:-1]])
        # Ridge-conditioned linear conditional-expectation estimate, not a BSDE Z.
        coefficients = torch.linalg.solve(inputs.T @ inputs + 0.01 * torch.eye(4), inputs.T @ targets)
        output, costs = {}, {}
        for arm in ("no_recurrence", "fixed_recurrence", "adaptive", "adaptive_ndu_linear"):
            state = torch.zeros(len(test_x), train_x.shape[2])
            active = torch.ones(len(test_x), dtype=torch.bool)
            chosen = torch.zeros(len(test_x), classes)
            used = torch.zeros(len(test_x), dtype=torch.long)
            with measured() as timing:
                for t in range(depth):
                    ids = active.nonzero(as_tuple=False).flatten()
                    if not len(ids):
                        break
                    next_state, logits = model.step(test_x[ids, t % test_x.shape[1]], state[ids])
                    state[ids] = next_state
                    p = logits.softmax(-1)
                    chosen[ids] = p
                    used[ids] += 1
                    stop = torch.full((len(ids),), t == depth - 1, dtype=torch.bool)
                    if arm == "no_recurrence":
                        stop[:] = True
                    elif arm == "adaptive":
                        stop |= p.max(-1).values >= 0.8  # frozen preregistered threshold
                    elif arm == "adaptive_ndu_linear":
                        improvement = _critic_features(p, t + 1, depth) @ coefficients
                        stop |= improvement <= step_cost * (depth - t - 1)
                    active[ids[stop]] = False
            output[arm] = chosen.tolist()
            costs[arm] = {**timing, "cell_transitions": int(used.sum()),
                "depths": used.tolist(), "registered_step_cost": step_cost,
                "matched_ceiling_not_matched_flops": True}
    return {"predictions": output, "costs": costs, "training": training,
            "critic_coefficients": coefficients.tolist(), "model": parameters(model),
            "ndu_profile": "conditional_expectation_of_external_correctness_minus_cost",
            "general_fbsde_gain": None, "production_accepted": False}


def math_finite_cost(value):
    import math
    return type(value) in (int, float) and math.isfinite(value) and 0 <= value <= 1


def distill_heads(teachers, student, train_x, test_x, *, steps=40, temperature=2.0):
    """Actual shared-head consolidation on candidate copy, not generator quality."""
    _features(train_x)
    _features(test_x)
    if not teachers or not 0 < temperature <= 10:
        raise InputError("teacher/temperature bounds")
    teacher_digests = [parameters(t)["sha256"] for t in teachers]
    original = parameters(student)["sha256"]
    candidate = deepcopy(student)
    with torch.no_grad():
        target = torch.stack([(t.eval()(train_x) / temperature).softmax(-1) for t in teachers]).mean(0)
    optimizer = torch.optim.AdamW(candidate.parameters(), lr=0.01, weight_decay=0)
    with measured() as timing:
        for _ in range(integer(steps, 1, 1000, "distillation steps")):
            optimizer.zero_grad(set_to_none=True)
            loss = F.kl_div((candidate(train_x.detach()) / temperature).log_softmax(-1),
                            target, reduction="batchmean") * temperature**2
            loss.backward()
            optimizer.step()
    if original != parameters(student)["sha256"] or teacher_digests != [parameters(t)["sha256"] for t in teachers]:
        raise InputError("selected student/teacher mutated")
    with torch.no_grad():
        predictions = candidate.eval()(test_x).softmax(-1).tolist()
    return candidate, {"predictions": predictions, "costs": {**timing, **parameters(candidate)},
        "teachers": teacher_digests, "retention_requires_external_test": True,
        "generator_distillation_completed": False, "production_accepted": False}
