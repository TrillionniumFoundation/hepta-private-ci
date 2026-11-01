"""Explicit, shared typed-event eligibility for addressed content writes.

This adds a semantics prior after the first revision's confirmation exposed
accumulated irrelevant writes. The complete raw observation still reaches the
encoder, physical policy, boundary remap and address computation unchanged.
Only the eligibility of a content or relation write is restricted. No label,
answer, dependency index or inferred memory key is consulted.
"""

import torch
from torch import nn


class TypedEligibility(nn.Module):
    def __init__(self, original):
        super().__init__()
        self.original = original

    def forward(self, kinds):
        if kinds.shape[-1] != 4 or not bool(((kinds == 0) | (kinds == 1)).all()) or bool((kinds.sum(-1) > 1).any()):
            raise ValueError("Expected four one-hot event kinds, or an empty placeholder")
        learned = self.original(kinds)
        content = torch.where(kinds[..., 0] == 1, learned[..., 0], -torch.inf)
        relation = torch.where(kinds[..., 3] == 1, learned[..., 1], -torch.inf)
        return torch.stack((content, relation), -1)


def install(model):
    """Preserve every learned tensor; replace only the role-gate computation."""
    if isinstance(model.roles, TypedEligibility):
        raise ValueError("Typed eligibility already installed")
    model.roles = TypedEligibility(model.roles)
    return model
