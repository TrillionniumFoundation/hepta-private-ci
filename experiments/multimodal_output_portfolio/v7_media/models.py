"""Learned acoustic and temporal pixel decoders for a bounded digit domain."""

import hashlib

import torch
from torch import nn
from torch.nn import functional as F


def validate_probabilities(probabilities, paired=False):
    dimensions = 3 if paired else 2
    expected = (2, 10) if paired else (10,)
    if probabilities.ndim != dimensions or tuple(probabilities.shape[1:]) != expected:
        raise ValueError("Semantic condition shape mismatch")
    if (not torch.isfinite(probabilities).all() or (probabilities < 0).any()
            or not torch.allclose(probabilities.sum(-1),
                                  torch.ones_like(probabilities.sum(-1)), atol=1e-5)):
        raise ValueError("Semantic condition must be a finite probability simplex")


def weights_sha256(model):
    digest = hashlib.sha256()
    for name, tensor in sorted(model.state_dict().items()):
        array = tensor.detach().cpu().contiguous()
        digest.update(name.encode())
        digest.update(str(array.dtype).encode())
        digest.update(str(tuple(array.shape)).encode())
        digest.update(array.numpy().tobytes())
    return digest.hexdigest()


class SpeechObserver(nn.Module):
    """Recording-disjoint speech audit model; not a perceptual certification."""

    def __init__(self):
        super().__init__()
        self.features = nn.Sequential(
            nn.Conv2d(1, 12, 5, stride=2, padding=2), nn.ReLU(),
            nn.Conv2d(12, 24, 5, stride=2, padding=2), nn.ReLU(),
            nn.Conv2d(24, 32, 3, stride=2, padding=1), nn.ReLU(),
            nn.AdaptiveAvgPool2d((4, 4)), nn.Flatten(),
            nn.Linear(512, 96), nn.ReLU(), nn.Linear(96, 10),
        )

    def forward(self, spectra):
        return self.features(spectra)


class AcousticDecoder(nn.Module):
    """Conditional spectral VAE; inference synthesizes, without retrieving WAVs."""

    def __init__(self, latent=16):
        super().__init__()
        self.latent = latent
        self.encoder = nn.Sequential(
            nn.Conv2d(1, 8, 5, stride=2, padding=2), nn.SiLU(),
            nn.Conv2d(8, 16, 5, stride=2, padding=2), nn.SiLU(),
            nn.Conv2d(16, 32, 3, stride=2, padding=1), nn.SiLU(),
            nn.AdaptiveAvgPool2d((4, 4)), nn.Flatten(),
        )
        self.posterior = nn.Linear(522, 2 * latent)
        self.initial = nn.Linear(10 + latent, 64 * 9 * 7)
        self.synthesis = nn.Sequential(
            nn.ConvTranspose2d(64, 32, 4, stride=2, padding=1), nn.SiLU(),
            nn.ConvTranspose2d(32, 16, 4, stride=2, padding=1), nn.SiLU(),
            nn.ConvTranspose2d(16, 8, 4, stride=2, padding=1), nn.SiLU(),
            nn.ConvTranspose2d(8, 1, 4, stride=2, padding=1),
        )

    def decode(self, probabilities, style=None):
        validate_probabilities(probabilities)
        if style is None:
            style = probabilities.new_zeros((len(probabilities), self.latent))
        if style.shape != (len(probabilities), self.latent) or not torch.isfinite(style).all():
            raise ValueError("Acoustic style state mismatch")
        hidden = self.initial(torch.cat((probabilities, style), dim=-1)).reshape(-1, 64, 9, 7)
        return self.synthesis(hidden)[:, :, :129, :101]

    def forward(self, spectra, probabilities, noise):
        validate_probabilities(probabilities)
        posterior = self.posterior(torch.cat((self.encoder(spectra), probabilities), dim=-1))
        mean, log_variance = posterior.chunk(2, dim=-1)
        log_variance = log_variance.clamp(-8, 5)
        style = mean + (.5 * log_variance).exp() * noise
        decoded = self.decode(probabilities, style)
        kl = -.5 * (1 + log_variance - mean.square() - log_variance.exp()).mean()
        return decoded, kl


class TemporalPixelDecoder(nn.Module):
    """A recurrent neural frame generator conditioned on two semantic slots."""

    def __init__(self, frames=20):
        super().__init__()
        if frames != 20:
            raise ValueError("This version declares a fixed two-second, 10 fps clock")
        self.frames = frames
        self.initial = nn.Linear(20, 64)
        self.temporal = nn.GRU(24, 64, batch_first=True)
        self.pixels = nn.Sequential(nn.Linear(64, 128), nn.SiLU(), nn.Linear(128, 784))

    def forward(self, probabilities):
        validate_probabilities(probabilities, paired=True)
        batch = len(probabilities)
        semantic = probabilities.reshape(batch, 20)
        time = torch.arange(self.frames, device=semantic.device, dtype=semantic.dtype) / 10
        clock = torch.stack((time / 2, torch.sin(torch.pi * time),
                             torch.cos(torch.pi * time), (time >= 1).to(time.dtype)), dim=-1)
        inputs = torch.cat((semantic[:, None].expand(-1, self.frames, -1),
                            clock[None].expand(batch, -1, -1)), dim=-1)
        initial = self.initial(semantic).tanh()[None]
        states, _ = self.temporal(inputs, initial)
        return self.pixels(states).reshape(batch, self.frames, 1, 28, 28)


def video_targets(left, right):
    """Training-only constructed videos from real source pixels, with motion."""
    if left.shape != right.shape or tuple(left.shape[1:]) != (1, 28, 28):
        raise ValueError("Expected paired real MNIST source pixels")
    frames = []
    for frame in range(20):
        image = left if frame < 10 else right
        shift = (-2, -1, 0, 1, 2, 2, 1, 0, -1, -2)[frame % 10]
        padded = F.pad(image, (2, 2, 0, 0))
        frames.append(padded[:, :, :, 2 - shift:30 - shift])
    return torch.stack(frames, dim=1)
