"""Frozen scalar model contract shared by training and independent replay.

The native owner consumes public task metadata and its own observed history.
This module never treats a model prediction as a supplied owner action.
"""
import hashlib
import json

import numpy as np

from ..task_value_factorial_20261030.cells import augmented_features
from ..task_value_factorial_20261030.controller import forward, normalization
from ..task_value_factorial_20261030.dataset import FEATURE_NAMES
from ..task_value_factorial_20261030.execution import boundary_action
from ..task_value_factorial_20261030.task import ACTIONS

SCHEMA = "hcsn.task.native.policy.v1"
ARMS = ("ordinary_fixed", "ordinary_value", "analytic_fixed", "analytic_value")
EXTRA_FEATURES = ("cell_0", "cell_1", "cell_2", "cell_3", "next_observation_probability")


def norm67(records):
    fitted = normalization(records)
    return dict(mean=fitted["mean"] + [.5] * 5,
                scale=fitted["scale"] + [.5] * 5)


def design(records, family, parameters, norm):
    family = "analytic" if family == "distribution" else family
    public = np.asarray([r["features"] for r in records], np.float64)
    raw = np.column_stack((public, augmented_features(family, parameters, records)))
    z = (raw - np.asarray(norm["mean"])) / np.asarray(norm["scale"])
    if z.shape != (len(records), 67) or not np.all(np.isfinite(z)):
        raise ValueError("Invalid normalized policy inputs")
    return z


def validate(policy):
    expected = {"schema", "family", "controller", "input_width", "hidden_width", "norm",
                "parameters", "weights", "confusion", "fixed_boundary", "multiplier",
                "latency_price", "seed", "feature_names"}
    if set(policy) != expected or policy["schema"] != SCHEMA:
        raise ValueError("Policy schema mismatch")
    if policy["family"] not in ("ordinary", "distribution") or policy["controller"] not in ("fixed", "value"):
        raise ValueError("Unknown cell family or controller")
    if policy["input_width"] != 67 or policy["hidden_width"] != 24:
        raise ValueError("Unsupported architecture")
    if policy["feature_names"] != list(FEATURE_NAMES + EXTRA_FEATURES):
        raise ValueError("Feature order changed")
    for name in ("mean", "scale"):
        a = np.asarray(policy["norm"][name], float)
        if a.shape != (67,) or not np.all(np.isfinite(a)) or (name == "scale" and np.any(a <= 0)):
            raise ValueError("Invalid normalization")
    theta = np.asarray(policy["parameters"], float)
    if theta.shape != (11,) or not np.all(np.isfinite(theta)) or np.max(np.abs(theta)) > 3.:
        raise ValueError("Cell parameters outside training domain")
    for name, shape in (("w", (67, 24)), ("b", (24,)), ("v", (24, 4)), ("c", (4,))):
        a = np.asarray(policy["weights"][name], float)
        if a.shape != shape or not np.all(np.isfinite(a)):
            raise ValueError("Invalid critic tensor")
    confusion = np.asarray(policy["confusion"], float)
    if confusion.shape != (2, 2) or np.any(confusion <= 0) or not np.allclose(confusion.sum(1), 1.):
        raise ValueError("Invalid observation law")
    return policy


def export(family, mode, seed, theta, weights, norm, confusion, protocol):
    return validate(dict(schema=SCHEMA, family="distribution" if family == "analytic" else family,
        controller=mode, input_width=67, hidden_width=24, norm=norm,
        parameters=np.asarray(theta).tolist(), weights={k: np.asarray(v).tolist() for k, v in weights.items()},
        confusion=np.asarray(confusion).tolist(), fixed_boundary=protocol["fixed_boundary"],
        multiplier=protocol["multiplier"], latency_price=protocol["latency_price"], seed=seed,
        feature_names=list(FEATURE_NAMES + EXTRA_FEATURES)))


def identity(policy):
    return hashlib.sha256(json.dumps(policy, sort_keys=True, separators=(",", ":"),
                                    allow_nan=False).encode()).hexdigest()


def infer(policy, record):
    """Pre-action absolute Q and deterministic legal choice; no clipping."""
    validate(policy)
    if policy["controller"] == "fixed":
        action = boundary_action(record, policy["fixed_boundary"])
        return dict(action=ACTIONS[action], action_index=action, q=None,
                    raw_features=None, normalized_features=None)
    z = design([record], policy["family"], policy["parameters"], policy["norm"])
    q, _ = forward({k: np.asarray(v) for k, v in policy["weights"].items()}, z)
    action = int(np.argmax(np.where(record["feasible"], q[0], -np.inf)))
    raw = z[0] * np.asarray(policy["norm"]["scale"]) + np.asarray(policy["norm"]["mean"])
    return dict(action=ACTIONS[action], action_index=action, q=q[0].tolist(),
                raw_features=raw.tolist(), normalized_features=z[0].tolist())
