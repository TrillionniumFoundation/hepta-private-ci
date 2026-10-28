"""Frozen official video/audio features, always computed from supplied media.

The PANN MobileNetV2 architecture follows Qiuqiang Kong's MIT-licensed release.
See semantic_LICENSES.md; checkpoint parameters and Fourier/mel kernels are loaded
strictly. No cached target feature may substitute for generated-media inference.
"""
import hashlib
from pathlib import Path
import time

import numpy as np
import torch
from torch import nn
from torch.nn import functional as F

PINS = {
    "s3d-d76dad2f.pth": "d76dad2f4b2a6701ad7f64e85b294b2d1989f1ea0d3f8b240446ed2152850bbb",
    "MobileNetV2_mAP_0.383.pth": "22437af9eb5ed1854b5ad285b4a17d5fc566f1a3b23df40db5541f5705ca340f",
}


class InvertedResidual(nn.Module):
    def __init__(self, inp, out, stride, expansion):
        super().__init__()
        hidden = round(inp * expansion)
        self.residual = stride == 1 and inp == out
        if expansion == 1:
            self.conv = nn.Sequential(
                nn.Conv2d(hidden, hidden, 3, 1, 1, groups=hidden, bias=False),
                nn.AvgPool2d(stride), nn.BatchNorm2d(hidden), nn.ReLU6(inplace=True),
                nn.Conv2d(hidden, out, 1, bias=False), nn.BatchNorm2d(out))
        else:
            self.conv = nn.Sequential(
                nn.Conv2d(inp, hidden, 1, bias=False), nn.BatchNorm2d(hidden),
                nn.ReLU6(inplace=True),
                nn.Conv2d(hidden, hidden, 3, 1, 1, groups=hidden, bias=False),
                nn.AvgPool2d(stride), nn.BatchNorm2d(hidden), nn.ReLU6(inplace=True),
                nn.Conv2d(hidden, out, 1, bias=False), nn.BatchNorm2d(out))

    def forward(self, x):
        value = self.conv(x)
        return x + value if self.residual else value


class PannMobileNet(nn.Module):
    def __init__(self):
        super().__init__()
        self.spectrogram_extractor = nn.Module()
        self.spectrogram_extractor.stft = nn.Module()
        for kind in ("real", "imag"):
            setattr(self.spectrogram_extractor.stft, "conv_" + kind,
                    nn.Conv1d(1, 513, 1024, stride=320, bias=False))
        self.logmel_extractor = nn.Module()
        self.logmel_extractor.register_buffer("melW", torch.zeros(513, 64))
        self.bn0 = nn.BatchNorm2d(64)
        layers = [nn.Sequential(nn.Conv2d(1, 32, 3, 1, 1, bias=False),
                  nn.AvgPool2d(2), nn.BatchNorm2d(32), nn.ReLU6(inplace=True))]
        channels = 32
        for expansion, out, count, stride in ((1,16,1,1),(6,24,2,2),(6,32,3,2),
                                            (6,64,4,2),(6,96,3,2),(6,160,3,1),(6,320,1,1)):
            for index in range(count):
                layers.append(InvertedResidual(channels, out, stride if index == 0 else 1, expansion))
                channels = out
        layers.append(nn.Sequential(nn.Conv2d(channels, 1280, 1, bias=False),
                                   nn.BatchNorm2d(1280), nn.ReLU6(inplace=True)))
        self.features = nn.Sequential(*layers)
        self.fc1 = nn.Linear(1280, 1024)
        self.fc_audioset = nn.Linear(1024, 527)

    def forward(self, waveform):
        x = F.pad(waveform[:, None], (512, 512), mode="reflect")
        stft = self.spectrogram_extractor.stft
        power = (stft.conv_real(x).square() + stft.conv_imag(x).square()).transpose(1, 2)
        mel = 10.0 * torch.log10((power @ self.logmel_extractor.melW).clamp_min(1e-10))
        x = self.bn0(mel[:, None].transpose(1, 3)).transpose(1, 3)
        x = self.features(x).mean(3)
        x = x.amax(2) + x.mean(2)
        embedding = F.relu(self.fc1(x))
        return torch.cat((embedding, torch.sigmoid(self.fc_audioset(embedding))), 1)


class SemanticBackbones:
    def __init__(self, root):
        from torchvision.models.video import s3d
        self.root = Path(root)
        for name, expected in PINS.items():
            actual = hashlib.sha256((self.root / name).read_bytes()).hexdigest()
            if actual != expected:
                raise ValueError(f"Pretrained weight identity changed: {name}")
        self.video = s3d(weights=None).eval()
        self.video.load_state_dict(torch.load(self.root / "s3d-d76dad2f.pth",
                                              map_location="cpu", weights_only=True), strict=True)
        self.audio = PannMobileNet().eval()
        self.audio.load_state_dict(torch.load(self.root / "MobileNetV2_mAP_0.383.pth",
                                              map_location="cpu", weights_only=True)["model"], strict=True)
        for model in (self.video, self.audio):
            model.requires_grad_(False)

    @torch.no_grad()
    def video_features(self, frames):
        """B,T,H,W,3 uint8; exact 16-frame protocol, official spatial normalization."""
        frames = np.asarray(frames)
        if frames.ndim != 5 or frames.shape[1] != 16 or frames.shape[-1] != 3:
            raise ValueError("Expected sixteen actual RGB frames")
        x = torch.as_tensor(frames.copy()).permute(0, 1, 4, 2, 3).float() / 255
        b, t, c, h, w = x.shape
        x = F.interpolate(x.reshape(b*t, c, h, w), size=(256,256), mode="bilinear", align_corners=False)
        x = x[:, :, 16:240, 16:240].reshape(b,t,c,224,224).permute(0,2,1,3,4)
        mean = torch.tensor((.43216,.394666,.37645))[None,:,None,None,None]
        scale = torch.tensor((.22803,.22145,.216989))[None,:,None,None,None]
        hidden = self.video.features((x-mean)/scale).mean((2,3,4))
        logits = self.video.classifier(hidden[:, :, None, None, None]).flatten(1)
        return torch.cat((hidden, logits.softmax(1)), 1).cpu().numpy()

    @torch.no_grad()
    def audio_features(self, waveform):
        """B,32000 float waveform at 16 kHz, resampled to official 32 kHz."""
        from scipy.signal import resample_poly
        waveform = np.asarray(waveform, np.float32)
        if waveform.ndim != 2 or waveform.shape[1] != 32000:
            raise ValueError("Expected two seconds of actual 16 kHz PCM")
        x = torch.from_numpy(resample_poly(waveform, 2, 1, axis=1).copy())
        return self.audio(x).cpu().numpy()

    def features(self, frames, waveform):
        start = time.process_time()
        video = self.video_features(frames)
        audio = self.audio_features(waveform)
        return video, audio, {"cpu_seconds":time.process_time()-start,
                              "video_features":video.shape[1], "audio_features":audio.shape[1]}
