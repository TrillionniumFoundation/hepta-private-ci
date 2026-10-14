"""Batch the existing independent Head/AdamW learning profile on frozen features.

This does not average Cells' losses, gradients, moments or parameters. Bucket by
fixed step count and actual minibatch length: no padding, idle updates or Adam
state compaction. Source Heads, feature table and global RNG remain unchanged.
No encoder, evaluator, selector, optimizer resume or production owner is added.
"""
from collections import defaultdict
from copy import deepcopy
import hashlib

import torch
from torch.func import functional_call, stack_module_state
from torch.nn import functional as F

from experiments.shared_stem_cell.execution import Head, InputError, integer, measured, parameters
from experiments.shared_stem_cell.head_artifacts import _shape_count

MAX_PARAMETERS_BYTES = 64 * 1024**2
MAX_FEATURE_BYTES = 64 * 1024**2
ATOL, RTOL = 2e-5, 2e-4  # training-roundoff diagnostic, fixed before measurements


def fit_cells(initials, features, row_indices, labels, *, seeds, step_counts,
              batch=16, group_size=32, maximum_parameter_bytes=MAX_PARAMETERS_BYTES):
    """Return ordinary candidate Heads in input order and real learning counters.

All source/fold/Scope admission belongs to the caller. Features and row maps are
copied once after complete preflight; only training labels enter this API. Each
Cell samples with its own torch.Generator exactly as execution.fit does. Loss is
mean within each Cell, SUM across Cells, then norm-1 clipping is PER CELL. Stock
AdamW keeps independent elementwise moments with equal step counters inside each
bucket. Zero-step candidates never enter an optimizer. Parameter admission caps
candidate bytes, not RSS/autograd/BLAS workspace. No asynchronous input mutation
or arbitrary in-process code is supported as a security boundary.
"""
    with measured() as whole:
        if type(initials) is not tuple or not 1 <= len(initials) <= 4096:
            raise InputError("bounded existing Head tuple required")
        if any(type(v) is not tuple or len(v) != len(initials)
               for v in (row_indices, labels, seeds, step_counts)):
            raise InputError("complete per-Cell training tuples required")
        integer(batch, 1, 256, "training batch")
        integer(group_size, 1, 32, "training group")
        integer(maximum_parameter_bytes, 1, MAX_PARAMETERS_BYTES, "candidate parameter budget")
        if (type(features) is not torch.Tensor or features.device.type != "cpu"
                or features.dtype != torch.float32 or features.ndim != 2
                or not 1 <= len(features) <= 16384 or not 1 <= features.shape[1] <= 8192
                or features.numel() * 4 > MAX_FEATURE_BYTES or not torch.isfinite(features).all()):
            raise InputError("bounded finite CPU float32 frozen features required")
        architecture, census, total_rows = None, 0, 0
        for head, rows, y, seed, steps in zip(initials, row_indices, labels, seeds, step_counts):
            integer(seed, 0, 2**63 - 1, "Cell seed")
            integer(steps, 0, 1000, "Cell steps")
            if type(head) is not Head or head.training:
                raise InputError("existing evaluation-mode Heads required")
            shape = {"kind": head.kind, "width": head.base.in_features,
                     "classes": head.base.out_features,
                     "rank": head.down.out_features if hasattr(head, "down") else 1}
            count = _shape_count(shape)
            if (shape["width"] != features.shape[1] or (architecture is not None and shape != architecture)
                    or tuple(head.buffers()) or sum(p.numel() for p in head.parameters()) != count
                    or any(type(layer) not in (Head, torch.nn.Linear, torch.nn.ModuleList)
                           or layer._forward_hooks or layer._forward_pre_hooks
                           or "forward" in layer.__dict__ for layer in head.modules())
                    or any(p.device.type != "cpu" or p.dtype != torch.float32
                           or not torch.isfinite(p).all() for p in head.parameters())):
                raise InputError("complete homogeneous finite Head architecture required")
            architecture = shape
            census += count * 4
            if census > maximum_parameter_bytes:
                raise InputError("candidate parameter budget before allocation")
            if (type(rows) is not torch.Tensor or rows.device.type != "cpu" or rows.dtype != torch.long
                    or rows.ndim != 1 or not 1 <= len(rows) <= 16384
                    or bool(((rows < 0) | (rows >= len(features))).any())
                    or type(y) is not torch.Tensor or y.device.type != "cpu" or y.dtype != torch.long
                    or y.shape != rows.shape or bool(((y < 0) | (y >= shape["classes"])).any())):
                raise InputError("complete training row/label mapping required")
            total_rows += len(rows)
            if total_rows > 1_048_576:
                raise InputError("training row census limit")
        original = [parameters(h) for h in initials]
        frozen = features.detach().clone()
        rows_private = tuple(r.clone() for r in row_indices)
        y_private = tuple(y.clone() for y in labels)
        trained = [None] * len(initials)
        hashes = [hashlib.sha256() for _ in initials]
        clips = [0] * len(initials)
        buckets, groups = defaultdict(list), []
        for i, steps in enumerate(step_counts):
            if steps == 0:
                trained[i] = deepcopy(initials[i]).eval()
            else:
                buckets[steps, min(batch, len(rows_private[i]))].append(i)
        for (steps, samples), ids in buckets.items():
            for offset in range(0, len(ids), group_size):
                selected = ids[offset:offset + group_size]
                with measured() as cost:
                    # stack_module_state returns new independent leaf tensors.
                    weights, buffers = stack_module_state([initials[i] for i in selected])
                    for value in weights.values():
                        value.requires_grad_(True)
                    template = deepcopy(initials[selected[0]]).to("meta").train()
                    def forward(params, x):
                        return functional_call(template, (params, buffers), (x,), strict=True)
                    vectorized = torch.vmap(forward, randomness="error")
                    optimizer = torch.optim.AdamW(weights.values(), lr=0.01, weight_decay=0.0)
                    rngs = [torch.Generator().manual_seed(seeds[i]) for i in selected]
                    clip_count = torch.zeros(len(selected), dtype=torch.long)
                    for _ in range(steps):
                        local = [torch.randint(len(rows_private[i]), (samples,), generator=rng)
                                 for i, rng in zip(selected, rngs)]
                        for i, sample in zip(selected, local):
                            hashes[i].update(sample.numpy().astype("<i8", copy=False).tobytes())
                        index = torch.stack([rows_private[i][s] for i, s in zip(selected, local)])
                        targets = torch.stack([y_private[i][s] for i, s in zip(selected, local)])
                        optimizer.zero_grad(set_to_none=True)
                        logits = vectorized(weights, frozen[index])
                        per_row = F.cross_entropy(logits.reshape(-1, architecture["classes"]),
                                                  targets.reshape(-1), reduction="none")
                        loss = per_row.reshape(len(selected), samples).mean(1).sum()
                        if not bool(torch.isfinite(loss)):
                            raise InputError("nonfinite grouped loss")
                        loss.backward()
                        component = torch.stack([torch.linalg.vector_norm(p.grad.flatten(1), 2, dim=1)
                                                 for p in weights.values()], 1)
                        norms = torch.linalg.vector_norm(component, 2, dim=1)
                        if not bool(torch.isfinite(norms).all()):
                            raise InputError("nonfinite per-Cell gradient")
                        scale = (1.0 / (norms + 1e-6)).clamp(max=1.0)
                        clip_count += (scale < 1).long()
                        for p in weights.values():
                            p.grad.mul_(scale.reshape((-1,) + (1,) * (p.ndim - 1)))
                        optimizer.step()
                    for position, i in enumerate(selected):
                        result = deepcopy(initials[i]).requires_grad_(True)
                        result.load_state_dict({k: v[position].detach() for k, v in weights.items()}, strict=True)
                        if not all(bool(torch.isfinite(p).all()) for p in result.parameters()):
                            raise InputError("nonfinite learned candidate")
                        trained[i] = result.eval()
                        clips[i] = int(clip_count[position])
                    state_bytes = sum(t.numel() * t.element_size() for state in optimizer.state.values()
                                      for t in state.values() if isinstance(t, torch.Tensor))
                groups.append({"cells": selected, "steps": steps, "samples_per_cell_step": samples,
                    "optimizer_calls": steps, "cell_updates": steps * len(selected),
                    "examples_processed": steps * samples * len(selected),
                    "optimizer_tensor_bytes_at_end": state_bytes, **cost})
        if original != [parameters(h) for h in initials]:
            raise InputError("source Heads changed during candidate learning")
        return tuple(trained), {"whole_call": whole, "groups": groups,
            "cells": [{"steps": n, "examples_processed": n * min(batch, len(rows_private[i])),
                       "minibatch_sha256": hashes[i].hexdigest(), "gradient_clipped_steps": clips[i],
                       **parameters(trained[i])} for i, n in enumerate(step_counts)],
            "candidate_parameter_bytes": census, "frozen_feature_copy_bytes": frozen.numel() * 4,
            "padded_example_lanes": 0, "encoder_calls": 0, "optimizer_state_retained": False,
            "production_accepted": False}
