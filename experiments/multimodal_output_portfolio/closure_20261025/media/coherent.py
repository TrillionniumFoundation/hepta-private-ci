"""Time-normalized acoustic learning and learned image-conditioned video motion."""

import torch
from torch import nn
from torch.nn import functional as F

from ...v7_media.models import validate_probabilities


class MelSpeech(nn.Module):
    """Learn from observed sound after a fixed label-free auditory transform."""

    def __init__(self):
        super().__init__()
        frequency = torch.linspace(0, 4000, 129)
        endpoints = 700 * (10 ** (torch.linspace(0, 2595 * torch.log10(torch.tensor(1 + 4000 / 700)), 42) / 2595) - 1)
        lower, center, upper = endpoints[:-2, None], endpoints[1:-1, None], endpoints[2:, None]
        bank = torch.minimum((frequency - lower) / (center - lower), (upper - frequency) / (upper - center)).clamp_min(0)
        self.register_buffer("mel_bank", bank / bank.sum(-1, keepdim=True).clamp_min(1e-8))
        self.features = nn.Sequential(
            nn.Conv2d(1, 16, 3, padding=1), nn.GroupNorm(4, 16), nn.SiLU(), nn.MaxPool2d(2),
            nn.Conv2d(16, 32, 3, padding=1), nn.GroupNorm(8, 32), nn.SiLU(), nn.MaxPool2d(2),
            nn.Conv2d(32, 64, 3, padding=1), nn.GroupNorm(8, 64), nn.SiLU(), nn.MaxPool2d(2),
            nn.AdaptiveAvgPool2d((4, 4)), nn.Flatten(), nn.Dropout(.1),
            nn.Linear(1024, 64), nn.SiLU(), nn.Linear(64, 10))

    def front_end(self, spectra):
        if spectra.ndim != 4 or spectra.shape[1:] != (1, 129, 101) or not torch.isfinite(spectra).all():
            raise ValueError("Malformed actual acoustic input")
        power = (10 * spectra[:, 0]).clamp(-24, 8).exp()
        transformed = torch.matmul(self.mel_bank, power).clamp_min(1e-10).log()
        normalized = []
        for x, energy in zip(transformed, power.mean(1)):
            voiced = torch.where(energy > energy.max() * .01)[0]
            start, end = int(voiced[0]), int(voiced[-1]) + 1
            aligned = F.interpolate(x[None, None, :, start:end], size=(40, 64), mode="bilinear", align_corners=False)[0]
            normalized.append((aligned - aligned.mean()) / aligned.std().clamp_min(.1))
        return torch.stack(normalized)

    def forward(self, spectra):
        return self.features(self.front_end(spectra))


def spatial_video(images, displacement):
    """Differentiable spatial fields applied to each emitted neural image panel."""
    if images.shape != (len(displacement), 1, 28, 56) or displacement.shape[1:] != (20, 2):
        raise ValueError("Image and learned motion clocks differ")
    panels = torch.stack((images[:, :, :, :28], images[:, :, :, 28:]), 1)
    source = panels.repeat_interleave(10, 1).reshape(-1, 1, 28, 28)
    affine = images.new_zeros((len(source), 2, 3))
    affine[:, 0, 0] = affine[:, 1, 1] = 1
    affine[:, :, 2] = displacement.reshape(-1, 2) * (2 / 28)
    grid = F.affine_grid(affine, source.shape, align_corners=False)
    pixels = F.grid_sample(source, grid, mode="bilinear", padding_mode="zeros", align_corners=False)
    return pixels.reshape(-1, 20, 1, 28, 28)


def motion_targets(images):
    """Training-only construction with ten distinct positions in each event."""
    displacement = images.new_zeros((len(images), 20, 2))
    displacement[:, :, 0] = torch.linspace(-2, 2, 10).repeat(2)
    return spatial_video(images, displacement)


class CoherentVideo(nn.Module):
    """A trained recurrent displacement decoder coupled to emitted image pixels.

    This small image-to-video model learns spatial motion, not natural video.
    Its image content is generated upstream by the frozen shared neural model.
    No source image or expected class is retrieved during output generation.
    """

    def __init__(self):
        super().__init__()
        self.initial = nn.Linear(10, 32)
        self.temporal = nn.GRU(13, 32, batch_first=True)
        self.motion = nn.Linear(32, 2)

    def displacements(self, probabilities):
        validate_probabilities(probabilities, paired=True)
        semantic = probabilities.reshape(-1, 10)
        t = torch.arange(10, dtype=semantic.dtype, device=semantic.device) / 9
        clock = torch.stack((t, (2 * torch.pi * t).sin(), (2 * torch.pi * t).cos()), -1)
        inputs = torch.cat((semantic[:, None].expand(-1, 10, -1), clock[None].expand(len(semantic), -1, -1)), -1)
        states, _ = self.temporal(inputs, self.initial(semantic).tanh()[None])
        return (2.5 * self.motion(states).tanh()).reshape(-1, 20, 2)

    def forward(self, probabilities, images):
        if not torch.isfinite(images).all() or images.min() < 0 or images.max() > 1:
            raise ValueError("Video requires finite actual generated image pixels")
        return torch.logit(spatial_video(images, self.displacements(probabilities)).clamp(1e-6, 1 - 1e-6))
