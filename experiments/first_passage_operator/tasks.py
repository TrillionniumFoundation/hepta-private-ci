"""Registered temporal tasks with disjoint named identity streams."""

import hashlib

import numpy as np


TASKS = ("evidence", "order", "delayed_match")


def task_data(task, split, seed, size):
    """Generate only the requested split; labels never encode simulator parameters."""
    if task not in TASKS or split not in {"train", "development", "confirmation"}:
        raise ValueError("Unregistered task or split")
    key = f"hepta.renewal-network.v1/{task}/{split}/{seed}"
    identity = int.from_bytes(hashlib.sha256(key.encode()).digest()[:16], "little")
    rng = np.random.default_rng(identity)
    labels = rng.integers(0, 2, size=size).astype(float)
    inputs = rng.normal(0, 0.12, size=(size, 8, 2))
    signs = 2 * labels - 1
    if task == "evidence":
        inputs = rng.normal(0, 0.65, size=(size, 8, 2))
        inputs[:, :, 0] += 0.6 * signs[:, None]
    elif task == "order":
        for i in range(size):
            early = int(rng.integers(1, 3))
            late = int(rng.integers(5, 7))
            first = int(labels[i])
            inputs[i, early, first] += 2.5
            inputs[i, late, 1 - first] += 2.5
    else:
        cue = rng.choice([-1.0, 1.0], size=size)
        query = cue * signs
        inputs[:, 1:6, 0] += rng.normal(0, 0.7, size=(size, 5))
        inputs[:, 0, 0] += 2.5 * cue
        inputs[:, 6, 1] += 2.5 * query
    return inputs, labels
