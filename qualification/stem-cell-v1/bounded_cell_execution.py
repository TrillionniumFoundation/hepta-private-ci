"""Inference-only, invocation-local dense folding of existing Cell parameters.

No persistent compiled cache, model loader, trainer, owner or authorization.
The input owner must supply scoped references and exclude concurrent mutation.
The memory bound covers explicit floating tensors, NOT RSS/library workspace.
"""
from __future__ import annotations

import torch

from development_tensors import MAX_ELEMENTS
from shared_cell_execution import _validate_request

MAX_SCRATCH_BYTES = 16 * 1024 * 1024
DEFAULT_SCRATCH_BYTES = 1024 * 1024


def _finite(*values):
    if any(not torch.isfinite(v).all() for v in values):
        raise ValueError("nonfinite folded intermediate or gate score")


def tile_plan(bank, features, cell_indices, maximum_scratch_bytes):
    """Pure size admission, before projection/folding. At most 32 request lanes.

    Output + common readout remain live. The conservative per-lane term charges
    matrices, matrix gathers, features/gates, coefficient gathers and products.
    No autograd graph is allowed to retain past tiles and invalidate this bound.
    """
    if (type(maximum_scratch_bytes) is not int
            or not 1 <= maximum_scratch_bytes <= MAX_SCRATCH_BYTES):
        raise ValueError("invalid explicit scratch byte budget")
    n, u, d, r, k = len(cell_indices), len(features), bank.width, bank.rank, bank.classes
    size = features.element_size()
    fixed = (n + u) * k
    single = bool((cell_indices == cell_indices[0]).all())
    # A single referenced Cell needs one folded matrix for this CALL only.
    # Its matmul avoids materializing an identical matrix for every input lane.
    if single:
        fixed += 3*(d*k+d+4*r+16)
    per_lane = (0 if single else 3*d*k) + 8*d + 4*r + 12*k + 16
    lanes = min(32, n, (maximum_scratch_bytes // size - fixed) // per_lane)
    if lanes < 1:
        raise ValueError("scratch budget cannot hold output and one folded lane")
    if not bank.basis.is_contiguous():
        raise ValueError("noncontiguous basis requires an explicitly charged copy")
    return {"tile_lanes": lanes, "explicit_scratch_upper_bytes": (fixed + lanes*per_lane)*size,
            "maximum_scratch_bytes": maximum_scratch_bytes,
            "folded_matrices_upper_bytes": (1 if single else lanes)*(d*k+d+1)*size,
            "single_cell_call": single,
            "retained_compiled_bytes_after_call": 0}


def _fold(bank, cells):
    # flatten is a view for the admitted contiguous basis; never expand all Cells.
    coefficients = bank.coefficients[cells]
    weights = (coefficients @ bank.basis.flatten(1)).reshape(-1, bank.width, bank.classes)
    gate = bank.gates[cells]
    axes = gate[:, :-1] @ bank.gate_axes
    bias = gate[:, -1].clone()
    _finite(weights, axes, bias)
    return weights, axes, bias


def _dense_math(features, fids, cids, folded):
    x = features[fids]
    weights, axes, bias = folded
    if len(weights) == 1:
        scores = x @ axes[0] + bias[0]
        residual = x @ weights[0]
    else:
        scores = (x * axes[cids]).sum(1) + bias[cids]
        residual = torch.bmm(x[:, None, :], weights[cids]).squeeze(1)
    _finite(scores)  # sigmoid(inf) must not conceal overflowing arithmetic.
    _finite(residual)
    return torch.sigmoid(scores)[:, None] * residual


def _tiled_validated(bank, features, fids, cids, plan):
    # Function-local tiles die after each call; no list of matrix outputs/graphs.
    base = bank.base(features)
    _finite(base)
    output = torch.empty((len(cids), bank.classes), dtype=features.dtype)
    compiled, maximum_cells, tiles = 0, 0, 0
    single_folded = _fold(bank, cids[:1]) if plan["single_cell_call"] else None
    if single_folded is not None:
        compiled = maximum_cells = 1
    for start in range(0, len(cids), plan["tile_lanes"]):
        stop = start + plan["tile_lanes"]
        cells, inverse = torch.unique(cids[start:stop], sorted=True, return_inverse=True)
        folded = single_folded if single_folded is not None else _fold(bank, cells)
        output[start:stop] = base[fids[start:stop]] + _dense_math(features, fids[start:stop], inverse, folded)
        if single_folded is None:
            compiled += len(cells)
        maximum_cells = max(maximum_cells, len(cells))
        tiles += 1
        del folded  # Do not retain the previous tile during the next allocation.
    _finite(output)
    return output, {**plan, "compiled_cell_matrices": compiled,
                    "maximum_live_compiled_cells": maximum_cells, "tile_count": tiles}


def forward_tiled(bank, features, feature_indices, cell_indices, *,
                  maximum_scratch_bytes=DEFAULT_SCRATCH_BYTES):
    """Return logits + actual work counts; no partial output on a failed tile.

    A frozen serving call must disable autograd. Training retains forward_shared,
    whose parameter/input gradient parity is qualified separately.
    """
    if torch.is_grad_enabled():
        raise ValueError("tiled scratch contract requires disabled autograd")
    _validate_request(bank, features, feature_indices, cell_indices, MAX_ELEMENTS)
    plan = tile_plan(bank, features, cell_indices, maximum_scratch_bytes)
    return _tiled_validated(bank, features, feature_indices, cell_indices, plan)


def _expanded_math(bank, features, fids, cids):
    # Original BasisCellHeads equation, without its separate input preflight.
    x = features[fids]
    gates = bank.gates[cids]
    scores = (x @ bank.gate_axes.T * gates[:, :-1]).sum(1) + gates[:, -1]
    _finite(scores)
    residual = torch.einsum("bd,rdk,br->bk", x, bank.basis, bank.coefficients[cids])
    return bank.base(x) + torch.sigmoid(scores)[:, None]*residual


def _shared_math(bank, features, fids, cids):
    base = bank.base(features)
    axes = features @ bank.gate_axes.T
    projected = torch.einsum("ud,rdk->urk", features, bank.basis)
    _finite(base, axes, projected)
    gates = bank.gates[cids]
    scores = (axes[fids]*gates[:, :-1]).sum(1) + gates[:, -1]
    _finite(scores)
    residual = (projected[fids]*bank.coefficients[cids, :, None]).sum(1)
    return base[fids] + torch.sigmoid(scores)[:, None]*residual


def _checked_comparison(bank, features, fids, cids, method, folded, maximum_scratch_bytes):
    """Private probe entry: one identical request preflight for each method.

    The probe owns the fixed bank and full-folded tensors for this call series.
    This is NOT a callable production precompiled-artifact/cached-use interface.
    """
    if torch.is_grad_enabled():
        raise ValueError("comparison requires disabled autograd")
    if method not in ("expanded_checked", "shared_checked", "full_folded_checked", "tiled_folded"):
        raise ValueError("unknown fixed comparison method")
    _validate_request(bank, features, fids, cids, MAX_ELEMENTS)
    if method == "tiled_folded":
        plan = tile_plan(bank, features, cids, maximum_scratch_bytes)
        return _tiled_validated(bank, features, fids, cids, plan)
    if method == "expanded_checked":
        output = _expanded_math(bank, features, fids, cids)
    elif method == "shared_checked":
        output = _shared_math(bank, features, fids, cids)
    else:
        weights, axes, bias, lookup = folded
        selected = lookup[cids]
        if bool((selected == selected[0]).all()):
            cell = int(selected[0])
            compact = (weights[cell:cell+1], axes[cell:cell+1], bias[cell:cell+1])
            residual = _dense_math(features, fids, selected, compact)
        else:
            residual = _dense_math(features, fids, selected, (weights, axes, bias))
        output = bank.base(features[fids]) + residual
    _finite(output)
    return output, None
