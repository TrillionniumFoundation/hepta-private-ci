"""Actual split-vs-capacity-vs-data experiment using existing Cell operators.

Only base/adaptation/extra labels reach fitting; only calibration reaches
selection. No held-out label is accepted by either public entrypoint.
"""
from __future__ import annotations

from copy import deepcopy
import math
import time

import torch
from torch import nn
from torch.nn import functional as F

from development_tensors import BasisCellHeads, parameter_digest, split_candidate
from model_runner import train_head


class RoutedBank(nn.Module):
    """Frozen feature-space router; not gold task labels or future outcomes."""
    def __init__(self, bank, centers=None):
        super().__init__()
        self.bank = bank
        self.register_buffer("centers", centers)

    def forward(self, x):
        indices = (torch.zeros(len(x), dtype=torch.long) if self.centers is None else
                   (x[:, None, :] - self.centers[None, :, :]).square().sum(-1).argmin(-1))
        return self.bank(x, indices)


def routed_centers(x, labels, parent):
    """Training-only residual initialization followed by bounded two-means."""
    with torch.no_grad():
        residual = F.cross_entropy(parent(x), labels, reduction="none")
        first = int(residual.argmax())
        second = int((x - x[first]).square().sum(-1).argmax())
        centers = x[[first, second]].clone()
        for _ in range(16):
            assignments = (x[:, None, :] - centers[None, :, :]).square().sum(-1).argmin(-1)
            if min(int((assignments == i).sum()) for i in range(2)) < 2:
                return None
            updated = torch.stack([x[assignments == i].mean(0) for i in range(2)])
            if torch.equal(updated, centers):
                break
            centers = updated
        assignments = (x[:, None, :] - centers[None, :, :]).square().sum(-1).argmin(-1)
        if min(int((assignments == i).sum()) for i in range(2)) < 2:
            return None
    return centers


def widen_candidate(parent, seed):
    """Add inactive basis directions, retaining the parent function initially."""
    bank = parent.bank
    larger = BasisCellHeads(bank.width, bank.classes, 2 * bank.rank,
                            bank.cell_ids, generation=bank.generation + 1, seed=seed)
    with torch.no_grad():
        larger.base.load_state_dict(bank.base.state_dict())
        larger.basis[:bank.rank].copy_(bank.basis)
        larger.gate_axes[:bank.rank].copy_(bank.gate_axes)
        larger.coefficients[:, :bank.rank].copy_(bank.coefficients)
        larger.gates[:, :bank.rank].copy_(bank.gates[:, :-1])
        larger.gates[:, -1].copy_(bank.gates[:, -1])
    return RoutedBank(larger)


def fit_record(model, x, y, steps, seed):
    start_cpu, start_wall = time.process_time_ns(), time.perf_counter_ns()
    count = sum(p.numel() for p in model.parameters() if p.requires_grad)
    train_head(torch, model, x, y, steps=steps, seed=seed)
    if any(not torch.isfinite(t).all() for t in model.state_dict().values()):
        raise ValueError("nonfinite fitted parameters")
    model.eval().requires_grad_(False)
    return {"steps": steps, "training_rows": len(x), "sample_presentations": steps * min(32, len(x)),
            "trainable_parameters": count,
            "stored_scalars": sum(t.numel() for t in model.state_dict().values()),
            "cpu_ns": time.process_time_ns() - start_cpu,
            "wall_ns": time.perf_counter_ns() - start_wall,
            "parameter_digest": parameter_digest(model)}


def fit_candidates(base_x, base_y, adapt_x, adapt_y, extra_x, extra_y, config):
    """Five arms share one trained parent; all adaptation arms use the same steps."""
    config.validate()
    total_cpu, total_wall = time.process_time_ns(), time.perf_counter_ns()
    if not 1 <= base_x.shape[1] <= 512:
        raise ValueError("explicit projection required for wide Encoder features")
    # Fitted only on the base training window. No transductive normalization.
    mean, scale = base_x.mean(0), base_x.std(0, unbiased=False).clamp_min(1e-6)
    base_x, adapt_x, extra_x = [(x - mean) / scale for x in (base_x, adapt_x, extra_x)]
    if any(not torch.isfinite(x).all() for x in (base_x, adapt_x, extra_x)):
        raise ValueError("nonfinite normalized training features")
    parent = RoutedBank(BasisCellHeads(base_x.shape[1], config.classes, config.rank,
                                       ("parent",), generation=config.generation, seed=config.seed))
    parent.bank.base.requires_grad_(True)
    parent.bank.basis.requires_grad_(True)
    base_cost = fit_record(parent, base_x, base_y, config.base_steps, config.seed)
    before = parameter_digest(parent)
    models = {"frozen": parent, "continued": deepcopy(parent),
              "wider": widen_candidate(parent, config.seed + 1), "more_data": deepcopy(parent)}
    router_cpu, router_wall = time.process_time_ns(), time.perf_counter_ns()
    centers = routed_centers(adapt_x, adapt_y, parent)
    router_cost = {"cpu_ns": time.process_time_ns() - router_cpu,
                   "wall_ns": time.perf_counter_ns() - router_wall, "training_rows": len(adapt_x)}
    unavailable = {}
    if centers is None:
        unavailable["split"] = "training-only router has fewer than two supported children"
    else:
        child = split_candidate(parent.bank, "parent", "child",
                                maximum_local_parameters=2 * (2 * config.rank + 1))
        models["split"] = RoutedBank(child, centers)
    costs = {"frozen": {"steps": 0, "cpu_ns": 0, "wall_ns": 0,
                        "trainable_parameters": 0, "sample_presentations": 0,
                        "parameter_digest": before,
                        "stored_scalars": sum(v.numel() for v in parent.state_dict().values())}}
    for name in ("continued", "wider", "more_data", "split"):
        if name not in models:
            continue
        model = models[name].requires_grad_(False)
        # One optimizer over selected candidate rows, not one full step budget per child.
        model.bank.coefficients.requires_grad_(True)
        model.bank.gates.requires_grad_(True)
        x, y = ((torch.cat((adapt_x, extra_x)), torch.cat((adapt_y, extra_y)))
                if name == "more_data" else (adapt_x, adapt_y))
        costs[name] = fit_record(model, x, y, config.adaptation_steps, config.seed + 2)
        model.bank.generation = parent.bank.generation + 1
    if parameter_digest(parent) != before:
        raise ValueError("selected frozen parent mutated")
    return models, {"base_training": base_cost, "adaptation": costs, "unavailable": unavailable,
                    "split_router_preparation": router_cost,
                    "all_arm_fit_cpu_ns": time.process_time_ns() - total_cpu,
                    "all_arm_fit_wall_ns": time.perf_counter_ns() - total_wall}, mean, scale


def select_candidate(logits, labels, groups, costs, config):
    """Calibration-only, group-weighted split gate against every unsplit control.

    The Hoeffding lower bound assumes independent source groups; source strings
    do not authenticate that assumption. This is a research decision, no grant.
    """
    controls = ("frozen", "continued", "wider", "more_data")
    if not set(controls) <= set(logits) or labels.shape != (len(groups),):
        raise ValueError("missing paired calibration controls")
    values = {}
    for name, output in logits.items():
        if output.shape != (len(groups), config.classes) or not torch.isfinite(output).all():
            raise ValueError("invalid calibration logits")
        hits = (output.argmax(1) == labels).float().tolist()
        buckets = {}
        for group, hit in zip(groups, hits):
            buckets.setdefault(group, []).append(hit)
        values[name] = {g: sum(v) / len(v) for g, v in buckets.items()}
    def utility(name):
        return sum(values[name].values()) / len(values[name]) - config.scalar_penalty * costs[name]["stored_scalars"]
    best_control = max(controls, key=utility)
    comparisons = {}
    split_supported = "split" in values and len(values[best_control]) >= config.minimum_groups
    if "split" in values:
        n = len(values["split"])
        radius = math.sqrt(2 * math.log(len(controls) / config.alpha) / n)
        for name in controls:
            delta = sum(values["split"][g] - values[name][g] for g in values[name]) / n
            penalty = config.scalar_penalty * (costs["split"]["stored_scalars"] - costs[name]["stored_scalars"])
            lower = delta - radius - penalty
            comparisons[name] = {"group_count": n, "mean_accuracy_delta": delta,
                                 "hoeffding_radius": radius, "scalar_penalty_delta": penalty,
                                 "net_lower_bound": lower}
            split_supported = split_supported and lower > 0
    return {"selected_arm": "split" if split_supported else best_control,
            "split_supported_on_calibration": split_supported,
            "comparisons": comparisons, "best_unsplit_control": best_control,
            "independent_groups_authenticated": False,
            "production_authorized": False}
