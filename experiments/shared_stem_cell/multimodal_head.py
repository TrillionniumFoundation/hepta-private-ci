"""Research-only state-gated residual Cell head over a frozen shared vector.

This is an *output* adapter, never an internal transformer LoRA. Training,
selection, calibration, authority, durable optimizer recovery, and real model
quality are not provided by this module.
"""

import torch
from torch import nn
from torch.nn import functional as F


class StateGatedCellHead(nn.Module):
    def __init__(self, feature_dim: int, state_dim: int, rank: int, classes: int):
        super().__init__()
        for name, value, maximum in (("feature_dim", feature_dim, 512),
                                     ("state_dim", state_dim, 256),
                                     ("rank", rank, 64), ("classes", classes, 256)):
            if type(value) is not int or not 1 <= value <= maximum:
                raise ValueError(f"invalid bounded {name}")
        if classes < 2:
            raise ValueError("classification requires at least two options")
        self.feature_dim, self.state_dim = feature_dim, state_dim
        self.down = nn.Linear(feature_dim, rank, bias=False)
        self.gate = nn.Linear(state_dim, rank)
        self.up = nn.Linear(rank, feature_dim, bias=False)
        self.output = nn.Linear(feature_dim, classes)
        nn.init.zeros_(self.up.weight)

    def forward(self, shared: torch.Tensor, local_state: torch.Tensor):
        if (shared.ndim != 2 or shared.shape[1] != self.feature_dim
                or local_state.shape != (len(shared), self.state_dim)
                or not torch.isfinite(shared).all() or not torch.isfinite(local_state).all()):
            raise ValueError("mismatched or nonfinite Cell input/state")
        # No backward graph crosses into the shared encoder or other Cell states.
        common = shared.detach()
        state = local_state.detach()
        delta = self.up(F.silu(self.down(common)) * torch.sigmoid(self.gate(state)))
        return self.output(common + delta)

    def parameter_count(self) -> int:
        return sum(p.numel() for p in self.parameters())
