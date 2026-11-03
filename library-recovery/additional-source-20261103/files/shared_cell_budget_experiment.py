#!/usr/bin/env python3
"""Equal-budget shared-encoder vs local Cell head qualification experiment.

The encoder is a fixed feature cache. Only tiny linear heads are trained. This
is intentionally a control experiment: it cannot claim multimodal or LLM
capability and remains SHADOW_ONLY/DENY_ALL.
"""
from __future__ import annotations

from dataclasses import dataclass
import argparse
import hashlib
import json
import math
import random
from typing import Dict, List, Sequence, Tuple


AUTHORITY = "DENY_ALL"
PROTOCOL_MODE = "SHADOW_ONLY"


@dataclass(frozen=True)
class Example:
    x: Tuple[float, ...]
    y: float


@dataclass(frozen=True)
class FeatureCache:
    train: Dict[int, List[Example]]
    future: Dict[int, List[Example]]
    cross: Dict[int, List[Example]]
    digest: str

    @property
    def old_train(self) -> Dict[int, List[Example]]:
        return self.train


@dataclass
class LinearHead:
    w: List[float]
    b: float

    @classmethod
    def zeros(cls, dim: int) -> "LinearHead":
        return cls([0.0] * dim, 0.0)

    def predict(self, x: Sequence[float]) -> float:
        return sum(a * b for a, b in zip(self.w, x)) + self.b

    def update(self, batch: Sequence[Example], lr: float) -> float:
        if not batch:
            return 0.0
        grad_w = [0.0] * len(self.w)
        grad_b = 0.0
        loss = 0.0
        for ex in batch:
            err = self.predict(ex.x) - ex.y
            loss += err * err
            for i, value in enumerate(ex.x):
                grad_w[i] += 2.0 * err * value / len(batch)
            grad_b += 2.0 * err / len(batch)
        for i in range(len(self.w)):
            self.w[i] -= lr * grad_w[i]
        self.b -= lr * grad_b
        return loss / len(batch)


def _features(rng: random.Random, n: int, dim: int) -> List[Tuple[float, ...]]:
    return [tuple(rng.uniform(-1.0, 1.0) for _ in range(dim)) for _ in range(n)]


def _dataset(seed: int, cells: int = 4, dim: int = 6) -> Tuple[Dict[int, List[Example]], Dict[int, List[Example]], Dict[int, List[Example]]]:
    rng = random.Random(seed)
    train: Dict[int, List[Example]] = {}
    future: Dict[int, List[Example]] = {}
    cross: Dict[int, List[Example]] = {}
    base = [rng.uniform(-1.0, 1.0) for _ in range(dim)]
    for cell in range(cells):
        # Each Cell has a small idiosyncratic residual around a common factor.
        coeff = [base[i] + (cell - 1.5) * 0.15 * (1 if i % 2 == 0 else -1) for i in range(dim)]
        bias = (cell - 1.5) * 0.08
        def make(n: int, noise: float) -> List[Example]:
            out = []
            for x in _features(rng, n, dim):
                y = sum(a * b for a, b in zip(coeff, x)) + bias + rng.gauss(0.0, noise)
                out.append(Example(x, y))
            return out
        train[cell] = make(64, 0.03)
        future[cell] = make(64, 0.03)
        cross[cell] = make(64, 0.03)
    return train, future, cross


def build_feature_cache(seed: int = 17, cells: int = 4, dim: int = 6) -> FeatureCache:
    train, future, cross = _dataset(seed, cells, dim)
    digest_source = repr((train, future, cross)).encode("utf-8")
    digest = hashlib.sha256(digest_source).hexdigest()
    return FeatureCache(train, future, cross, digest)


def mse(head: LinearHead, data: Sequence[Example]) -> float:
    return sum((head.predict(ex.x) - ex.y) ** 2 for ex in data) / max(1, len(data))


def utility_from_mse(value: float) -> float:
    """Map held-out MSE to a bounded utility proxy in ``[0, 1]``."""
    return 1.0 / (1.0 + max(0.0, value))


def run(seed: int = 17, cells: int = 4, dim: int = 6, total_steps: int = 120,
        batch_size: int = 32, lr: float = 0.08) -> Dict[str, object]:
    cache = build_feature_cache(seed, cells, dim)
    train, future, cross = cache.train, cache.future, cache.cross
    pooled = [ex for cell in range(cells) for ex in train[cell]]
    rng = random.Random(seed + 1)
    if cells < 1 or dim < 1 or batch_size < 1:
        raise ValueError("cells, dim and batch_size must be positive")
    # Round the requested optimizer steps down to a common multiple of the
    # number of Cells.  This makes aggregate head-update FLOPs exactly equal
    # for arbitrary caller-supplied ``total_steps``.
    effective_steps = max(cells, (total_steps // cells) * cells)
    # The same optimizer-step × batch × feature budget is used for both arms.
    shared = LinearHead.zeros(dim)
    shared_losses = []
    for _ in range(effective_steps):
        batch = [pooled[rng.randrange(len(pooled))] for _ in range(batch_size)]
        shared_losses.append(shared.update(batch, lr))

    local: Dict[int, LinearHead] = {cell: LinearHead.zeros(dim) for cell in range(cells)}
    local_losses = []
    local_steps = max(1, total_steps // cells)
    for cell in range(cells):
        for _ in range(local_steps):
            batch = [train[cell][rng.randrange(len(train[cell]))] for _ in range(batch_size)]
            local_losses.append(local[cell].update(batch, lr))

    shared_future = sum(mse(shared, future[cell]) for cell in range(cells)) / cells
    local_future = sum(mse(local[cell], future[cell]) for cell in range(cells)) / cells
    shared_cross = sum(mse(shared, cross[cell]) for cell in range(cells)) / cells
    local_cross = sum(mse(local[cell], cross[cell]) for cell in range(cells)) / cells
    wrong_routing = sum(mse(local[(cell + 1) % cells], future[cell]) for cell in range(cells)) / cells
    params_shared = dim + 1
    params_local = cells * (dim + 1)
    train_flops = effective_steps * batch_size * (2 * dim + 1)
    local_flops = cells * local_steps * batch_size * (2 * dim + 1)
    shared_future_utility = 1.0 / (1.0 + shared_future)
    local_future_utility = 1.0 / (1.0 + local_future)
    shared_cross_utility = 1.0 / (1.0 + shared_cross)
    local_cross_utility = 1.0 / (1.0 + local_cross)
    # The stress arm deliberately routes every future Cell to its next Cell
    # (modulo the Cell count).  Keep the actual routing error probability
    # separate from the wrong-route MSE and its bounded utility proxy.
    wrong_routing_rate = 1.0
    wrong_routing_utility = utility_from_mse(wrong_routing)
    arms = [
        {
            "architecture": "shared_head",
            "mode": PROTOCOL_MODE,
            "authority": AUTHORITY,
            "train_flops": train_flops,
            "train_budget_flops": train_flops,
            "parameter_count": params_shared,
            "cache_digest": cache.digest,
            "future_utility": shared_future_utility,
            "cross_dataset_utility": shared_cross_utility,
            "wrong_routing_rate": wrong_routing_rate,
            "wrong_routing_utility": shared_future_utility,
            "old_task_degradation": 0.0,
        },
        {
            "architecture": "per_cell_light_head",
            "mode": PROTOCOL_MODE,
            "authority": AUTHORITY,
            "train_flops": local_flops,
            "train_budget_flops": train_flops,
            "parameter_count": params_local,
            "cache_digest": cache.digest,
            "future_utility": local_future_utility,
            "cross_dataset_utility": local_cross_utility,
            "wrong_routing_rate": wrong_routing_rate,
            "wrong_routing_utility": wrong_routing_utility,
            "old_task_degradation": max(0.0, local_future - shared_future),
        },
    ]
    return {
        "seed": seed,
        "cells": cells,
        "dim": dim,
        "authority": AUTHORITY,
        "status": PROTOCOL_MODE,
        "protocol": {
            "mode": PROTOCOL_MODE,
            "authority": AUTHORITY,
            "production_caller": False,
            "model_invocation": False,
            "provider_dispatch": False,
        },
        "encoder": {
            "frozen": True,
            "same_cache_for_all_arms": True,
            "cache_digest": cache.digest,
        },
        "budget": {
            "shared_train_flops": train_flops,
            "local_train_flops": local_flops,
            "equal_within_rounding": abs(train_flops - local_flops) <= batch_size * (2 * dim + 1) * cells,
            "budget_is_equal_across_arms": train_flops == local_flops,
            "train_flops": train_flops,
            "effective_steps": effective_steps,
        },
        "parameters": {"shared": params_shared, "local": params_local},
        "future_mse": {"shared": shared_future, "local": local_future},
        "cross_dataset_mse": {"shared": shared_cross, "local": local_cross},
        "wrong_routing_rate": wrong_routing_rate,
        "wrong_routing_mse": wrong_routing,
        "wrong_routing_utility": wrong_routing_utility,
        "old_task_degradation_proxy": max(0.0, local_future - shared_future),
        "training_loss_last": {"shared": shared_losses[-1], "local": local_losses[-1]},
        "arms": arms,
        "note": "fixed shared feature cache; synthetic data; no claim of model efficacy",
    }


def run_experiment(seed: int = 17) -> Dict[str, object]:
    """Stable interface for the cross-arm qualification harness."""
    return run(seed=seed)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--seed", type=int, default=17)
    args = parser.parse_args()
    print(json.dumps(run(seed=args.seed), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
