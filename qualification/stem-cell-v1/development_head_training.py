"""Bounded, independently clipped Linear/SwiGLU Cell training on shared frozen features.

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


class SwiGLUCellHead(nn.Module):
    """Per-Cell input-dependent SiLU gate, value projection and shared-width readout.

    This is a bounded research Head, not an Encoder or persistent Cell owner.
    The gate is learned and input-dependent; it is not an affine export profile.
    """

    def __init__(self, width, hidden, classes):
        super().__init__()
        if (any(type(v) is not int for v in (width, hidden, classes))
                or not 1 <= width <= 512 or not 1 <= hidden <= 256
                or not 2 <= classes <= 128):
            raise ValueError("unsupported gated Head dimensions")
        self.gate = nn.Linear(width, hidden)
        self.value = nn.Linear(width, hidden)
        self.readout = nn.Linear(hidden, classes)

    def forward(self, x):
        return self.readout(F.silu(self.gate(x)) * self.value(x))


def fit_linear_cells(initials, features, row_indices, labels, *, seeds,
                     steps=80, group_size=32, batch_size=32, lr=0.02):
    """Original Linear profile; defaults, loss and per-Cell SGD stay unchanged."""
    return _fit_cells(initials, features, row_indices, labels, seeds=seeds, steps=steps,
                      group_size=group_size, batch_size=batch_size, lr=lr, family="linear")


def fit_gated_cells(initials, features, row_indices, labels, *, seeds,
                    steps=80, group_size=32, batch_size=32, lr=0.02):
    """Independent SwiGLU Heads, using the same fitter and per-Cell SGD profile."""
    return _fit_cells(initials, features, row_indices, labels, seeds=seeds, steps=steps,
                      group_size=group_size, batch_size=batch_size, lr=lr, family="swiglu")


def _fit_cells(initials, features, row_indices, labels, *, seeds,
               steps, group_size, batch_size, lr, family):
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
        if family == "linear":
            if type(head) is not nn.Linear:
                raise ValueError("homogeneous Linear Heads required")
            layers = (head,)
        else:
            if (type(head) is not SwiGLUCellHead
                    or tuple(head._modules) != ("gate", "value", "readout")
                    or any(type(layer) is not nn.Linear for layer in head.children())):
                raise ValueError("homogeneous bounded SwiGLU Heads required")
            layers = (head.gate, head.value, head.readout)
            if (layers[0].in_features != layers[1].in_features
                    or layers[0].out_features != layers[1].out_features
                    or layers[0].out_features != layers[2].in_features
                    or not 1 <= layers[0].out_features <= 256):
                raise ValueError("incompatible gated projections")
        if (layers[0].in_features != features.shape[1]
                or not 2 <= layers[-1].out_features <= 128
                or type(seed) is not int or not 0 <= seed < 2**63
                or any(layer.bias is None or tuple(layer._parameters) != ("weight", "bias")
                       or layer.weight.shape != (layer.out_features, layer.in_features)
                       or layer.bias.shape != (layer.out_features,) for layer in layers)
                or len(tuple(head.parameters())) != 2 * len(layers)
                or any(not p.requires_grad or p.device.type != "cpu" or p.dtype != features.dtype
                       or not torch.isfinite(p).all() for p in head.parameters())
                or tuple(head.buffers())):
            raise ValueError("finite, trainable, homogeneous CPU Head parameters required")
        current = tuple((layer.in_features, layer.out_features) for layer in layers)
        if shape is not None and shape != current:
            raise ValueError("mixed Cell Head dimensions")
        shape = current
        if (not isinstance(rows, torch.Tensor) or rows.device.type != 'cpu'
                or rows.dtype != torch.long or rows.ndim != 1 or not 1 <= len(rows) <= 4096
                or bool(((rows < 0) | (rows >= len(features))).any())):
            raise ValueError("invalid per-Cell training row indices")
        labels_checked(gold, len(rows), layers[-1].out_features)
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
    width, classes = shape[0][0], shape[-1][1]
    for offset in range(0, len(initials), group_size):
        end = min(len(initials), offset + group_size)
        group_clock = PhaseClock()
        selected = initials[offset:end]
        rows, gold = rows_private[offset:end], gold_private[offset:end]
        names = tuple(dict(selected[0].named_parameters()))
        parameters = tuple(nn.Parameter(torch.stack([dict(h.named_parameters())[name].detach()
                                                     for h in selected])) for name in names)
        optimizer = torch.optim.SGD(parameters, lr=lr)
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
            if family == "linear":
                weight, bias = parameters
                logits = torch.bmm(batch, weight.transpose(1, 2)) + bias[:, None, :]
            else:
                gw, gb, vw, vb, ow, ob = parameters
                gate = F.silu(torch.bmm(batch, gw.transpose(1, 2)) + gb[:, None, :])
                value = torch.bmm(batch, vw.transpose(1, 2)) + vb[:, None, :]
                logits = torch.bmm(gate * value, ow.transpose(1, 2)) + ob[:, None, :]
            per_row = F.cross_entropy(logits.reshape(-1, classes), target.reshape(-1),
                                      reduction='none', ignore_index=-100).reshape(len(selected), samples)
            losses = per_row.sum(1) / torch.tensor(counts, dtype=features.dtype)
            if not torch.isfinite(losses).all():
                raise ValueError("nonfinite grouped loss")
            optimizer.zero_grad(set_to_none=True)
            losses.sum().backward()
            # Match clip_grad_norm_ over ALL parameters of EACH Head, not the bank.
            component_norms = torch.stack([torch.linalg.vector_norm(p.grad.flatten(1), 2, dim=1)
                                           for p in parameters], 1)
            norms = torch.linalg.vector_norm(component_norms, 2, dim=1)
            if not torch.isfinite(norms).all():
                raise ValueError("nonfinite per-Cell gradient norm")
            scale = (1.0 / (norms + 1e-6)).clamp(max=1.0)
            clip_counts += (scale < 1).long()
            for p in parameters:
                p.grad.mul_(scale.reshape((-1,) + (1,) * (p.ndim - 1)))
            optimizer.step()
            last_loss = losses.detach()
        if any(not torch.isfinite(p).all() for p in parameters):
            raise ValueError("nonfinite trained bank")
        for i, source in enumerate(selected):
            candidate = deepcopy(source).eval()
            with torch.no_grad():
                for target, learned in zip(candidate.parameters(), parameters):
                    target.copy_(learned[i])
            trained.append(candidate)
            reports.append({"steps": steps, "examples_processed": counts[i] * steps,
                            "training_rows_available": len(rows[i]), "clipped_steps": int(clip_counts[i]),
                            "minibatch_sha256": sequence_hashes[i].hexdigest(),
                            "trainable_parameters": sum(p.numel() for p in source.parameters()),
                            "last_training_loss": float(last_loss[i]),
                            "group_index": len(groups), "production_authorized": False})
        groups.append({"first_cell": offset, "cells": len(selected), "padded_batch_width": samples,
                       "useful_example_updates": steps * sum(counts),
                       "physical_example_lanes": steps * len(selected) * samples,
                       "optimizer_steps": steps, **group_clock.finish()})
    if tuple(parameter_digest(h) for h in initials) != initial_digests:
        raise RuntimeError("source Head parameters changed during fitting")
    return tuple(trained), {"profile": "independent_sgd_cross_entropy_norm1_v1", "head_family": family,
                            "cells": reports, "groups": groups,
                            "initial_digests": initial_digests,
                            "candidate_digests": tuple(parameter_digest(h) for h in trained),
                            "shared_feature_bytes": frozen.numel() * frozen.element_size(),
                            "candidate_parameter_bytes": total_parameters * frozen.element_size(),
                            "feature_table_copies": 1,
                            "admission": admission, "total": clock.finish(),
                            "encoder_executed": False, "rss_measured": False,
                            "production_authorized": False}
