"""Pinned real speech sources and disjoint recording roles for media heads."""

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import wave

import numpy as np
import torch
from torch.nn import functional as F


FSDD_COMMIT = "26eb9aaf76e81b692f806f9140c2d2777410d7a1"
FSDD_ARCHIVE_SHA256 = "9a68686ad29274bd0affde81b244953e677c9d7048dfb8acaf1168d7758bafab"
FSDD_MANIFEST_SHA256 = "f33fdd4af043704d396e0ad2f1f0d0ef349b60f45d0e502f7aec9b23ae84225c"
SAMPLE_RATE = 8000
WORD_SAMPLES = 8000
FFT_SIZE = 256
HOP_SIZE = 80
SPEC_SCALE = 5.0
ROLE_INDICES = {
    "generator": range(20, 50),
    "reward": range(10, 15),
    "audit": range(15, 20),
    "validation": range(5, 10),
    "test": range(0, 5),
}


@dataclass(frozen=True)
class SpeechSources:
    waveforms: torch.Tensor
    labels: torch.Tensor
    identities: tuple[str, ...]
    manifest: dict


def load_speech(root, role):
    """Read only one declared role; no held-out audio enters a fitting call."""
    if role not in ROLE_INDICES:
        raise ValueError("Unknown speech source role")
    root = Path(root)
    raw_manifest = (root / "source-manifest.json").read_bytes()
    if (hashlib.sha256(raw_manifest).hexdigest() != FSDD_MANIFEST_SHA256
            or hashlib.sha256((root / "original.tar.gz").read_bytes()).hexdigest() != FSDD_ARCHIVE_SHA256):
        raise ValueError("Public source archive or independent member manifest pin changed")
    manifest = json.loads(raw_manifest)
    if (manifest["source_commit"] != FSDD_COMMIT
            or manifest["archive_sha256"] != FSDD_ARCHIVE_SHA256
            or manifest["recordings"] != 3000):
        raise ValueError("Unrecognized public speech corpus identity")
    waveforms, labels, identities, source_records = [], [], [], []
    all_hashes = set()
    for record in sorted(manifest["files"], key=lambda item: item["path"]):
        relative = Path(record["path"])
        if relative.suffix != ".wav":
            continue
        if relative.is_absolute() or ".." in relative.parts or relative.parts[0] != "recordings":
            raise ValueError("Unsafe speech source path")
        label, speaker, index = relative.stem.split("_")
        label, index = int(label), int(index)
        if not 0 <= label <= 9 or not 0 <= index < 50 or not speaker:
            raise ValueError("Invalid public speech source identity")
        if record["sha256"] in all_hashes:
            raise ValueError("Duplicate speech bytes require explicit source regrouping")
        all_hashes.add(record["sha256"])
        if index not in ROLE_INDICES[role]:
            continue
        path = root / relative
        raw = path.read_bytes()
        if len(raw) != record["bytes"] or hashlib.sha256(raw).hexdigest() != record["sha256"]:
            raise ValueError("Speech source bytes changed")
        with wave.open(str(path), "rb") as source:
            if (source.getnchannels(), source.getsampwidth(), source.getframerate()) != (1, 2, SAMPLE_RATE):
                raise ValueError("Expected real mono 16-bit 8 kHz source")
            count = source.getnframes()
            if not 1 <= count <= 4 * SAMPLE_RATE:
                raise ValueError("Unexpected spoken-digit duration")
            samples = np.frombuffer(source.readframes(count), dtype="<i2").astype(np.float32) / 32768
        value = torch.from_numpy(samples.copy())
        peak = value.abs().max()
        if not torch.isfinite(value).all() or peak <= 1e-5:
            raise ValueError("Empty or nonfinite source speech")
        value = .9 * value / peak
        # Preserve original rate and phoneme timing unless a word exceeds 1 s.
        stretched = len(value) > WORD_SAMPLES
        if stretched:
            value = F.interpolate(value[None, None], size=WORD_SAMPLES,
                                  mode="linear", align_corners=False)[0, 0]
        else:
            value = F.pad(value, (0, WORD_SAMPLES - len(value)))
        waveforms.append(value)
        labels.append(label)
        identities.append(record["sha256"])
        source_records.append({**record, "speaker": speaker, "index": index,
                               "label": label, "source_samples": count,
                               "duration_resampled": stretched})
    expected = 60 * len(ROLE_INDICES[role])
    if len(waveforms) != expected:
        raise ValueError("Incomplete speech role census")
    return SpeechSources(torch.stack(waveforms), torch.tensor(labels),
                         tuple(identities), {"role": role, "files": source_records,
                                            "source_commit": FSDD_COMMIT,
                                            "archive_sha256": FSDD_ARCHIVE_SHA256})


def speech_spectrum(waveforms):
    if waveforms.ndim != 2 or waveforms.shape[1] != WORD_SAMPLES:
        raise ValueError("Expected a batch of one-second speech segments")
    spectrum = torch.stft(waveforms, n_fft=FFT_SIZE, hop_length=HOP_SIZE,
                          window=torch.hann_window(FFT_SIZE, device=waveforms.device),
                          return_complex=True)
    return spectrum.abs().clamp_min(1e-5).log()[:, None] / SPEC_SCALE


def spectrum_waveform(spectrum, seed, iterations=24):
    """Deterministic Griffin-Lim phase reconstruction of learned magnitudes."""
    if spectrum.ndim != 4 or tuple(spectrum.shape[1:]) != (1, 129, 101):
        raise ValueError("Expected learned Bx1x129x101 log-magnitude spectra")
    if not torch.isfinite(spectrum).all() or not 1 <= iterations <= 64:
        raise ValueError("Invalid bounded waveform reconstruction")
    magnitude = (spectrum[:, 0] * SPEC_SCALE).clamp(-12, 4).exp()
    generator = torch.Generator(device="cpu").manual_seed(seed)
    phase = torch.rand(magnitude.shape, generator=generator) * (2 * torch.pi)
    estimate = torch.polar(magnitude, phase)
    window = torch.hann_window(FFT_SIZE)
    for _ in range(iterations):
        signal = torch.istft(estimate, n_fft=FFT_SIZE, hop_length=HOP_SIZE,
                             window=window, length=WORD_SAMPLES)
        transformed = torch.stft(signal, n_fft=FFT_SIZE, hop_length=HOP_SIZE,
                                 window=window, return_complex=True)
        estimate = magnitude * transformed / transformed.abs().clamp_min(1e-8)
    signal = torch.istft(estimate, n_fft=FFT_SIZE, hop_length=HOP_SIZE,
                         window=window, length=WORD_SAMPLES)
    return .9 * signal / signal.abs().amax(dim=1, keepdim=True).clamp_min(1e-5)
