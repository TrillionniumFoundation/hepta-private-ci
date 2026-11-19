"""Numerical learner and atomic checkpoints for the synthetic EVOLVE-1 pilot."""

from contextlib import contextmanager
import json
import os
import tempfile
import time

import numpy as np

from ._causal_checks import COST_STAGES, _sha


POLICIES = [(ratio, rate) for ratio in (0.0, 0.25, 0.5, 0.75) for rate in (0.03, 0.12)]


def save_json(path, value):
    """Replace one complete checkpoint; interrupted writes preserve the old one."""
    with tempfile.NamedTemporaryFile(mode="w", dir=path.parent, delete=False) as stream:
        temporary = stream.name
        json.dump(value, stream, sort_keys=True, allow_nan=False)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)
    if hasattr(os, "O_DIRECTORY"):
        descriptor = os.open(path.parent, os.O_DIRECTORY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)


def stream_seed(seed, label):
    return int(_sha({"seed": seed, "stream": label})[:32], 16)


def ledger():
    return {
        stage: {
            "status": "not_applicable",
            "values": {},
            "evidence": "CPU pilot: stage not executed",
        }
        for stage in COST_STAGES
    }


@contextmanager
def meter(costs, stage):
    wall, cpu = time.perf_counter(), time.process_time()
    try:
        yield
    finally:
        old = costs[stage]["values"]
        costs[stage] = {
            "status": "measured",
            "values": {
                "wall_seconds": old.get("wall_seconds", 0) + time.perf_counter() - wall,
                "cpu_seconds": old.get("cpu_seconds", 0) + time.process_time() - cpu,
                "energy_joules": None,
                "provider_charges": None,
            },
            "evidence": "local perf_counter/process_time; energy and charges unmeasured",
        }


def dataset(seed, size, family="gaussian"):
    rng = np.random.default_rng(seed)
    x = (
        rng.normal(size=(size, 8))
        if family == "gaussian"
        else rng.uniform(-2, 2, size=(size, 8))
    )
    x = np.column_stack((x, np.ones(size)))
    old = (x[:, 0] + 0.8 * x[:, 1] > 0).astype(float)
    new = (x[:, 0] - 0.8 * x[:, 1] > 0).astype(float)
    return x, old, new


def train(weights, samples, policy, seed, steps=64):
    """Exactly 64 equal-size updates; replay changes the target mixture only."""
    x, old, new = samples
    ratio, rate = policy
    rng = np.random.default_rng(seed)
    result = weights.copy()
    for _ in range(steps):
        ids = rng.integers(len(x), size=32)
        labels = np.where(rng.random(32) < ratio, old[ids], new[ids])
        logits = np.clip(x[ids] @ result, -40, 40)
        result -= rate * (x[ids].T @ (1 / (1 + np.exp(-logits)) - labels)) / 32
    return result


def accuracy(weights, samples, old=False):
    return float(np.mean((samples[0] @ weights > 0) == samples[1 if old else 2]))


def bind(weights):
    return _sha(
        {
            "weights": weights.tolist(),
            "state": [],
            "encoder": "identity-f64-9",
            "optimizer": "sgd-no-momentum",
            "schema": "evolve1.reference.v1",
        }
    )


def data_pin(samples):
    return _sha([array.tolist() for array in samples])


def discover(seed):
    """Learn a proposal distribution using development-only replay outcomes."""
    costs = ledger()
    with meter(costs, "training"):
        samples = dataset(stream_seed(seed, "discovery-training"), 192)
        validation = dataset(stream_seed(seed, "discovery-development"), 192)
        start = train(np.zeros(9), samples, (1.0, 0.12), seed, steps=120)
        scores = []
        for index, policy in enumerate(POLICIES):
            candidate = train(start, samples, policy, seed + index)
            scores.append(
                accuracy(candidate, validation)
                - 2
                * max(
                    0,
                    accuracy(start, validation, True)
                    - accuracy(candidate, validation, True),
                )
            )
        probabilities = np.exp(12 * (np.array(scores) - max(scores)))
        probabilities = 0.9 * probabilities / probabilities.sum() + 0.1 / len(POLICIES)
    return {
        "schema": "evolve1.frozen-proposer.v1",
        "policies": POLICIES,
        "probabilities": probabilities.tolist(),
        "training_seed": seed,
        "development_scores": scores,
        "discovery_training_data": data_pin(samples),
        "discovery_development_data": data_pin(validation),
    }, costs
