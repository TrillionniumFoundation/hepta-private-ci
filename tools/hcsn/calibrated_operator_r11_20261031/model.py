"""A bounded learned residual on ordinary, calibrated Bellman values."""
import hashlib
import json

import numpy as np

from ..task_native_loop_20261031.model import norm67
from ..task_value_factorial_20261030.controller import forward
from ..task_value_factorial_20261030.dataset import FEATURE_NAMES
from ..task_native_loop_20261031.model import EXTRA_FEATURES
from ..task_value_factorial_20261030.task import ACTIONS
from .propagation.finite import augmented_features
from .value import select_action

SCHEMA = "hcsn.calibrated.operator.policy.v1"


def design(records, family, parameters, norm, intervention="none"):
    cell = augmented_features(family, parameters, records)
    if intervention == "constant":
        cell[:] = .5
    elif intervention != "none":
        raise ValueError("Unknown cell-state intervention")
    raw = np.column_stack(([r["features"] for r in records], cell))
    return (raw-np.asarray(norm["mean"]))/np.asarray(norm["scale"])


def residual(weights, x, radius):
    output, hidden = forward(weights, x)
    delta = radius*np.tanh(output)
    delta[:, 0] = 0.
    return delta, hidden, output


def loss_gradient(weights, x, target, valid, radius):
    delta, hidden, output = residual(weights, x, radius)
    mask = valid.copy()
    mask[:, 0] = False
    # Dimensionless residual loss: no L2 term can masquerade as task gradient.
    error = (delta-target)/radius*mask
    loss = float(np.square(error).sum()/mask.sum())
    dq = 2*error*(1-np.tanh(output)**2)/mask.sum()
    dh = (dq @ weights["v"].T)*(1-hidden*hidden)
    return loss, dict(w=x.T@dh, b=dh.sum(0), v=hidden.T@dq, c=dq.sum(0))


def export(family, seed, theta, weights, norm, confusion, protocol, nodes):
    return dict(schema=SCHEMA, family="distribution" if family == "analytic" else "ordinary",
        controller="value", input_width=67, hidden_width=24, norm=norm,
        parameters=np.asarray(theta).tolist(), weights={k:np.asarray(v).tolist() for k,v in weights.items()},
        confusion=np.asarray(confusion).tolist(), fixed_boundary=.8, multiplier=protocol["multiplier"],
        latency_price=protocol["latency_price"], seed=seed,
        feature_names=list(FEATURE_NAMES+EXTRA_FEATURES), grid_nodes=nodes,
        residual_radius=protocol["residual_radius"], intervention="none")


def infer(policy, record, controller):
    q = controller.record_q(record)
    cell = None
    if policy["controller"] == "value":
        x = design([record], policy["family"], policy["parameters"], policy["norm"], policy["intervention"])
        delta, _, _ = residual({k:np.asarray(v) for k,v in policy["weights"].items()}, x, policy["residual_radius"])
        q += delta[0]
        cell = (x[0]*np.asarray(policy["norm"]["scale"])+policy["norm"]["mean"])[62:].tolist()
    action = select_action(q, record["feasible"])
    return dict(action=ACTIONS[action], action_index=action,
                q=np.where(record["feasible"], q, 0.).tolist(), cell_features=cell)


def identity(policy):
    return hashlib.sha256(json.dumps(policy,sort_keys=True,separators=(",",":"),allow_nan=False).encode()).hexdigest()
