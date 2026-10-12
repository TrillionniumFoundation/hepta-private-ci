"""Bounded, independently clipped Linear Cell training on shared frozen features.

Ordinary Torch only: no code generation, native loader, effect or authority.
Callers retain scope/fold admission and candidate selection. This is the same
SGD/mean cross-entropy/per-Cell norm-1 profile as development_ablation.fit_candidate,
not a new optimizer objective. Numerical equivalence is tested, not assumed.
"""

from copy import deepcopy
import hashlib

import torch
from torch import nn
from torch.nn import functional as F

from development_ablation import PhaseClock, labels_checked
from development_tensors import checked_tensor, parameter_digest


MAX_PARAMETERS = 4_194_304


def fit_linear_cells(initials, features, row_indices, labels, *, seeds,
                     steps=80, group_size=32, batch_size=32, lr=0.02):
    """Fit 1..4096 independent candidates, at most 32 Cells in one tensor group.

    Each Cell owns its random minibatch stream and gradient norm. Losses are
    summed across Cells AFTER averaging each Cell's actual (unpadded) rows.
    Only supplied Cells get candidate copies; absent/dormant peer state cannot
    decay. The function receives no holdout labels and never updates the inputs.
    All shape/range checks precede the first optimizer or candidate allocation.
    Whole-call CPU/wall includes admission, input copy, RNG, and output copies.
    """
    clock = PhaseClock()
    if (type(initials) is not tuple or not 1 <= len(initials) <= 4096
            or any(type(v) is not tuple or len(v) != len(initials)
                   for v in (row_indices, labels, seeds))
            or type(steps) is not int or not 1 <= steps <= 1000
            or type(group_size) is not int or not 1 <= group_size <= 32
            or type(batch_size) is not int or not 1 <= batch_size <= 32
            or type(lr) not in (int, float) or not 0 < lr <= 1):
        raise ValueError("invalid bounded Cell training envelope")
    checked_tensor(features, 2, "shared frozen feature table")
    if not 1 <= len(features) <= 4096 or not 1 <= features.shape[1] <= 512:
        raise ValueError("unsupported feature table shape")
    shape, total_parameters = None, 0
    for head, rows, gold, seed in zip(initials, row_indices, labels, seeds):
        if (type(head) is not nn.Linear or head.bias is None
                or head.weight.device.type != 'cpu' or head.weight.dtype != features.dtype
                or head.bias.device.type != 'cpu' or head.bias.dtype != features.dtype
                or head.in_features != features.shape[1] or not 2 <= head.out_features <= 128
                or head.weight.shape != (head.out_features, head.in_features)
                or head.bias.shape != (head.out_features,)
                or any(not p.requires_grad or not torch.isfinite(p).all() for p in head.parameters())
                or type(seed) is not int or not 0 <= seed < 2**63):
            raise ValueError("homogeneous finite trainable CPU Linear Heads required")
        current = (head.in_features, head.out_features)
        if shape is not None and shape != current:
            raise ValueError("mixed Cell Head dimensions")
        shape = current
        if (not isinstance(rows, torch.Tensor) or rows.device.type != 'cpu'
                or rows.dtype != torch.long or rows.ndim != 1 or not 1 <= len(rows) <= 4096
                or bool(((rows < 0) | (rows >= len(features))).any())):
            raise ValueError("invalid per-Cell training row indices")
        labels_checked(gold, len(rows), head.out_features)
        total_parameters += sum(p.numel() for p in head.parameters())
    if total_parameters > MAX_PARAMETERS or sum(len(r) for r in row_indices) > MAX_PARAMETERS:
        raise ValueError("training census exceeds bounded tensor inventory")
    admission = clock.finish()
    # Snapshot once, not a copy of the entire feature table for every Cell.
    frozen = features.detach().clone()
    rows_private = tuple(r.detach().clone() for r in row_indices)
    gold_private = tuple(y.detach().clone() for y in labels)
    initial_digests = tuple(parameter_digest(h) for h in initials)
    trained, reports, groups = [], [], []
    width, classes = shape
    for offset in range(0, len(initials), group_size):
        end = min(len(initials), offset + group_size)
        group_clock = PhaseClock()
        selected = initials[offset:end]
        rows, gold = rows_private[offset:end], gold_private[offset:end]
        weight = nn.Parameter(torch.stack([h.weight.detach() for h in selected]))
        bias = nn.Parameter(torch.stack([h.bias.detach() for h in selected]))
        optimizer = torch.optim.SGD((weight, bias), lr=lr)
        rngs = [torch.Generator(device='cpu').manual_seed(seed) for seed in seeds[offset:end]]
        counts = [min(len(r), batch_size) for r in rows]
        samples = max(counts)
        clip_counts = torch.zeros(len(selected), dtype=torch.long)
        sequence_hashes = [hashlib.sha256(b'hepta.cell.minibatch.v1') for _ in selected]
        last_loss = None
        for _ in range(steps):
            # Padded indices are not observations: ignored labels remove their loss.
            index = torch.zeros(len(selected), samples, dtype=torch.long)
            target = torch.full((len(selected), samples), -100, dtype=torch.long)
            for i, (r, y, rng, count) in enumerate(zip(rows, gold, rngs, counts)):
                local = torch.randperm(len(r), generator=rng)[:count]
                index[i, :count], target[i, :count] = r[local], y[local]
                sequence_hashes[i].update(local.numpy().astype('<i8', copy=False).tobytes())
            batch = frozen[index]
            logits = torch.bmm(batch, weight.transpose(1, 2)) + bias[:, None, :]
            per_row = F.cross_entropy(logits.reshape(-1, classes), target.reshape(-1),
                                      reduction='none', ignore_index=-100).reshape(len(selected), samples)
            losses = per_row.sum(1) / torch.tensor(counts, dtype=features.dtype)
            if not torch.isfinite(losses).all():
                raise ValueError("nonfinite grouped loss")
            optimizer.zero_grad(set_to_none=True)
            losses.sum().backward()
            # Match clip_grad_norm_ over EACH head's weight+bias, never over the bank.
            wn = torch.linalg.vector_norm(weight.grad.flatten(1), 2, dim=1)
            bn = torch.linalg.vector_norm(bias.grad, 2, dim=1)
            norms = torch.linalg.vector_norm(torch.stack((wn, bn), 1), 2, dim=1)
            if not torch.isfinite(norms).all():
                raise ValueError("nonfinite per-Cell gradient norm")
            scale = (1.0 / (norms + 1e-6)).clamp(max=1.0)
            clip_counts += (scale < 1).long()
            weight.grad.mul_(scale[:, None, None])
            bias.grad.mul_(scale[:, None])
            optimizer.step()
            last_loss = losses.detach()
        if not torch.isfinite(weight).all() or not torch.isfinite(bias).all():
            raise ValueError("nonfinite trained bank")
        for i, source in enumerate(selected):
            candidate = deepcopy(source).eval()
            with torch.no_grad():
                candidate.weight.copy_(weight[i])
                candidate.bias.copy_(bias[i])
            trained.append(candidate)
            reports.append({"steps": steps, "examples_processed": counts[i] * steps,
                            "training_rows_available": len(rows[i]), "clipped_steps": int(clip_counts[i]),
                            "minibatch_sha256": sequence_hashes[i].hexdigest(),
                            "trainable_parameters": classes * (width + 1),
                            "last_training_loss": float(last_loss[i]),
                            "group_index": len(groups), "production_authorized": False})
        groups.append({"first_cell": offset, "cells": len(selected), "padded_batch_width": samples,
                       "useful_example_updates": steps * sum(counts),
                       "physical_example_lanes": steps * len(selected) * samples,
                       "optimizer_steps": steps, **group_clock.finish()})
    if tuple(parameter_digest(h) for h in initials) != initial_digests:
        raise RuntimeError("source Head parameters changed during fitting")
    return tuple(trained), {"profile": "independent_sgd_cross_entropy_norm1_v1",
                            "cells": reports, "groups": groups,
                            "initial_digests": initial_digests,
                            "candidate_digests": tuple(parameter_digest(h) for h in trained),
                            "shared_feature_bytes": frozen.numel() * frozen.element_size(),
                            "candidate_parameter_bytes": total_parameters * frozen.element_size(),
                            "feature_table_copies": 1,
                            "admission": admission, "total": clock.finish(),
                            "encoder_executed": False, "rss_measured": False,
                            "production_authorized": False}
