"""Bounded development training of the installed dense Q24 model format.

This numerical adapter cannot sign, select, publish or activate a model. Both
heads have the explicit binary supervision target; the eight unused outputs
are frozen. Development labels never select an epoch or optimizer setting.
"""

import hashlib
import struct
import time

import numpy as np


Q24 = 1 << 24
LIMIT = 8 * Q24


def component_cut(rows, seed, development_components):
    """Fix whole-component membership from features before reading labels."""
    components = {row["component_digest"] for row in rows}
    if not 1 <= development_components < len(components) <= 64:
        raise ValueError("component split budget")
    ranked = sorted(
        components,
        key=lambda value: hashlib.sha256(
            f"hepta.public-training.component-cut.v1:{seed}:{value}".encode()
        ).digest(),
    )
    development = set(ranked[:development_components])
    return [
        "development" if row["component_digest"] in development else "train"
        for row in rows
    ]


def train(
    features_q24,
    labels,
    partitions,
    *,
    seed,
    epochs,
    learning_rate,
    deadline,
    maximum_rows=512,
):
    """Train only the declared TRAIN partition, with one bounded full batch."""
    if (
        type(epochs) is not int
        or not 1 <= epochs <= 300
        or not 0 < learning_rate <= 0.03
    ):
        raise ValueError("optimizer budget")
    x = np.asarray(features_q24, dtype=np.float64) / Q24
    y = np.asarray(labels, dtype=np.int64)
    mask = np.array([value == "train" for value in partitions])
    if (
        x.ndim != 2
        or x.shape != (len(y), 512)
        or maximum_rows not in (512, 698)
        or not 4 <= len(y) <= maximum_rows
        or len(partitions) != len(y)
        or not np.isfinite(x).all()
        or np.abs(x).max() > 8
        or set(y.tolist()) != {0, 1}
        or set(y[mask].tolist()) != {0, 1}
        or not (~mask).any()
        or set(partitions) != {"train", "development"}
    ):
        raise ValueError("binary training inputs")
    x, y = x[mask], y[mask]
    rng = np.random.default_rng(seed)
    parameters = [
        rng.normal(0, (2 / 512) ** 0.5, (512, 96)),
        np.zeros(96),
        rng.normal(0, (2 / 96) ** 0.5, (96, 2)),
        np.zeros(2),
    ]
    first = [np.zeros_like(value) for value in parameters]
    second = [np.zeros_like(value) for value in parameters]
    losses = []
    for epoch in range(1, epochs + 1):
        if time.monotonic() >= deadline:
            raise TimeoutError("original training deadline")
        w, b, v, c = parameters
        pre = x @ w + b
        hidden = np.clip(pre, 0, 8)
        raw_logits = hidden @ v + c
        logits = np.clip(raw_logits, -8, 8)
        logits -= logits.max(axis=1, keepdims=True)
        probability = np.exp(logits)
        probability /= probability.sum(axis=1, keepdims=True)
        losses.append(float(-np.log(probability[np.arange(len(y)), y]).mean()))
        delta = probability.copy()
        delta[np.arange(len(y)), y] -= 1
        delta /= len(y)
        delta *= (raw_logits > -8) & (raw_logits < 8)
        hidden_delta = (delta @ v.T) * ((pre > 0) & (pre < 8))
        gradients = [
            x.T @ hidden_delta,
            hidden_delta.sum(axis=0),
            hidden.T @ delta,
            delta.sum(axis=0),
        ]
        for index, gradient in enumerate(gradients):
            first[index] = 0.9 * first[index] + 0.1 * gradient
            second[index] = 0.999 * second[index] + 0.001 * gradient * gradient
            step = (first[index] / (1 - 0.9**epoch)) / (
                np.sqrt(second[index] / (1 - 0.999**epoch)) + 1e-8
            )
            parameters[index] = np.clip(parameters[index] - learning_rate * step, -8, 8)
    if not all(np.isfinite(value).all() for value in parameters + [np.array(losses)]):
        raise ValueError("nonfinite optimizer result")
    return parameters, {
        "initial_training_loss": losses[0],
        "last_epoch_input_training_loss": losses[-1],
        "completed_epochs": epochs,
    }


def quantized_payload(parameters):
    w, b, v, c = parameters
    if [value.shape for value in parameters] != [(512, 96), (96,), (96, 2), (2,)]:
        raise ValueError("trained tensor dimensions")
    encoder = np.column_stack((w.T, b))
    head = np.zeros((10, 97))
    head[:2, :96] = v.T
    head[:2, 96] = c
    head[2:, 96] = -8
    matrices = [encoder, head, head]
    encoded = []
    for matrix in matrices:
        if not np.isfinite(matrix).all() or np.abs(matrix).max() > 8:
            raise ValueError("physical Q24 coefficient bounds")
        encoded.append(np.rint(matrix * Q24).astype(">i8").tobytes(order="C"))
    return b"HPTNCPU1" + struct.pack(">HHH", 512, 96, 10) + b"".join(encoded)


def candidate_manifest(template, payload, model_id):
    """Retain the actual numeric runtime/device tuple, changing only tensors."""
    end = 14 + 96 * 513 * 8
    result = dict(template)
    result.update(
        model_id=model_id,
        weights_filename="weights.bin",
        weights_digest=hashlib.sha256(payload).hexdigest(),
        encoder_digest=hashlib.sha256(payload[14:end]).hexdigest(),
        head_digest=hashlib.sha256(payload[end:]).hexdigest(),
    )
    return result
