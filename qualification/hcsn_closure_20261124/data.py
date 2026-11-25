"""New source identities for prospective delayed-evidence confirmation."""

import numpy as np
import torch

from qualification.hcsn_smallnet_20261124.data import TaskBatch


SOURCES = {
    "smoke_train": tuple(range(9000, 9002)),
    "smoke_dev": tuple(range(9100, 9102)),
    "train": tuple(range(10000, 10012)),
    "dev": tuple(range(11000, 11004)),
    "test": tuple(range(12000, 12016)),
}


def generate_sources(sources, *, per_source=48, length=12, delay=0,
                     dtype=torch.float32, namespace="closure"):
    """A and B have identical positive gain; B cannot affect earlier inputs.

    Source IDs select independent synthetic nuisance laws, not real sensors.
    Delay adds blank noisy ticks between A and B; it is a declared distribution
    shift, not a resampling of the physical time step or of a continuous law.
    """
    if length < 12 + delay or per_source < 1 or delay < 0:
        raise ValueError("positive source size and enough ticks for delayed B required")
    xs, ys, groups, margins, late_steps, ids = [], [], [], [], [], []
    for source in sources:
        rng = np.random.default_rng(20261124 + 1009 * source)
        a, b = rng.uniform(-1, 1, (2, per_source))
        gain, noise = rng.uniform(.85, 1.15), rng.uniform(.08, .35)
        correlation = rng.uniform(-.5, .7)
        late = rng.integers(4, 7, per_source) + delay
        x = np.zeros((length, per_source, 6), dtype=np.float64)
        x[0, :, 0], x[0, :, 2] = gain * a, 1
        x[late, np.arange(per_source), 1] = gain * b
        x[late, np.arange(per_source), 3] = 1
        x[:, :, 4] = np.arange(length)[:, None] / (length - 1)
        for tick in range(length):
            x[tick, :, 5] = noise * rng.normal(size=per_source)
            if tick:
                x[tick, :, 5] += correlation * x[tick - 1, :, 5]
        xs.append(x)
        ys.append((a + b > 0).astype(np.int64))
        groups.extend([source] * per_source)
        margins.append(rng.uniform(.45, .85, per_source))
        late_steps.append(late)
        ids.extend(f"{namespace}:{source}:{i}" for i in range(per_source))
    return TaskBatch(torch.as_tensor(np.concatenate(xs, 1), dtype=dtype),
                     torch.as_tensor(np.concatenate(ys)), torch.tensor(groups),
                     torch.as_tensor(np.concatenate(margins), dtype=dtype),
                     torch.as_tensor(np.concatenate(late_steps)), tuple(ids))


def make_data(split, *, per_source=48, length=12, dtype=torch.float32):
    return generate_sources(SOURCES[split], per_source=per_source, length=length,
                            dtype=dtype, namespace="closure-v1-" + split)
