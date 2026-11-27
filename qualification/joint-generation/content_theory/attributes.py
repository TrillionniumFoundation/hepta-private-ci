"""Hand-only structured native-law prototype; not a trainable model runner."""

import numpy as np

from content_theory.categorical import softmax


def joint_logits(attribute_logits):
    z = np.asarray(attribute_logits, dtype=np.float64)
    if z.shape != (7,):
        raise ValueError("three color, two shape and two position logits required")
    return (z[:3, None, None] + z[None, 3:5, None] + z[None, None, 5:7]).reshape(12)


def attribute_law(attribute_logits):
    z = np.asarray(attribute_logits, dtype=np.float64)
    a, b, c = softmax(z[:3]), softmax(z[3:5]), softmax(z[5:7])
    return (a[:, None, None] * b[None, :, None] * c[None, None, :]).reshape(12)


def project_main_effects(joint_values):
    """Fixed ANOVA projection on trailing12 dimension, no data fitting."""
    values = np.asarray(joint_values, dtype=np.float64)
    if values.shape[-1] != 12:
        raise ValueError("trailing twelve semantic codes required")
    structured = values.reshape(*values.shape[:-1], 3, 2, 2)
    mean = structured.mean(axis=(-3, -2, -1), keepdims=False)
    color = structured.mean(axis=(-2, -1)) - mean[..., None]
    shape = structured.mean(axis=(-3, -1)) - mean[..., None]
    position = structured.mean(axis=(-3, -2)) - mean[..., None]
    return np.concatenate((color, shape, position), axis=-1)


def attribute_gradient(joint_logit_gradient):
    g = np.asarray(joint_logit_gradient).reshape(3, 2, 2)
    return np.concatenate((g.sum(axis=(1, 2)), g.sum(axis=(0, 2)), g.sum(axis=(0, 1))))
