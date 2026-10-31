"""Neural image-conditioned motion decoder for the constructed digit domain.

The required event clock chooses the source panel; a learned recurrent model
produces every frame's spatial transform. This is a bounded image-to-video
model, not a natural-video foundation model or a static repeated-frame codec.
"""

import torch
from torch import nn
from torch.nn import functional as F

from .models import validate_probabilities


ARCHITECTURE = "learned-recurrent-image-conditioned-motion-v1"


class ConditionedMotionDecoder(nn.Module):
    def __init__(self):
        super().__init__()
        self.initial = nn.Linear(20, 32)
        self.temporal = nn.GRU(24, 32, batch_first=True)
        self.motion = nn.Linear(32, 2)

    def motion_pixels(self, probabilities):
        validate_probabilities(probabilities, paired=True)
        semantic = probabilities.reshape(-1, 20)
        index = torch.arange(20, dtype=semantic.dtype, device=semantic.device)
        phase = 2 * torch.pi * index / 10
        clock = torch.stack((index / 19, phase.sin(), phase.cos(), (index >= 10).to(index.dtype)), -1)
        inputs = torch.cat((semantic[:, None].expand(-1, 20, -1),
                            clock[None].expand(len(semantic), -1, -1)), -1)
        sequence, _ = self.temporal(inputs, self.initial(semantic).tanh()[None])
        return self.motion(sequence).tanh()

    def forward(self, probabilities, images):
        validate_probabilities(probabilities, paired=True)
        if (images.shape != (len(probabilities), 1, 28, 56)
                or not torch.isfinite(images).all() or images.min() < 0 or images.max() > 1):
            raise ValueError("Image-conditioned video requires actual bounded decoded image pixels")
        displacement = self.motion_pixels(probabilities)
        panels = torch.stack((images[:, :, :, :28], images[:, :, :, 28:]), 1)
        # The public output requirement contains two one-second events. No
        # expected digit or evaluation target participates in this clock.
        source = panels.repeat_interleave(10, dim=1).reshape(-1, 1, 28, 28)
        affine = torch.zeros((len(source), 2, 3), dtype=source.dtype, device=source.device)
        affine[:, 0, 0] = 1
        affine[:, 1, 1] = 1
        affine[:, :, 2] = displacement.reshape(-1, 2) * (2 / 28)
        grid = F.affine_grid(affine, source.shape, align_corners=False)
        pixels = F.grid_sample(source, grid, mode="bilinear", padding_mode="zeros", align_corners=False)
        return torch.logit(pixels.clamp(1e-6, 1 - 1e-6)).reshape(-1, 20, 1, 28, 28)
