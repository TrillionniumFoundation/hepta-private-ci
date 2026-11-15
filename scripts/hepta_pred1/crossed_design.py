"""Train/dev-only crossed randomness design, separate from frozen qualification.

The finite-grid decomposition is descriptive. Reusing a data or optimizer seed
across cells makes the cells dependent; no seed-level p-value is computed here.
"""

from hashlib import sha256
from itertools import combinations, product
import json

import numpy as np

from .simulator import ACTION_DIM, INPUT_DIM


VARIANTS = (
    "single_step",
    "gru",
    "diag_ssm",
    "dual_timescale",
    "gru_reset",
    "gru_no_action",
    "gru_no_time",
)
FACTORS = ("data", "init", "order")
# Both used confirmation campaigns, their selectors, and exposed planner pilots.
# Source: 885dae0/qualification/{pred1,cell-integrated-20261108-08b6/pred1}.
SEALED_OR_EXPOSED_SEEDS = frozenset(
    (
        11,
        22,
        33,
        101,
        202,
        303,
        404,
        505,
        9011,
        9017,
        3926890411,
        727086859,
        1852124203,
        2302186560,
        2281010178,
        440845250,
        3228430729,
        3070568927,
        952767533,
        3178635790,
        2295792649,
        3109268547,
        111838876,
        2929527613,
        2274992072,
        995533690,
    )
)
TARIFF_FIELDS = frozenset(
    (
        "state_step_work",
        "head_work",
        "candidate_planning_work",
        "state_step_time",
        "head_time",
        "candidate_planning_time",
    )
)


def canonical(value):
    return json.dumps(value, sort_keys=True, indent=2, allow_nan=False) + "\n"


def validate_config(config):
    """Refuse confirmation switches, old seeds, duplicate cells and unbounded fits."""
    keys = {
        "schema",
        "base_commit",
        "data_seeds",
        "init_seeds",
        "order_seeds",
        "variants",
        "train_episodes",
        "dev_episodes",
        "history_length",
        "epochs",
        "batch_size",
        "target_parameters",
        "learning_rate",
        "cost_profile",
        "expanded_budget",
        "expanded_deadline",
    }
    if not isinstance(config, dict) or set(config) != keys:
        raise ValueError("expected only the registered train/dev design fields")
    if config["schema"] != "pred1-crossed-train-dev-v1":
        raise ValueError("unsupported crossed design schema")
    base = config["base_commit"]
    if (
        not isinstance(base, str)
        or len(base) != 40
        or any(c not in "0123456789abcdef" for c in base)
    ):
        raise ValueError("base_commit must be a full immutable Git SHA")
    used = set()
    for factor in FACTORS:
        values = config[factor + "_seeds"]
        if (
            not isinstance(values, list)
            or not 2 <= len(values) <= 8
            or any(type(v) is not int or not 0 <= v < 2**32 for v in values)
            or len(set(values)) != len(values)
        ):
            raise ValueError("each factor requires 2..8 unique uint32 seeds")
        if set(values) & (used | SEALED_OR_EXPOSED_SEEDS):
            raise ValueError(
                "factor seeds overlap another factor or sealed/exposed data"
            )
        used.update(values)
    variants = config["variants"]
    if (
        not isinstance(variants, list)
        or not variants
        or any(v not in VARIANTS for v in variants)
        or len(set(variants)) != len(variants)
    ):
        raise ValueError("unknown or repeated model variant")
    for name, low, high in (
        ("train_episodes", 1, 100_000),
        ("dev_episodes", 1, 10_000),
        ("history_length", 4, 256),
        ("epochs", 1, 500),
        ("batch_size", 1, 4096),
        ("target_parameters", 128, 100_000),
    ):
        value = config[name]
        if type(value) is not int or not low <= value <= high:
            raise ValueError(f"invalid {name}")
    for name in ("learning_rate", "expanded_budget", "expanded_deadline"):
        value = config[name]
        if (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not np.isfinite(value)
            or value <= 0
        ):
            raise ValueError(f"invalid {name}")
    profile = config["cost_profile"]
    if not isinstance(profile, dict) or set(profile) != TARIFF_FIELDS:
        raise ValueError("all six explicit simulated tariff rates are required")
    for value in profile.values():
        if (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not np.isfinite(value)
            or value < 0
        ):
            raise ValueError("tariff rates must be finite nonnegative numbers")


def design_cells(config):
    validate_config(config)
    return list(product(*(config[factor + "_seeds"] for factor in FACTORS)))


def transform_inputs(x, query, variant):
    """Ablate both fitting and evaluation inputs without changing old generators.

    no_time removes explicit clock features and pools the four fast-sensor lag
    slots. Arrival order and missingness remain visible; this is not a claim to
    remove every temporal cue. gru_reset uses only the final row at zero state;
    in this simulator it jointly removes history and accumulated recurrent state.
    """
    if variant not in VARIANTS:
        raise ValueError("unknown variant")
    x, query = (
        np.array(x, dtype=float, copy=True),
        np.array(query, dtype=float, copy=True),
    )
    if (
        x.ndim != 3
        or x.shape[-1] != INPUT_DIM
        or x.shape[1] < 1
        or query.shape != (len(x), ACTION_DIM)
        or not np.isfinite(x).all()
        or not np.isfinite(query).all()
    ):
        raise ValueError("invalid simulator input shape or values")
    if variant == "gru_no_action":
        x[:, :, :3], query[:, :4] = 0, 0
    elif variant == "gru_no_time":
        counts = x[:, :, 6:13:2].sum(axis=-1)
        values = x[:, :, 5:12:2].sum(axis=-1)
        x[:, :, 5:15] = 0
        x[:, :, 5] = np.divide(
            values, counts, out=np.zeros_like(values), where=counts > 0
        )
        x[:, :, 6] = counts
    return x, query, variant == "gru_reset"


def decompose(values):
    """Orthogonal functional ANOVA on the complete balanced D x I x O grid.

    Report finite-grid squared deviations, including every interaction. These
    are not unbiased population variance-component estimates or independent
    replicates. A missing or failed cell must never be silently deleted.
    """
    y = np.asarray(values, dtype=float)
    if y.ndim != 3 or min(y.shape) < 2 or not np.isfinite(y).all():
        raise ValueError(
            "need a complete finite three-factor grid with >=2 levels each"
        )
    grand = float(y.mean())
    components = {(): np.full((1, 1, 1), grand)}
    results = {}
    for size in (1, 2, 3):
        for axes in combinations(range(3), size):
            eliminated = tuple(axis for axis in range(3) if axis not in axes)
            term = y.mean(axis=eliminated, keepdims=True) if eliminated else y.copy()
            for previous, effect in components.items():
                if set(previous) < set(axes):
                    term = term - effect
            components[axes] = term
            name = ":".join(FACTORS[axis] for axis in axes)
            results[name] = float(np.mean(term**2))
    total = float(np.mean((y - grand) ** 2))
    reconstructed = sum(np.broadcast_to(term, y.shape) for term in components.values())
    if not np.allclose(y, reconstructed, atol=1e-10, rtol=1e-10):
        raise AssertionError("factor decomposition did not reconstruct the grid")
    if not np.isclose(sum(results.values()), total, atol=1e-12, rtol=1e-10):
        raise AssertionError("factor squared deviations do not sum to grid variance")
    return {
        "grand_mean": grand,
        "grid_shape": list(y.shape),
        "cells": int(y.size),
        "finite_grid_variance": total,
        "mean_squared_components": results,
        "fraction_of_grid_variance": {
            name: value / total if total > 0 else None
            for name, value in results.items()
        },
        "marginal_means": {
            name: y.mean(axis=tuple(j for j in range(3) if j != i)).tolist()
            for i, name in enumerate(FACTORS)
        },
        "scope": "descriptive complete crossed grid; shared factors; no p-value or population variance claim",
    }


def registered_config():
    """Fixed prospective development design; no output-dependent seed selection."""
    seed_sets = {
        factor + "_seeds": [
            int.from_bytes(
                sha256(
                    f"hepta/PRED1/crossed-train-dev/2026-11-09-v1/{factor}/{i}".encode()
                ).digest()[:4],
                "big",
            )
            for i in range(1, 4)
        ]
        for factor in FACTORS
    }
    config = {
        "schema": "pred1-crossed-train-dev-v1",
        "base_commit": "885dae0f3285267e9e9c49d8b43b0d009779f9e8",
        **seed_sets,
        "variants": list(VARIANTS),
        "train_episodes": 4096,
        "dev_episodes": 512,
        "history_length": 16,
        "epochs": 30,
        "batch_size": 128,
        "target_parameters": 3000,
        "learning_rate": 0.003,
        "cost_profile": {
            "state_step_work": 0.0001,
            "head_work": 0.001,
            "candidate_planning_work": 0.0001,
            "state_step_time": 0.0001,
            "head_time": 0.001,
            "candidate_planning_time": 0.0001,
        },
        "expanded_budget": 16.0,
        "expanded_deadline": 20.0,
    }
    validate_config(config)
    return config
