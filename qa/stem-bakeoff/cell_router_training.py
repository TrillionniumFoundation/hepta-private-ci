"""Full-information offline router learning over frozen, provenance-bound Cells.

Targets are observed per-Cell task NLL plus declared cost, never holdout labels.
Inference ranks first, then invokes only the selected Heads. Cost units are
caller-declared work estimates, not measured latency, money or energy.
"""

from dataclasses import asdict, dataclass
import copy
import hashlib
import math
import re
from typing import Mapping

import torch
from torch import nn

from cell_head_training import (HeadCohortV1, TrainedCellHeadV1, TEMPERATURES,
                                _cohort, _json_bytes, _state_digest, task_metrics)
from feature_bundle import FeatureBundleV1, FeatureIdentityV1
from multimodal_bridge import _verify_optimizer_lifecycle


class RouterTrainingError(ValueError):
    pass


@dataclass(frozen=True)
class RouterCellV1:
    cell_id: str
    head: TrainedCellHeadV1
    cost_units: float
    # Head reports retain a group hash; this witness must match that hash.
    head_source_groups: Mapping[str, tuple[str, ...]]


@dataclass(frozen=True)
class RouterTrainingConfigV1:
    steps: int = 200
    learning_rate: float = 0.1
    seed: int = 7
    hidden_width: int = 16  # zero selects a linear router
    top_k: int = 1
    budget_units: float = 1.0
    cost_weight: float = 0.0
    confidence_threshold: float = 0.7

    def validate(self):
        integers = ((self.steps, 1, 5000), (self.seed, 0, 2**31 - 1),
                    (self.hidden_width, 0, 64), (self.top_k, 1, 8))
        reals = ((self.learning_rate, 0, 1), (self.budget_units, 0, 1e9),
                 (self.cost_weight, 0, 1e3), (self.confidence_threshold, 0, 1))
        if (any(type(v) is not int or not lo <= v <= hi for v, lo, hi in integers)
                or any(type(v) not in (float, int) or not math.isfinite(v)
                       or not lo <= v <= hi for v, lo, hi in reals)
                or self.learning_rate == 0 or self.budget_units == 0):
            raise RouterTrainingError("invalid bounded Router configuration")


def _check_cells(cells):
    if not isinstance(cells, (tuple, list)) or not 1 <= len(cells) <= 16:
        raise RouterTrainingError("one to sixteen bound Cells required")
    if any(type(c) is not RouterCellV1 or not isinstance(c.cell_id, str)
           or not re.fullmatch(r"[A-Za-z0-9_.:-]{1,128}", c.cell_id) for c in cells):
        raise RouterTrainingError("invalid Cell descriptor")
    ordered = tuple(sorted(cells, key=lambda c: c.cell_id))
    if len({c.cell_id for c in ordered}) != len(ordered):
        raise RouterTrainingError("duplicate Cell ID")
    bindings, origins, signature = [], {}, None
    for cell in ordered:
        if (type(cell.head) is not TrainedCellHeadV1
                or type(cell.cost_units) not in (float, int)
                or not math.isfinite(cell.cost_units) or not 0 < cell.cost_units <= 1e9):
            raise RouterTrainingError("invalid frozen Head or declared cost")
        report = cell.head.report
        if (report.get("authority") != "DENY_ALL" or report.get("mode") != "SHADOW_ONLY"
                or report.get("production_activation_allowed") is not False
                or asdict(cell.head.identity) != report["feature_identity"]
                or _state_digest(cell.head._head) != report["trained_tensor_sha256"]
                or any(p.requires_grad for p in cell.head._head.parameters())):
            raise RouterTrainingError("Cell identity, frozen state or research boundary changed")
        current = (cell.head.identity, report["feature_width"], report["config"]["task_count"])
        if signature is not None and current != signature:
            raise RouterTrainingError("Cell feature/task spaces differ")
        signature = current
        if (not isinstance(cell.head_source_groups, Mapping)
                or set(cell.head_source_groups) != set(report["splits"])):
            raise RouterTrainingError("complete Head source-group witness required")
        origins[cell.cell_id] = {}
        for name, split in report["splits"].items():
            groups = cell.head_source_groups[name]
            if (not isinstance(groups, (list, tuple))
                    or any(not isinstance(g, str) or not 1 <= len(g) <= 256 for g in groups)
                    or len(groups) != len(split["source_record_digests"])
                    or len(set(groups)) != split["unique_source_groups"]
                    or hashlib.sha256(_json_bytes(groups)).hexdigest() != split["source_group_sha256"]):
                raise RouterTrainingError("Head source-group witness does not match report")
            origins[cell.cell_id][name] = (set(split["source_record_digests"]), set(groups))
        bindings.append({"cell_id": cell.cell_id, "cost_units": float(cell.cost_units),
                         "head_tensor_sha256": report["trained_tensor_sha256"],
                         "head_report_sha256": hashlib.sha256(_json_bytes(report)).hexdigest()})
    return ordered, bindings, signature, origins


class _RouterNet(nn.Module):
    def __init__(self, width, count, hidden):
        super().__init__()
        self.register_buffer("mean", torch.zeros(width, dtype=torch.float32))
        self.register_buffer("scale", torch.ones(width, dtype=torch.float32))
        self.layers = (nn.Sequential(nn.Linear(width, hidden, dtype=torch.float32), nn.Tanh(),
                                    nn.Linear(hidden, count, dtype=torch.float32))
                       if hidden else nn.Linear(width, count, dtype=torch.float32))

    def forward(self, features):
        return self.layers(((features.float() - self.mean) / self.scale).clamp(-20, 20))


def _new_router(width, count, config):
    with torch.random.fork_rng(devices=[]):
        torch.manual_seed(config.seed)
        return _RouterNet(width, count, config.hidden_width)


def _subset(bundle, indices):
    indices = torch.tensor(indices, dtype=torch.int64)
    views = {name: value.index_select(0, indices) for name, value in bundle.snapshot().items()}
    return FeatureBundleV1.from_tensors(identity=bundle.identity,
        source_record_digests=tuple(bundle.source_record_digests[i] for i in indices.tolist()), **views)


def _choose(order, cells, allowed, top_k, budget):
    chosen, spent = [], 0.0
    for i in order:
        if cells[i].cell_id in allowed and spent + cells[i].cost_units <= budget:
            chosen.append(i)
            spent += cells[i].cost_units
            if len(chosen) == top_k:
                break
    if not chosen:
        raise RouterTrainingError("no legal candidate within the declared budget")
    return chosen


class TrainedCellRouterV1:
    def __init__(self, net, identity: FeatureIdentityV1, report):
        self._net = net.eval().requires_grad_(False)
        self.identity = identity
        self._report = copy.deepcopy(report)

    @property
    def report(self):
        return copy.deepcopy(self._report)

    def predict_task(self, bundle, cells, *, allowed_cell_ids=None, fixed_cell_ids=None,
                     budget_units=None):
        """Route without labels; only selected example/Head pairs execute.

        fixed_cell_ids is a measured fixed-route control under the same cap.
        Runtime may restrict candidates or reduce, but cannot raise, the cap.
        """
        ordered, bindings, signature, _ = _check_cells(cells)
        if (bindings != self._report["cell_bindings"] or signature[0] != self.identity
                or asdict(self.identity) != self._report["feature_identity"]
                or _state_digest(self._net) != self._report["trained_tensor_sha256"]):
            raise RouterTrainingError("Router/Cell artifact binding changed")
        if type(bundle) is not FeatureBundleV1:
            raise RouterTrainingError("typed FeatureBundle required")
        bundle.require_identity(self.identity)
        features = bundle.read_global().float()
        if features.shape[1] != self._report["feature_width"]:
            raise RouterTrainingError("Router feature width changed")
        config = RouterTrainingConfigV1(**self._report["config"])
        config.validate()
        budget = config.budget_units if budget_units is None else budget_units
        if (type(budget) not in (int, float) or not math.isfinite(budget)
                or not 0 < budget <= config.budget_units):
            raise RouterTrainingError("runtime budget must be within the trained cap")
        ids = tuple(c.cell_id for c in ordered)
        allowed = ids if allowed_cell_ids is None else allowed_cell_ids
        if (not isinstance(allowed, (tuple, list)) or len(set(allowed)) != len(allowed)
                or not set(allowed) <= set(ids)):
            raise RouterTrainingError("invalid candidate allowlist")
        if fixed_cell_ids is not None and (
                not isinstance(fixed_cell_ids, (tuple, list)) or not fixed_cell_ids
                or len(set(fixed_cell_ids)) != len(fixed_cell_ids)
                or not set(fixed_cell_ids) <= set(allowed)
                or len(fixed_cell_ids) > config.top_k
                or sum(ordered[ids.index(i)].cost_units for i in fixed_cell_ids) > budget):
            raise RouterTrainingError("fixed route violates candidate/budget constraints")
        scores = [[None] * len(ids) for _ in range(len(features))]
        if fixed_cell_ids is None:
            with torch.inference_mode():
                tensor_scores = self._net(features)
            if not bool(torch.isfinite(tensor_scores).all()):
                raise RouterTrainingError("nonfinite Router score")
            scores = tensor_scores.tolist()
        selections, ledger = [], []
        for row, scores_row in enumerate(scores):
            rank = (sorted(range(len(ids)), key=lambda i: (scores_row[i], ids[i]))
                    if fixed_cell_ids is None else [ids.index(i) for i in fixed_cell_ids])
            selected = _choose(rank, ordered, allowed, config.top_k, budget)
            selections.append(selected)
            ledger.append({"source_record_digest": bundle.source_record_digests[row],
                "candidates": [{"cell_id": c.cell_id, "predicted_loss_cost": scores_row[i],
                    "declared_cost_units": float(c.cost_units),
                    "legal": c.cell_id in allowed and c.cost_units <= budget}
                    for i, c in enumerate(ordered)],
                "selected": [ids[i] for i in selected], "actual_calls": [],
                "actual_cost_units": 0.0, "budget_units": float(budget),
                "route_mode": "learned" if fixed_cell_ids is None else "fixed"})
        # Every row's selection and budget is finalized before any Head runs.
        probabilities = torch.zeros((len(features), signature[2]), dtype=torch.float64)
        invocations = {}
        for index, cell in enumerate(ordered):
            rows = [row for row, selected in enumerate(selections) if index in selected]
            if not rows:
                continue
            output = cell.head.predict_task(_subset(bundle, rows))["task_probabilities"].double()
            if (output.shape != (len(rows), signature[2]) or not bool(torch.isfinite(output).all())
                    or bool((output < 0).any()) or not torch.allclose(
                        output.sum(1), torch.ones(len(rows), dtype=torch.float64), atol=1e-5)):
                raise RouterTrainingError("invalid selected Head probability output")
            invocations[cell.cell_id] = 1
            for position, row in enumerate(rows):
                probabilities[row] += output[position] / len(selections[row])
                ledger[row]["actual_calls"].append(cell.cell_id)
                ledger[row]["actual_cost_units"] += float(cell.cost_units)
        logits = probabilities.clamp_min(1e-12).log()
        temperature = self._report["temperature"]
        if fixed_cell_ids is not None:
            temperature = (self._report["fixed_temperature"] if list(fixed_cell_ids) ==
                           self._report["fixed_cell_ids"] else 1.0)
            if len(fixed_cell_ids) == 1:
                temperature = self._report["single_cell_temperatures"].get(fixed_cell_ids[0], 1.0)
        probabilities = (logits / temperature).softmax(-1)
        return {"task_logits": logits, "task_probabilities": probabilities,
                "temperature": temperature, "accepted": probabilities.max(-1).values >=
                config.confidence_threshold, "routes": ledger, "head_module_invocations": invocations,
                "router_forward_calls": int(fixed_cell_ids is None),
                "head_example_calls": sum(len(row["actual_calls"]) for row in ledger),
                "actual_cost_units": sum(row["actual_cost_units"] for row in ledger),
                "feature_bundle_sha256": bundle.bundle_digest, "authority": "DENY_ALL"}


def _bundles(cohort):
    return (cohort.bundle,) if type(cohort.bundle) is FeatureBundleV1 else cohort.bundle


def _execution_receipt(outputs):
    return {"routes": [r for o in outputs for r in o["routes"]],
            "head_example_calls": sum(o["head_example_calls"] for o in outputs),
            "head_module_invocations": sum(sum(o["head_module_invocations"].values()) for o in outputs),
            "router_forward_calls": sum(o["router_forward_calls"] for o in outputs),
            "actual_cost_units": sum(o["actual_cost_units"] for o in outputs)}


def _evaluate(router, cohort, view, cells, fixed=False):
    outputs = [router.predict_task(bundle, cells, fixed_cell_ids=(
        router._report["fixed_cell_ids"] if fixed else None)) for bundle in _bundles(cohort)]
    logits = torch.cat([o["task_logits"] for o in outputs])
    return {"metrics": task_metrics(logits, view["labels"], temperature=outputs[0]["temperature"],
                confidence_threshold=router._report["config"]["confidence_threshold"]),
            **_execution_receipt(outputs)}


def train_cell_router(train: HeadCohortV1, calibration: HeadCohortV1,
                      holdouts: Mapping[str, HeadCohortV1], cells,
                      config: RouterTrainingConfigV1 = RouterTrainingConfigV1()):
    if type(config) is not RouterTrainingConfigV1:
        raise RouterTrainingError("typed Router configuration required")
    config.validate()
    ordered, bindings, signature, origins = _check_cells(cells)
    identity, width, task_count = signature
    if len(ordered) < 2 or config.top_k > len(ordered):
        raise RouterTrainingError("Router training requires at least two Cells and valid top_k")
    if (not isinstance(holdouts, Mapping) or not 1 <= len(holdouts) <= 6
            or any(not isinstance(n, str) or not re.fullmatch(r"[a-zA-Z0-9_-]{1,64}", n)
                   or n in ("train", "calibration") for n in holdouts)):
        raise RouterTrainingError("named separate Router holdouts required")
    cohorts = {"train": train, "calibration": calibration, **holdouts}
    views = {name: _cohort(value, task_count) for name, value in cohorts.items()}
    if sum(len(view["rows"]) for view in views.values()) > 4096:
        raise RouterTrainingError("Router cohort row budget exceeded")
    seen_rows, seen_groups = set(), set()
    for name, view in views.items():
        rows, groups = set(view["rows"]), set(view["groups"])
        if (view["identity"] != identity or view["features"].shape[1] != width
                or rows & seen_rows or groups & seen_groups):
            raise RouterTrainingError("Router split identity mismatch or source record/group leakage")
        seen_rows.update(rows)
        seen_groups.update(groups)
        for splits in origins.values():
            for split, (head_rows, head_groups) in splits.items():
                # Reusing a Head's evaluation cohort for Router evaluation is valid;
                # no Router fitting/calibration may consume a prior Head holdout.
                if (name in ("train", "calibration") or split in ("train", "calibration")) and (
                        rows & head_rows or groups & head_groups):
                    raise RouterTrainingError("Head/Router source record/group leakage")
    all_ids = tuple(c.cell_id for c in ordered)
    _choose(range(len(ordered)), ordered, all_ids, config.top_k, config.budget_units)
    observations = []
    for cell in ordered:
        outputs = [cell.head.predict_task(bundle) for bundle in _bundles(train)]
        probabilities = torch.cat([o["task_probabilities"] for o in outputs]).double()
        observed = probabilities.gather(1, views["train"]["labels"][:, None]).squeeze(1)
        observations.append(-observed.clamp_min(1e-12).log())
    nll = torch.stack(observations, dim=1).float()
    costs = torch.tensor([c.cost_units for c in ordered], dtype=torch.float32)
    targets = nll + config.cost_weight * costs
    if not bool(torch.isfinite(targets).all()):
        raise RouterTrainingError("nonfinite observed Cell loss/cost")
    net = _new_router(width, len(ordered), config)
    features = views["train"]["features"]
    net.mean.copy_(features.double().mean(0).float())
    net.scale.copy_(features.double().std(0, unbiased=False).clamp_min(1e-6).float())
    initial = _state_digest(net)
    parameters = tuple(net.parameters())
    optimizer = torch.optim.SGD(parameters, lr=config.learning_rate)
    owner_ids = tuple(id(p) for p in parameters)
    losses = []
    for _ in range(config.steps):
        _verify_optimizer_lifecycle(optimizer)
        if tuple(id(p) for g in optimizer.param_groups for p in g["params"]) != owner_ids:
            raise RouterTrainingError("optimizer crossed the private Router boundary")
        optimizer.zero_grad(set_to_none=True)
        loss = nn.functional.smooth_l1_loss(net(features), targets)
        if not bool(torch.isfinite(loss)):
            raise RouterTrainingError("nonfinite Router training loss")
        loss.backward()
        if any(p.grad is None or not bool(torch.isfinite(p.grad).all()) for p in parameters):
            raise RouterTrainingError("missing/nonfinite Router gradient")
        nn.utils.clip_grad_norm_(parameters, 5.0, error_if_nonfinite=True)
        _verify_optimizer_lifecycle(optimizer)
        optimizer.step()
        losses.append(float(loss.detach()))
    if any(not bool(torch.isfinite(p).all()) for p in parameters):
        raise RouterTrainingError("nonfinite Router weights")
    if _check_cells(ordered)[1] != bindings:
        raise RouterTrainingError("frozen Cells changed during Router training")
    fixed = _choose(sorted(range(len(ordered)), key=lambda i: (float(targets[:, i].mean()),
                    ordered[i].cell_id)), ordered, all_ids, config.top_k, config.budget_units)
    report = {"schema": "hepta.trained-cell-router.v1", "config": asdict(config),
        "feature_identity": asdict(identity), "feature_width": width, "task_count": task_count,
        "cell_bindings": bindings, "initial_tensor_sha256": initial,
        "trained_tensor_sha256": _state_digest(net), "optimizer": "torch.optim.SGD",
        "optimizer_steps": config.steps, "initial_train_loss": losses[0],
        "last_train_loss_before_step": losses[-1], "trainable_parameter_count": sum(p.numel() for p in parameters),
        "encoder_training_steps": 0, "cell_training_steps": 0,
        "objective": "smooth_l1(observed_calibrated_cell_nll + cost_weight * declared_cost)",
        "observed_probability_floor": 1e-12,
        "cost_semantics": "declared_head_example_units_exclude_router_integrity_checks_and_latency",
        "combination": "uniform_probability_average_of_selected_cells",
        "fixed_cell_ids": [ordered[i].cell_id for i in fixed], "fixed_selection_split": "train",
        "temperature": 1.0, "fixed_temperature": 1.0, "single_cell_temperatures": {},
        "calibration_split": "calibration", "arbitrary_fixed_ensemble_temperature": 1.0,
        "equal_budget_comparison": "same_cap_and_top_k_not_necessarily_same_realized_cost",
        "source_groups_disjoint": True, "temporal_provenance_verified": False,
        "training_head_example_calls": len(features) * len(ordered),
        "training_head_cost_units": len(features) * sum(c.cost_units for c in ordered),
        "training_signals": [{"source_record_digest": views["train"]["rows"][row],
            "source_group_sha256": hashlib.sha256(views["train"]["groups"][row].encode()).hexdigest(),
            "actual_calls": list(all_ids), "actual_cost_units": sum(c.cost_units for c in ordered),
            "cells": [{"cell_id": c.cell_id, "observed_nll": float(nll[row, i]),
                       "declared_cost_units": float(c.cost_units), "target": float(targets[row, i])}
                      for i, c in enumerate(ordered)]} for row in range(len(features))],
        "authority": "DENY_ALL", "mode": "SHADOW_ONLY", "production_activation_allowed": False}
    router = TrainedCellRouterV1(net, identity, report)
    # Calibration alters only output temperature, never routing weights/selection.
    calibration_routes = [(None, "temperature", False), (report["fixed_cell_ids"], "fixed_temperature", False)]
    calibration_routes += [([c.cell_id], c.cell_id, True) for c in ordered if c.cost_units <= config.budget_units]
    calibration_receipts = []
    for fixed_route, key, single_cell in calibration_routes:
        outputs = [router.predict_task(bundle, ordered, fixed_cell_ids=fixed_route)
                   for bundle in _bundles(calibration)]
        cal_logits = torch.cat([output["task_logits"] for output in outputs])
        temperature = min(TEMPERATURES, key=lambda t: (float(nn.functional.cross_entropy(
            cal_logits / t, views["calibration"]["labels"])), abs(math.log(t)), t))
        calibration_receipts.append({"calibration_target": key, "single_cell": single_cell,
            "fixed_cell_ids": fixed_route, "temperature": temperature, **_execution_receipt(outputs)})
        if single_cell:
            router._report["single_cell_temperatures"][key] = temperature
        else:
            router._report[key] = temperature
    router._report["splits"] = {name: {"bundle_digests": views[name]["bundle_digests"],
        "source_record_digests": list(views[name]["rows"]),
        "source_group_sha256": hashlib.sha256(_json_bytes(views[name]["groups"])).hexdigest(),
        "labels_sha256": hashlib.sha256(views[name]["labels"].numpy().tobytes()).hexdigest(),
        "learned": _evaluate(router, cohort, views[name], ordered),
        "fixed": _evaluate(router, cohort, views[name], ordered, fixed=True)}
        for name, cohort in cohorts.items()}
    router._report["calibration_routes"] = calibration_receipts
    target_receipt = {"head_example_calls": report["training_head_example_calls"],
        "head_module_invocations": len(_bundles(train)) * len(ordered), "router_forward_calls": 0,
        "actual_cost_units": report["training_head_cost_units"]}
    optimizer_receipt = {"head_example_calls": 0, "head_module_invocations": 0,
                         "router_forward_calls": config.steps, "actual_cost_units": 0.0}
    def total(receipts):
        return {key: sum(r[key] for r in receipts) for key in target_receipt}
    evaluation_receipts = [split[arm] for split in router._report["splits"].values()
                           for arm in ("learned", "fixed")]
    router._report["execution_accounting"] = {"target_collection": target_receipt,
        "optimizer_training": optimizer_receipt,
        "temperature_calibration": total(calibration_receipts),
        "reported_evaluation": total(evaluation_receipts),
        "total": total([target_receipt, optimizer_receipt, *calibration_receipts, *evaluation_receipts])}
    return router
