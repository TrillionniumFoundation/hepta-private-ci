"""The original frozen DigitObserver architecture and AudioMNIST input contract."""

import wave

import numpy as np
from scipy.signal import resample_poly
import torch
from torch import nn
from torch.nn import functional as functional


class DigitObserver(nn.Module):
    """Architecture-preserving copy; the original checkpoint is never updated."""

    def __init__(self):
        super().__init__()
        self.net = nn.Sequential(nn.Conv2d(1, 12, 5, stride=2, padding=2), nn.ReLU(),
            nn.Conv2d(12, 24, 3, stride=2, padding=1), nn.ReLU(), nn.AdaptiveAvgPool2d((4, 4)),
            nn.Flatten(), nn.Linear(384, 64), nn.ReLU(), nn.Linear(64, 10))

    def forward(self, features):
        return self.net(features)


def features(path):
    with wave.open(str(path), 'rb') as stream:
        if (stream.getnchannels(), stream.getsampwidth(), stream.getframerate()) != (1, 2, 48000):
            raise ValueError('Pinned source interface requires mono PCM16 at48kHz')
        samples = np.frombuffer(stream.readframes(stream.getnframes()), dtype='<i2').copy()
    signal = resample_poly(samples.astype(np.float64)/32768., 1, 6)
    tensor = torch.from_numpy(signal).float()
    if len(tensor) < 256:
        tensor = functional.pad(tensor, (0, 256-len(tensor)))
    spectrum = torch.stft(tensor, n_fft=256, hop_length=64, window=torch.hann_window(256),
                          center=False, return_complex=True).abs().log1p()
    resized = functional.interpolate(spectrum[None, None], size=(64, 64),
                                      mode='bilinear', align_corners=False)[0]
    return (resized-resized.mean())/resized.std().clamp_min(1e-6)
