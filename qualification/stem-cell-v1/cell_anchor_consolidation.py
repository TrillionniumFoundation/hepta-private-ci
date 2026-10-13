"""Training-only affine nullspace updates; no live model or Encoder mutation.

FiLM is folded into one affine Head. The projection constrains the *actual*
parameter delta after AdamW, not only gradients. Memory guarantees concern the
registered old input span; unseen inputs still need the original retention test.
"""
from __future__ import annotations

from copy import deepcopy
import time

import torch
from torch.nn import functional as F

from cell_consolidation import training_partition
from cell_consolidation_study import affine_logits
from development_tensors import checked_tensor

EXTRA_ARMS = ("affine_unconstrained", "anchor_memory", "anchor_all_old")
ANCHOR_TOLERANCE = 1e-4  # final packed float32 Head versus frozen FiLM


def fold_film(tensors, width, classes):
    """Validate existing FiLM inventory and fold it in float64, including bias."""
    affine_logits(tensors, torch.zeros(1, width), classes)
    t = {k: v.detach().double().clone() for k, v in tensors.items()}
    weight = t["readout.weight"] * t["gamma"]
    bias = t["readout.bias"] + t["readout.weight"] @ t["beta"]
    result = torch.cat((weight, bias[:, None]), 1)
    checked_tensor(result, 2, "folded teacher")
    return result


def anchor_basis(anchors):
    """Economy SVD, no autograd or dense d-by-d projector. Empty = no constraint."""
    if (not isinstance(anchors, torch.Tensor) or anchors.ndim != 2
            or anchors.dtype != torch.float64 or anchors.device.type != "cpu"
            or not 0 <= len(anchors) <= 512 or not 2 <= anchors.shape[1] <= 513
            or not torch.isfinite(anchors).all()):
        raise ValueError("invalid bounded augmented anchor matrix")
    if not len(anchors):
        return anchors.clone(), 0.0
    with torch.no_grad():
        _, singular, vh = torch.linalg.svd(anchors, full_matrices=False)
        threshold = torch.finfo(torch.float64).eps * max(anchors.shape) * float(singular[0])
        basis = vh[singular > threshold].contiguous()
        if (not torch.isfinite(basis).all() or not torch.isfinite(singular).all()
                or float((anchors - (anchors @ basis.T) @ basis).abs().max()) > 1e-8):
            raise ValueError("old input span cannot be represented at fixed tolerance")
    return basis, threshold


def train_affine(base, memory, new, probabilities, anchors, config):
    """Same T=2 KL, initialization, minibatches and 200 steps in all new arms.

    The full delta is projected after EVERY optimizer step. Adam moments and
    weight decay therefore cannot take the actual update out of the nullspace.
    Output is packed back to one float32 affine Head; basis is training-only.
    """
    config.validate()
    for x in (base, memory, new, probabilities):
        checked_tensor(x, 2, "anchor fitting")
        if x.dtype != torch.float64:
            raise ValueError("constrained fitting requires float64")
    if not isinstance(anchors, torch.Tensor) or anchors.ndim != 2:
        raise ValueError("invalid augmented anchors")
    d, k = base.shape[1], base.shape[0]
    if (not 2 <= d <= 513 or k != config.classes or memory.shape[1] != d or new.shape[1] != d
            or len(memory) > 512 or len(new) > 4096 or anchors.shape[1] != d
            or probabilities.shape != (len(memory)+len(new), k)
            or (probabilities < 0).any() or not torch.allclose(probabilities.sum(1), torch.ones(len(probabilities), dtype=torch.float64), atol=1e-8, rtol=0)):
        raise ValueError("invalid anchor training dimensions or probabilities")
    start = time.process_time_ns(), time.perf_counter_ns()
    basis, threshold = anchor_basis(anchors)
    x = torch.cat((memory, new)).detach().clone()
    target = probabilities.detach().clone()
    delta = torch.nn.Parameter(torch.zeros_like(base))
    optimizer = torch.optim.AdamW([delta], lr=1e-3, weight_decay=.01)
    rng = torch.Generator().manual_seed(config.seed+2)
    max_residual = 0.0
    for _ in range(config.steps):
        ids = torch.cat((torch.randint(len(memory), (16,), generator=rng),
                         len(memory)+torch.randint(len(new), (16,), generator=rng)))
        logits = x[ids] @ (base.detach()+delta).T
        loss = F.kl_div(F.log_softmax(logits/config.temperature, -1), target[ids],
                        reduction="batchmean") * config.temperature**2
        if not torch.isfinite(loss):
            raise ValueError("nonfinite constrained training loss")
        optimizer.zero_grad(set_to_none=True)
        loss.backward()
        if not torch.isfinite(delta.grad).all():
            raise ValueError("nonfinite constrained gradient")
        optimizer.step()
        with torch.no_grad():
            delta.sub_((delta @ basis.T) @ basis)
            if not torch.isfinite(delta).all():
                raise ValueError("nonfinite projected update")
            residual = float((anchors @ delta.T).abs().max()) if len(anchors) else 0.0
            max_residual = max(max_residual, residual)
            if residual > 1e-8:
                raise ValueError("actual optimizer update violates old-input constraint")
    final = (base.detach()+delta.detach()).float()
    checked_tensor(final, 2, "packed affine candidate")
    return {"weight": final[:, :-1].contiguous(), "bias": final[:, -1].contiguous()}, {
        "cpu_ns": time.process_time_ns()-start[0], "wall_ns": time.perf_counter_ns()-start[1],
        "steps": config.steps, "sample_presentations": config.steps*32,
        "anchor_rows": len(anchors), "constraint_rank": len(basis), "free_input_dimensions": d-len(basis),
        "rank_threshold": threshold, "max_training_anchor_residual": max_residual,
        "anchor_tensor_bytes": anchors.numel()*8, "basis_tensor_bytes": basis.numel()*8,
        "delta_parameter_bytes": base.numel()*8, "optimizer_moment_bytes": base.numel()*16,
        "target_probability_bytes": target.numel()*8, "deployed_parameters": final.numel(),
        "deployed_weight_bytes": final.numel()*4, "current_encoder_calls": 0,
        "production_authorized": False}


def fit_anchors(inputs, truth, features, config, teachers):
    """Only old-base/adapt labels; reuse sealed teachers without retraining them."""
    old, new, memory = training_partition(inputs, truth, config)
    checked_tensor(features, 2, "raw frozen features")
    if features.dtype != torch.float32 or len(features) != len(inputs) or not 1 <= features.shape[1] <= 512:
        raise ValueError("invalid source feature shape")
    teachers = deepcopy(teachers)
    if set(teachers) != {"frozen", "new_only"}:
        raise ValueError("two fixed teacher checkpoints required")
    mean = features[old].mean(0)
    scale = features[old].std(0, unbiased=False).clamp_min(1e-6)
    x = {n: (features[ids].detach()-mean)/scale for n, ids in (("old", old), ("new", new), ("memory", memory))}
    with torch.no_grad():
        target = torch.cat((affine_logits(teachers["frozen"], x["memory"], config.classes),
                            affine_logits(teachers["new_only"], x["new"], config.classes))).double()
        target = F.softmax(target/config.temperature, -1)
        base = fold_film(teachers["frozen"], features.shape[1], config.classes)
        xx = {n: torch.cat((v.double(), torch.ones(len(v), 1, dtype=torch.float64)), 1) for n, v in x.items()}
    candidates, costs = {}, {}
    for name, anchors in zip(EXTRA_ARMS, (xx["old"][:0], xx["memory"], xx["old"])):
        candidate, cost = train_affine(base, xx["memory"], xx["new"], target, anchors, config)
        ids = memory if name == "anchor_memory" else old if name == "anchor_all_old" else []
        cost["anchor_indices"] = ids
        if ids:
            probe = (features[ids]-mean)/scale
            observed = probe @ candidate["weight"].T + candidate["bias"]
            reference = affine_logits(teachers["frozen"], probe, config.classes)
            drift = float((observed-reference).abs().max())
            if drift > ANCHOR_TOLERANCE:
                raise ValueError("float32 packed Head violates anchor drift ceiling")
            cost["packed_anchor_max_error"] = drift
        else:
            cost["packed_anchor_max_error"] = None
        candidates[name], costs[name] = candidate, cost
    return candidates, costs
