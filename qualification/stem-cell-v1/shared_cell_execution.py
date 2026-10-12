"""Invocation-local factorization of the existing BasisCellHeads equation.

Pure candidate tensor math: no loader, persistent cache, owner or authorization.
The caller supplies same-scope frozen features and their explicit row references.
We never infer permission or input identity from equal floating-point vectors.
"""
from __future__ import annotations

import torch

from development_tensors import BasisCellHeads, MAX_ELEMENTS, checked_tensor


def forward_shared(bank, features, feature_indices, cell_indices, *,
                   maximum_scratch_elements=MAX_ELEMENTS):
    """Project each referenced input through the common basis only once.

    Cell coefficients/gates remain independent. This preserves autograd, including
    accumulation of gradients for reused rows. The scratch check conservatively
    bounds explicit forward floating-point intermediates, NOT allocator/RSS,
    matrix-library workspace, inputs, model storage or backward saved tensors.
    No intermediate survives this call; parameter changes cannot hit a stale cache.
    """
    if not isinstance(bank, BasisCellHeads):
        raise ValueError("existing BasisCellHeads required")
    checked_tensor(features, 2, "shared features")
    if (features.shape[1] != bank.width or features.dtype != bank.base.weight.dtype
            or not 1 <= len(features) <= 4096
            or type(maximum_scratch_elements) is not int
            or not 1 <= maximum_scratch_elements <= MAX_ELEMENTS):
        raise ValueError("invalid shared features or scratch limit")
    for ids, limit in ((feature_indices, len(features)), (cell_indices, len(bank.cell_ids))):
        if (not isinstance(ids, torch.Tensor) or ids.dtype != torch.long
                or ids.device.type != "cpu" or ids.ndim != 1 or not 1 <= len(ids) <= 4096
                or bool(((ids < 0) | (ids >= limit)).any())):
            raise ValueError("invalid bounded feature/Cell indices")
    if feature_indices.shape != cell_indices.shape:
        raise ValueError("unpaired feature and Cell rows")
    if torch.unique(feature_indices).numel() != len(features):
        raise ValueError("unreferenced feature rows are not shared work")
    active = torch.unique(cell_indices).tolist()
    if any(not bank.awake[i] for i in active):
        raise ValueError("dormant Cell cannot execute")
    u, n, r, k = len(features), len(cell_indices), bank.rank, bank.classes
    # All gathers, multiply outputs and retained projection results, not merely
    # the packed output. Fail before either projection is dispatched.
    scratch = u * (r*k + r + k) + n * (2*r*k + 4*r + 4*k + 4)
    if scratch > maximum_scratch_elements:
        raise ValueError("shared forward scratch budget exceeded")
    base = bank.base(features)
    gate_features = features @ bank.gate_axes.T
    basis_features = torch.einsum("ud,rdk->urk", features, bank.basis)
    if any(not torch.isfinite(v).all() for v in (base, gate_features, basis_features)):
        raise ValueError("nonfinite shared projection")
    gates = bank.gates[cell_indices]
    gate_scores = (gate_features[feature_indices] * gates[:, :-1]).sum(1) + gates[:, -1]
    if not torch.isfinite(gate_scores).all():
        raise ValueError("nonfinite Cell gate score")
    activation = torch.sigmoid(gate_scores)
    residual = (basis_features[feature_indices] * bank.coefficients[cell_indices, :, None]).sum(1)
    output = base[feature_indices] + activation[:, None] * residual
    if not torch.isfinite(output).all():
        raise ValueError("nonfinite shared Cell output")
    return output
