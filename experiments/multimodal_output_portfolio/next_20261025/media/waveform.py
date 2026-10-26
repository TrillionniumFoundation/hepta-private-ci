"""A trainable, explicitly teacher-distilled finite-digit waveform decoder.

The decoder's inference API receives predicted semantic probabilities. It does
not open target recordings, text templates, a TTS process, or observer scores.
This bounded ten-condition model is not a general speech foundation model.
"""

import torch
from torch import nn


class WaveformStudent(nn.Module):
    """Map a public digit simplex to a two-second physical audio event."""

    def __init__(self):
        super().__init__()
        self.network = nn.Sequential(nn.Linear(10, 64), nn.Tanh(),
                                     nn.Linear(64, 16000), nn.Tanh())

    def forward(self, probabilities):
        if probabilities.ndim != 2 or probabilities.shape[1] != 10:
            raise ValueError("Waveform decoder requires ten semantic probabilities")
        if (not torch.isfinite(probabilities).all() or probabilities.min() < 0
                or not torch.allclose(probabilities.sum(-1), probabilities.new_ones(len(probabilities)), atol=1e-5)):
            raise ValueError("Invalid predicted semantic simplex")
        return self.network(probabilities)


def waveform_distance(predicted, target):
    """Training reward only; independent ASRs are absent from this computation."""
    return (predicted - target).square().mean(-1)


def entropic_joint_risk(per_example_losses, risk_aversion=2.0):
    """A differentiable exponential-risk loss for actual multimodal training."""
    if per_example_losses.ndim != 1 or len(per_example_losses) == 0:
        raise ValueError("Expected one joint loss per independently sampled task")
    return (torch.logsumexp(risk_aversion * per_example_losses, 0)
            - per_example_losses.new_tensor(len(per_example_losses)).log()) / risk_aversion
