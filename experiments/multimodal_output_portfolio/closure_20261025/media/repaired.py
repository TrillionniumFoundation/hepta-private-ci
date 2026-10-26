"""Declared development repairs: acoustic invariance and explicit event clocks."""

import torch
from torch import nn

from ...v7_media.models import validate_probabilities


class RobustSpeech(nn.Module):
    def __init__(self):
        super().__init__()
        self.features = nn.Sequential(
            nn.Conv2d(1, 16, 5, stride=2, padding=2), nn.GroupNorm(4, 16), nn.SiLU(),
            nn.Conv2d(16, 32, 5, stride=2, padding=2), nn.GroupNorm(8, 32), nn.SiLU(),
            nn.Conv2d(32, 48, 3, stride=2, padding=1), nn.GroupNorm(8, 48), nn.SiLU(),
            nn.AdaptiveAvgPool2d((4, 4)), nn.Flatten(), nn.Dropout(.15),
            nn.Linear(768, 128), nn.SiLU(), nn.Linear(128, 10))

    def forward(self, spectra):
        if spectra.ndim != 4 or spectra.shape[1:] != (1, 129, 101) or not torch.isfinite(spectra).all():
            raise ValueError("Malformed observed acoustic spectrum")
        normalized = (spectra - spectra.mean((2, 3), keepdim=True)) / spectra.std((2, 3), keepdim=True).clamp_min(.1)
        return self.features(normalized)


class EventVideoDecoder(nn.Module):
    """Generate each event with its own recurrent state; no copied output frames.

    The public clock declares two one-second events. Their digit content comes
    from the predicted shared semantic code, never from evaluation labels.
    """

    def __init__(self):
        super().__init__()
        self.initial = nn.Linear(10, 64)
        self.temporal = nn.GRU(13, 64, batch_first=True)
        self.pixels = nn.Sequential(nn.Linear(64, 128), nn.SiLU(), nn.Linear(128, 784))

    def forward(self, probabilities):
        validate_probabilities(probabilities, paired=True)
        semantic = probabilities.reshape(-1, 10)
        t = torch.arange(10, dtype=semantic.dtype) / 9
        clock = torch.stack((t, (2 * torch.pi * t).sin(), (2 * torch.pi * t).cos()), -1)
        inputs = torch.cat((semantic[:, None].expand(-1, 10, -1), clock[None].expand(len(semantic), -1, -1)), -1)
        states, _ = self.temporal(inputs, self.initial(semantic).tanh()[None])
        return self.pixels(states).reshape(len(probabilities), 20, 1, 28, 28)
