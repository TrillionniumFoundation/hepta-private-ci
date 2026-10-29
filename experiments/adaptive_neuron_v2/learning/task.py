"""Independent support/query Bernoulli tasks with causal six-feature inputs."""

from dataclasses import dataclass
import hashlib
import math

import numpy as np


SPLIT_CODES = {
    "support": 1201,
    "query": 1213,
    "validation": 1223,
    "id_test": 1231,
    "ood_test": 1237,
    "development": 1291,
}


@dataclass
class Batch:
    observations: np.ndarray
    truth: np.ndarray
    reliability: np.ndarray
    cost: np.ndarray
    deadline: np.ndarray
    features: np.ndarray
    digest: str


def features(observation, reliability, cost, deadline, elapsed):
    """The identical feature contract used by scalar native inference."""
    if observation not in (-1, 1) or not 0.5 < reliability < 1:
        raise ValueError("binary evidence and informative known reliability required")
    if not math.isfinite(cost) or cost < 0 or not 1 <= elapsed <= deadline <= 16:
        raise ValueError("cost/deadline/elapsed outside the task domain")
    return [
        float(observation),
        observation * math.log(reliability / (1 - reliability)),
        (reliability - 0.65) * 4,
        cost / 0.04,
        deadline / 16,
        elapsed / deadline,
    ]


def make_batch(seed, task_index, split, context, count):
    """Episode-keyed draws; action-dependent consumption cannot shift streams."""
    if split not in SPLIT_CODES or count < 1 or task_index < 0:
        raise ValueError("registered split, task index and count required")
    reliability, cost, deadline = context
    deadline = int(deadline)
    features(1, reliability, cost, deadline, 1)
    truth, evidence = [], []
    for episode in range(count):
        random = np.random.default_rng(
            np.random.SeedSequence([seed, SPLIT_CODES[split], task_index, episode])
        )
        label = 2 * random.integers(2) - 1
        truth.append(label)
        evidence.append(np.where(random.random(deadline) < reliability, label, -label))
    observations, truth = (
        np.asarray(evidence, dtype=float),
        np.asarray(truth, dtype=float),
    )
    inputs = np.asarray(
        [
            [
                features(int(observation), reliability, cost, deadline, t + 1)
                for t, observation in enumerate(row)
            ]
            for row in observations
        ]
    )
    r, c, h = (
        np.full(count, reliability),
        np.full(count, cost),
        np.full(count, deadline, dtype=int),
    )
    digest = hashlib.sha256()
    for array in (observations, truth, r, c, h):
        digest.update(np.ascontiguousarray(array).tobytes())
    return Batch(observations, truth, r, c, h, inputs, digest.hexdigest())
