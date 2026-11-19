"""P1 research-only scale witness to repair a demonstrated rank-one blind spot.

Adding absolute log K restores a second observable coordinate; this is a local
Jacobian result, NOT evidence of neural-memory quality or causal utility gain.
"""
from __future__ import annotations

import torch

try:
    from .dual_channel_structural_gate import channels
except ImportError:
    from dual_channel_structural_gate import channels


def scale_aware_features(v: torch.Tensor, k: torch.Tensor):
    """Four features: Call/K, Put/K, log(V/b), log(K).

    Requires same f64 positive finite bounded inputs as the one-shot kernel.
    The last coordinate is an explicit absolute scale witness. Returning an
    amplitude channel is a proposed design repair, not a production operator.
    """
    q = channels(v, k)
    return torch.stack((q.call_normalized, q.put_normalized,
                        q.margin, torch.log(k)))
