"""Independent NumPy STFT/interpolation and a reconstructed frozen CNN."""

import json
import wave

import numpy as np
from scipy.signal import resample_poly
import torch
from torch import nn


def independent_features(path):
    with wave.open(str(path), 'rb') as stream:
        if (stream.getnchannels(), stream.getsampwidth(), stream.getframerate()) != (1, 2, 48000):
            raise AssertionError('Unexpected waveform representation')
        signal = np.frombuffer(stream.readframes(stream.getnframes()), dtype='<i2')
    signal = resample_poly(signal.astype(float)/32768, 1, 6).astype(np.float32)
    if len(signal) < 256:
        signal = np.pad(signal, (0, 256-len(signal)))
    frames = np.lib.stride_tricks.sliding_window_view(signal, 256)[::64]
    window = (.5-.5*np.cos(2*np.pi*np.arange(256)/256)).astype(np.float32)
    spectrum = np.log1p(abs(np.fft.rfft(frames*window, axis=1))).T
    y = np.clip((np.arange(64)+.5)*spectrum.shape[0]/64-.5, 0, spectrum.shape[0]-1)
    x = np.clip((np.arange(64)+.5)*spectrum.shape[1]/64-.5, 0, spectrum.shape[1]-1)
    yl, xl = np.floor(y).astype(int), np.floor(x).astype(int)
    yh, xh = np.minimum(yl+1, spectrum.shape[0]-1), np.minimum(xl+1, spectrum.shape[1]-1)
    wy, wx = y-yl, x-xl
    resized = (spectrum[yl[:, None], xl[None, :]]*(1-wy[:, None])*(1-wx[None, :])
               + spectrum[yh[:, None], xl[None, :]]*wy[:, None]*(1-wx[None, :])
               + spectrum[yl[:, None], xh[None, :]]*(1-wy[:, None])*wx[None, :]
               + spectrum[yh[:, None], xh[None, :]]*wy[:, None]*wx[None, :]).astype(np.float32)
    resized = (resized-resized.mean())/max(float(resized.std(ddof=1)), 1e-6)
    return torch.from_numpy(resized[None])


def verify_waveforms(run, source):
    torch.set_num_threads(1)
    model = nn.Sequential(nn.Conv2d(1, 12, 5, stride=2, padding=2), nn.ReLU(),
                          nn.Conv2d(12, 24, 3, stride=2, padding=1), nn.ReLU(),
                          nn.AdaptiveAvgPool2d((4, 4)), nn.Flatten(), nn.Linear(384, 64),
                          nn.ReLU(), nn.Linear(64, 10)).eval().requires_grad_(False)
    original = torch.load(run/'observer.pt', weights_only=True, map_location='cpu')
    model.load_state_dict({key.removeprefix('net.'): value for key, value in original.items()})
    rows = json.loads((run/'observations_test.json').read_text())
    max_error, rank_disagreements = 0., 0
    with torch.inference_mode():
        for offset in range(0, len(rows), 64):
            batch = rows[offset:offset+64]
            x = torch.stack([independent_features(source/row['source_path']) for row in batch])
            actual = model(x).softmax(1).double().numpy()
            expected = np.array([row['probabilities'] for row in batch])
            max_error = max(max_error, float(abs(actual-expected).max()))
            rank_disagreements += int(np.any(np.argsort(-actual, axis=1, kind='stable')[:, :2]
                                             != np.argsort(-expected, axis=1, kind='stable')[:, :2], axis=1).sum())
    if max_error > 1e-4 or rank_disagreements:
        raise AssertionError('Frozen waveform observations fail independent reconstruction')
    return {'actual_waveforms_reencoded': len(rows), 'maximum_probability_error': max_error,
            'rank_disagreements': rank_disagreements, 'probability_tolerance': 1e-4,
            'implementation': 'NumPy window/rFFT/bilinear interpolation, independently reconstructed CNN'}
