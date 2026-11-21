"""New independent mechanism probes; labels never import or call HCSN."""
import hashlib
import math

import numpy as np

TASKS = ("first_passage", "burst", "asynchronous", "association")
SPLITS = ("train", "dev", "final_iid", "final_clock")


def generate(namespace, seed, task, split, count, length=12):
    if task not in TASKS or split not in SPLITS or count < 2 or length < 4:
        raise ValueError("unknown task/split or undersized independent window")
    identity = f"{namespace}/{seed}/{task}/{split}"
    key = int.from_bytes(hashlib.sha256(identity.encode()).digest()[:8], "little")
    rng = np.random.default_rng(key)
    low, high = (180_000, 450_001) if split == "final_clock" else (40_000, 120_001)
    dt = rng.integers(low, high, (count, length)).astype(np.float64) / 1e6
    x = np.zeros((count, length, 4), dtype=np.float64)
    if task == "first_passage":
        z, drift = rng.uniform(.1, 1.2, count), rng.uniform(-.3, .3, count)
        for t in range(length):
            z += drift * dt[:, t] + .3 * np.sqrt(dt[:, t]) * rng.normal(size=count)
            x[:, t, 0], x[:, t, 1] = z, drift
        # Exact Brownian first passage over a NEW future 0.5-second interval.
        margin, horizon, sigma = np.maximum(z, 0), .5, .3
        cdf = np.vectorize(lambda v: .5 * math.erfc(-v / math.sqrt(2)))
        denominator = sigma * math.sqrt(horizon)
        y = cdf((-margin - drift * horizon) / denominator)
        y += np.exp(-2 * drift * margin / sigma**2) * cdf((-margin + drift * horizon) / denominator)
        y = np.clip(y, 0, 1)
    elif task == "burst":
        state = rng.integers(0, 2, count)
        for t in range(length):
            state ^= (rng.random(count) < -.5 * np.expm1(-2.4 * dt[:, t])).astype(int)
            x[:, t, 0] = rng.poisson((.5 + 3.5 * state) * dt[:, t]) / 4
        # Conditional future expected count of a symmetric two-state rate process.
        y = (2.25 + ((.5 + 3.5 * state) - 2.25) * (-math.expm1(-2.4)) / 2.4) / 4
    elif task == "asynchronous":
        phase, frequency = rng.uniform(-math.pi, math.pi, count), rng.uniform(.4, 1.2, count)
        latent = np.sin(phase[:, None] + frequency[:, None] * dt.cumsum(1))
        mask = rng.integers(0, 2, (count, length)).astype(bool)
        x[:, :, 0] = np.where(mask, latent + rng.normal(0, .15, latent.shape), 0)
        x[:, :, 1] = np.where(~mask, .7 * latent + .2 + rng.normal(0, .15, latent.shape), 0)
        x[:, :, 2], x[:, :, 3] = mask, ~mask
        y = latent[:, -1]
    else:
        values, first_key = rng.uniform(-.8, .8, (count, 2)), rng.choice([-1., 1.], count)
        query = rng.choice([-1., 1.], count)
        x[:, 0, 0], x[:, 1, 0] = values[:, 0], values[:, 1]
        x[:, 0, 1], x[:, 1, 1] = first_key * values[:, 0], -first_key * values[:, 1]
        x[:, :2, 2], x[:, -1, 3] = 1, query
        x[:, 2:-1, 2] = rng.normal(0, .2, (count, length - 3))  # irrelevant distractors
        y = np.where(query == first_key, values[:, 0], values[:, 1])
    ids = np.array([f"{identity}/{i}" for i in range(count)])
    return {"x": x, "dt": dt, "y": y[:, None], "ids": ids}


def digest(data):
    result = hashlib.sha256()
    for name, array in sorted(data.items()):
        result.update(str((name, array.shape, array.dtype)).encode())
        result.update(array.tobytes())
    return result.hexdigest()

