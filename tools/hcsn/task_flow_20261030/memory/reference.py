"""Independent NumPy delta recurrence; old financial reference is reused."""
from pathlib import Path
import sys

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from third.memory import reference as old


def delta_update(memory, key, value, write):
    residual = value - np.einsum("bk,bkh->bh", key, memory)
    increment = key[:, :, None] * residual[:, None, :]
    increment *= (write / (0.0001 + np.sum(key * key, axis=1, keepdims=True)))[:, :, None]
    result = memory + increment
    norms = np.sqrt(np.sum(result.astype(np.float64) ** 2, axis=1, keepdims=True))
    return result * np.minimum(1., 8. / np.maximum(norms, 1e-10)).astype(result.dtype)


def forward(params, x, dt, variant):
    name, mode = variant.split("_")
    if mode != "delta":
        state = old.forward(params, x, dt, name)
        logits, _ = old.readout(params, state, mode, np.float64)
        return logits
    p = params
    batch, length = x.shape[:2]
    width = p["out"].shape[0]
    memory = np.zeros((batch, 16, width), x.dtype)
    xx = np.zeros((batch, width), x.dtype)
    yy = xx.copy()
    u = np.concatenate([x, np.log1p(dt)[..., None]], axis=-1)
    fast = .2 + 4.8 * old.sigmoid(p["tau_fast"])
    slow = 2. + 98. * old.sigmoid(p["tau_slow"])
    for index in range(length):
        incoming, duration = u[:, index], dt[:, index]
        hidden = np.tanh(incoming @ p["inp"] + p["bias"])
        key = np.tanh(incoming @ p["key"] + p["key_bias"]) / np.float32(4.)
        candidate = hidden @ p["value"] + p["value_bias"]
        q, a = old.gates(xx - p["boundary"] - incoming @ p["boundary_weights"], name)
        drive = 3. * np.tanh(hidden + .5 * np.tanh(p["recurrent_diag"]) * (2 * q - 1))
        ef, es = np.exp(-duration[:, None] / fast), np.exp(-duration[:, None] / slow)
        xx = ef * xx + (1 - ef) * (2. * old.sigmoid(p["call"]) * a
             + 4. * old.sigmoid(p["regen"]) * q - yy + drive)
        yy = es * yy + (1 - es) * 6. * old.sigmoid(p["recover"]) * q
        value = np.tanh(candidate + .1 * np.tanh(xx))
        current = (np.tanh(p["read_current"]) * hidden
                   + np.tanh(p["read_fast"]) * np.tanh(xx)
                   + np.tanh(p["read_slow"]) * np.tanh(yy))
        if index < length - 1:
            write = old.closed_write(incoming @ p["write"] + p["write_bias"])
            memory = delta_update(memory, key, value, write)
    read = np.einsum("bk,bkh->bh", key, memory)
    return (np.tanh(read) + current) @ p["out"] + p["out_bias"]
