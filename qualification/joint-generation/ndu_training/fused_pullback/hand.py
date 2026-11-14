"""Fixed hand inputs and assigned parameters; never loads trained weights/data."""

import time

import numpy as np

from data import templates
from independent.learning import CONTENT_PARAMETERS
from model import JointModel
from ndu_training.estimators import Sampler
from ndu_training.reinfer_d1.kernels import Reference
from ndu_training.fused_pullback.kernel import BoundReference


def moments(model, clock):
    model._moments = (
        {}
        if clock == 0
        else {
            key: (
                np.full_like(model.params[key], 0.001),
                np.full_like(model.params[key], 0.0001),
                clock,
            )
            for key in CONTENT_PARAMETERS
        }
    )


def fixture(plan, ledger):
    rng = np.random.default_rng(plan["input_seed"])
    n = plan["hand_full_rows"]
    x = rng.uniform(0, 1, (n, 202))
    pixels = x[:, :192].reshape(n, 4, 2, 4, 2, 3)
    low = np.concatenate(
        (
            pixels.mean(axis=(2, 4))
            .repeat(2, axis=1)
            .repeat(2, axis=2)
            .reshape(n, 192),
            x[:, 192:],
        ),
        axis=1,
    )
    labels = np.arange(n) % 12
    base = JointModel(202, 12, 192, hidden=32, seed=plan["base_seed"])
    assigned = 0.02 + 0.96 * templates()
    base.params["decoder"] = np.log(assigned / (1 - assigned))
    ledger.charge_kernel(
        "hand_prepare",
        "assigned_decoder",
        scalar_ops=2 * assigned.size,
        div_ops=assigned.size,
        log_ops=assigned.size,
    )
    ref = Reference(base, np.concatenate((x, low)), np.tile(labels, 2), ledger)
    started = time.process_time()
    bound = BoundReference(ref, ledger)
    bind_cpu = time.process_time() - started
    current = base.clone()
    for key in CONTENT_PARAMETERS:
        current.params[key] += plan["current_drift"] * rng.normal(
            size=current.params[key].shape
        )
    for model in (base, current):
        moments(model, 3)
        for value in model.params.values():
            value.flags.writeable = False
    return (
        {"base": base, "drifted": current},
        bound,
        {"full": x, "low": low, "labels": labels},
        bind_cpu,
    )


def draw(arrays, plan, sampler, low_count):
    s = Sampler(arrays["labels"], sampler, plan["draw_seed"])
    indices, weights, _ = s.draw()
    full = np.arange(64) >= low_count
    full = np.roll(full, 13)
    x = np.where(full[:, None], arrays["full"][indices], arrays["low"][indices])
    return x, arrays["labels"][indices], full, indices, weights
