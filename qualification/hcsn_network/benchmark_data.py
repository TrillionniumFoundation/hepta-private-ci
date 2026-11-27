"""Original writer-separated UCI PenDigits split; training-only validation."""

import hashlib
from pathlib import Path

import numpy as np
import torch


DATA_SHA256 = {"pendigits.tra": "e2b9eb9f0d0467e2b64a4816a3420edf2b8043447576f4b84337aba44a9f97d3",
               "pendigits.tes": "8bd03229c5c5291fefe43e45465dd948d2645bf23328b9d993e0b777666b2015"}


def _load(directory, name):
    path = Path(directory)/name
    if hashlib.sha256(path.read_bytes()).hexdigest() != DATA_SHA256[name]:
        raise ValueError("original UCI dataset bytes changed")
    rows = np.loadtxt(path, delimiter=",", dtype=np.int64)
    if rows.shape != ((7494 if name.endswith("tra") else 3498), 17):
        raise ValueError("original dataset shape mismatch")
    if np.any((rows[:, :16] < 0) | (rows[:, :16] > 100)) or np.any((rows[:, 16] < 0) | (rows[:, 16] > 9)):
        raise ValueError("dataset outside original declared domain")
    x = torch.tensor(rows[:, :16].reshape(-1, 8, 2)/50.-1., dtype=torch.float64)
    # Two zero-input intervals allow the declared layer latency to drain.
    x = torch.cat((x, x.new_zeros(len(x), 2, 2)), dim=1)
    return x, torch.tensor(rows[:, 16], dtype=torch.int64)


def training_data(directory):
    """No test file is opened here. 75 validation rows per training class."""
    x, y = _load(directory, "pendigits.tra")
    generator = np.random.default_rng(271828)
    validation = np.concatenate([generator.permutation(np.flatnonzero(y.numpy() == k))[:75]
                                 for k in range(10)])
    validation.sort()
    training = np.setdiff1d(np.arange(len(x)), validation)
    return x[training], y[training], x[validation], y[validation], training, validation


def testing_data(directory):
    """Called only by the separate post-seal evaluation stage."""
    return _load(directory, "pendigits.tes")
