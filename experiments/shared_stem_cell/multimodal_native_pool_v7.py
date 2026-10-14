"""Model-native pooling with explicit semantics for frozen research Encoders.

This is a numerical transformation, not evidence of genuine pretrained weights
or original-publisher signature. Use only after LocalEncoder's pinned loader.
"""
from __future__ import annotations

import torch

POOLINGS = frozenset({"attention-mask-mean", "cls-first-token"})


def pool_hidden_state(hidden: torch.Tensor, attention: torch.Tensor,
                      pooling: str) -> torch.Tensor:
    """Apply a named, versioned pooling rule; never silently switch algorithms.

    Returns [batch,width]. The caller is responsible for a separate unit-L2
    normalization if required by the frozen candidate profile.
    """
    if pooling not in POOLINGS or type(pooling) is not str:
        raise ValueError("unrecognized frozen pooling")
    if (not isinstance(hidden, torch.Tensor) or hidden.ndim != 3
            or not hidden.is_floating_point() or not bool(torch.isfinite(hidden).all())
            or min(hidden.shape) < 1):
        raise ValueError("invalid encoder last hidden states")
    if (not isinstance(attention, torch.Tensor) or attention.ndim != 2
            or tuple(attention.shape) != tuple(hidden.shape[:2])
            or attention.dtype not in (torch.int8, torch.int16, torch.int32, torch.int64, torch.bool)
            or not bool(((attention == 0) | (attention == 1)).all())
            or not bool((attention[:, 0] == 1).all())):
        raise ValueError("noncanonical encoder attention mask / missing CLS")
    if pooling == "cls-first-token":
        return hidden[:, 0, :].contiguous()
    mask = attention.unsqueeze(-1).to(dtype=hidden.dtype)
    count = mask.sum(dim=1)
    if not bool((count > 0).all()):
        raise ValueError("empty attention support")
    return ((hidden * mask).sum(dim=1) / count).contiguous()
