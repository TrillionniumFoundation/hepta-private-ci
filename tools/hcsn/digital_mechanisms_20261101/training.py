"""Common supervised budgets with optional actual greedy-state aggregation."""
import hashlib
import time

import numpy as np
import torch
import torch.nn.functional as F

from .execution import collect_visits, occupancy_key
from .models import MechanismPolicy


def candidates():
    output = []
    families = ("ordinary_base", "ordinary_bank", "clocked_bank", "first_passage_bank", "raw_history")
    for family in families:
        for method in ("free_off", "structured_off", "structured_on"):
            output.append(dict(id=f"{family}__{method}", family=family,
                               terminal_mode="free" if method == "free_off" else "structured",
                               drive_mode="sustained", on_policy=method.endswith("_on"), budget="updates"))
    for family in ("ordinary_bank", "clocked_bank", "first_passage_bank"):
        output.append(dict(id=f"{family}__impulse_on", family=family,
                           terminal_mode="structured", drive_mode="impulse", on_policy=True, budget="updates"))
    for method in ("free_off", "structured_on"):
        output.append(dict(id=f"evidence_accumulator__{method}", family="evidence_accumulator",
                           terminal_mode="free" if method == "free_off" else "structured",
                           drive_mode="accumulator", on_policy=method.endswith("_on"), budget="updates"))
    for identifier in ("ordinary_bank__structured_on", "first_passage_bank__structured_on",
                       "first_passage_bank__impulse_on", "evidence_accumulator__structured_on"):
        spec = next(x for x in output if x["id"] == identifier).copy()
        spec.update(id=identifier + "__cpu", budget="cpu")
        output.append(spec)
    return output


def loss_for_rows(policy, rows, protocol):
    """Exact fixed-behavior expectation or recorded realized on-policy state.

    A policy-dependent prefix must never be reweighted by the unconditioned
    prefix_mass. On-policy rows use their recorded realized index; occupancy is
    detached. This is supervised dataset aggregation, not a policy gradient.
    """
    cache = {}
    inputs = torch.stack([policy.latent_inputs(r["public"], r["state"], cache) for r in rows])
    masses = []
    for row in rows:
        if "latent_index" in row:
            index = int(row["latent_index"])
            if not 0 <= index < inputs.shape[1]:
                raise ValueError("recorded latent index incompatible with model")
            mass = inputs.new_zeros(inputs.shape[1])
            mass[index] = 1.
        else:
            mass = policy.prefix_mass(row["prefix"], cache)
        masses.append(mass)
    mass = torch.stack(masses)
    if float((mass.detach().sum(-1) - 1).abs().max()) > 2e-9 or float(mass.detach().min()) < -2e-10:
        raise FloatingPointError("invalid supervised conditional mass")
    output = policy(inputs)
    target = inputs.new_tensor([r["q"] for r in rows])
    mask = torch.tensor([r["legal"] for r in rows], dtype=torch.bool)
    belief = inputs.new_tensor([r["posterior"] for r in rows])
    qloss = ((output[..., :6] - target[:, None]).square() * mask[:, None]).sum(-1) / mask.sum(-1)[:, None]
    bloss = F.binary_cross_entropy_with_logits(output[..., 6], belief[:, None].expand_as(output[..., 6]), reduction="none")
    loss = (mass * (qloss + protocol["belief_loss_weight"] * bloss)).sum(-1).mean()
    if policy.cell is not None:
        loss = loss + protocol["raw_regularizer"] * policy.cell.raw[:policy.cell.effective_parameter_count].square().sum()
    if not bool(torch.isfinite(loss)):
        raise FloatingPointError("nonfinite supervised loss")
    return loss


def fit_candidate(spec, fit, data, adapter, protocol):
    start = time.process_time()
    policy = MechanismPolicy(spec["family"], fit, spec["terminal_mode"], spec["drive_mode"])
    optimizer = torch.optim.AdamW(policy.parameters(), lr=protocol["learning_rate"], weight_decay=protocol["weight_decay"])
    initial = {k: v.detach().clone() for k, v in policy.state_dict().items()}
    rng = np.random.default_rng(protocol["batch_seed_base"] + fit)
    behavior = data["train"]["rows"]
    visits, visit_receipts, update_rows = [], [], []
    setup_cpu = time.process_time() - start
    learning_start = time.process_time()
    aggregated = False
    batch_digest = hashlib.sha256()
    while True:
        elapsed = time.process_time() - learning_start
        count = len(update_rows)
        if ((spec["budget"] == "updates" and count >= protocol["updates"]) or
                (spec["budget"] == "cpu" and elapsed >= protocol["training_cpu_seconds"])):
            break
        half = (count >= protocol["updates"] // 2 if spec["budget"] == "updates" else
                elapsed >= protocol["training_cpu_seconds"] / 2)
        if spec["on_policy"] and half and not aggregated:
            visits, receipt = collect_visits(policy, data["train_cohort"]["records"], adapter,
                                             data["confusion"], protocol["occupancy_seed_base"] + fit * 10000)
            visit_receipts.append(receipt)
            aggregated = True
            # Collection and fitted-target computation consume the same learning CPU budget.
            continue
        size = protocol["batch_states"]
        off_count = size if not visits else size // 2
        indices = rng.integers(0, len(behavior), off_count)
        rows = [behavior[int(i)] for i in indices]
        batch_digest.update(indices.astype("<i8").tobytes())
        if visits:
            indices = rng.integers(0, len(visits), size - off_count)
            rows.extend(visits[int(i)] for i in indices)
            batch_digest.update(indices.astype("<i8").tobytes())
        optimizer.zero_grad(set_to_none=True)
        loss = loss_for_rows(policy, rows, protocol)
        loss.backward()
        if any(p.grad is not None and not bool(torch.isfinite(p.grad).all()) for p in policy.parameters()):
            raise FloatingPointError("nonfinite candidate gradient")
        norm = float(torch.nn.utils.clip_grad_norm_(policy.parameters(), protocol["gradient_clip"]))
        optimizer.step()
        update_rows.append(dict(update=count + 1, loss=float(loss.detach()), gradient_norm=norm,
                                mixed_realized_records=len(rows) - off_count,
                                cumulative_learning_cpu_seconds=time.process_time() - learning_start))
    learning_cpu = time.process_time() - learning_start
    artifact = policy.export()
    changes = {k: float(torch.linalg.vector_norm(v.detach() - initial[k])) for k, v in policy.state_dict().items()}
    coverage = sorted(set(occupancy_key(row["state"]) for row in behavior))
    augmented_coverage = sorted(set(occupancy_key(row["state"]) for row in visits))
    receipt = dict(spec=spec, fit=fit, setup_cpu_seconds=setup_cpu,
                   learning_cpu_seconds=learning_cpu, optimizer_updates=len(update_rows),
                   training_cpu_budget=protocol["training_cpu_seconds"] if spec["budget"] == "cpu" else None,
                   cpu_budget_overshoot=max(0., learning_cpu - protocol["training_cpu_seconds"]) if spec["budget"] == "cpu" else 0.,
                   batch_size=protocol["batch_states"], minibatch_sha256=batch_digest.hexdigest(),
                   behavior_records=len(behavior), realized_visit_records=len(visits),
                   visit_collection_count=len(visit_receipts), visit_receipts=visit_receipts,
                   behavior_occupancy_keys=coverage, augmented_occupancy_keys=augmented_coverage,
                   capacity=policy.capacity_report(), parameter_shift_l2=changes,
                   final_update_selected=True, policy_gradient_claim=False,
                   updates=update_rows, validation_used_for_checkpoint_selection=False)
    return policy, artifact, receipt
