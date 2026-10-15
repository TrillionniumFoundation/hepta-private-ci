"""Research-only differentiable *per-operation* evidence coverage.

An attention union can be perfectly satisfied by one of several required facts.
The objective charges a separate -log probability-mass term per valid public
operation, sharing no per-step terminal labels at inference.
"""
from __future__ import annotations


def per_operation_mass_loss(attention, operation_masks):
    """One equal-weight log mass for EACH required evidence operation.

    Args: attention [batch,tokens]; operation_masks [batch,operations,tokens]
    with bounded detached binary masks validated by fit_model at admission.
    Empty padded operation slots contribute zero weight and zero gradient.
    """
    if (attention.ndim != 2 or operation_masks.ndim != 3
            or operation_masks.shape[0] != attention.shape[0]
            or operation_masks.shape[2] != attention.shape[1]):
        raise ValueError("operation attention geometry differs")
    active = operation_masks.sum(dim=-1).gt(0).to(attention.dtype)
    evidence_mass = (attention.unsqueeze(1) * operation_masks).sum(dim=-1)
    return (-(evidence_mass.clamp_min(1e-8).log()) * active).sum() / active.sum().clamp_min(1)
