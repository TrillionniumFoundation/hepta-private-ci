"""TRAIN-only terminal-label eligibility for evidence-step Group curricula.

The public operation masks identify the last required evidence slot, not the
answer. They must not be used by the runtime proposer, verifier or NDU critic.
This does not establish semantic evidence execution or causal sufficiency.
"""
from __future__ import annotations

import torch
from torch.nn import functional as F


def terminal_label_eligibility(operation_masks: torch.Tensor) -> torch.Tensor:
    """Return [cases, depths] indicating completion of all TRAIN operations.

    Multiple required operations coalesced into one slot are handled without
    truncation. Empty padded operation/step slots do not grant early access to
    final labels.  The caller must bind the teacher to its frozen source tokens.
    """
    if (not isinstance(operation_masks, torch.Tensor)
            or operation_masks.ndim != 4 or not 1 <= operation_masks.shape[0] <= 4096
            or not 1 <= operation_masks.shape[1] <= 64
            or not 1 <= operation_masks.shape[2] <= 64
            or not 1 <= operation_masks.shape[3] <= 1024
            or operation_masks.dtype != torch.float32
            or operation_masks.device.type != "cpu" or operation_masks.requires_grad
            or not torch.isfinite(operation_masks).all()
            or not ((operation_masks == 0) | (operation_masks == 1)).all()):
        raise ValueError("bounded detached binary TRAIN operation masks required")
    required = operation_masks.sum(dim=-1).gt(0).any(dim=2)
    if not required.any(dim=1).all():
        raise ValueError("each TRAIN example requires evidence before terminal supervision")
    completed = required.to(torch.int64).cumsum(dim=1).eq(required.sum(dim=1, keepdim=True))
    return completed.detach()


def guarded_terminal_cross_entropy(logits: torch.Tensor, targets: torch.Tensor,
                                   complete: torch.Tensor):
    """Mask unreached final targets before averaging; retain zero gradients.

    Per-example CE is multiplied by a train-only *detached* Boolean indicator.
    A batch with no complete chain returns an exactly zero differentiable loss.
    The optimizer can still learn from intermediate attention supervision.
    """
    if (not isinstance(logits, torch.Tensor) or logits.ndim != 2
            or not 1 <= logits.shape[0] <= 4096
            or not 2 <= logits.shape[1] <= 256
            or logits.device.type != "cpu" or not torch.isfinite(logits).all()
            or not isinstance(targets, torch.Tensor)
            or targets.shape != (logits.shape[0],) or targets.dtype != torch.long
            or targets.device.type != "cpu" or targets.requires_grad
            or not isinstance(complete, torch.Tensor)
            or complete.shape != targets.shape or complete.dtype != torch.bool
            or complete.device.type != "cpu" or complete.requires_grad):
        raise ValueError("bounded logits, detached class labels and eligibility required")
    if not targets.ge(0).all() or not targets.lt(logits.shape[1]).all():
        raise ValueError("TRAIN class labels outside registered classifier width")
    # Use log-softmax + gather instead of unreduced cross_entropy: the
    # frozen strict ATen arithmetic profile only admits mean-reduced NLL.
    # This still computes each row before removing inadmissible label loss.
    log_probability = F.log_softmax(logits, dim=-1)
    true_log_probability = log_probability.gather(1, targets.unsqueeze(1)).squeeze(1)
    paid = complete.to(dtype=logits.dtype)
    loss = -(true_log_probability * paid).sum() / paid.sum().clamp_min(1)
    return loss, int(complete.sum().item())
