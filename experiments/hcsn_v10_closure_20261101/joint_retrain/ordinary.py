"""Larger ordinary MLP substitute on exactly the common six-scalar packet."""

import numpy as np
from .joint_model import softmax

WIDTH = 16
PARAMETERS = 6*WIDTH+WIDTH+WIDTH*5+5


def unpack(flat):
    a, b, c = 6*WIDTH, 7*WIDTH, 12*WIDTH
    return flat[:a].reshape(6, WIDTH), flat[a:b], flat[b:c].reshape(WIDTH, 5), flat[c:]


def predict(flat, x):
    w1, b1, w2, b2 = unpack(flat)
    hidden = np.tanh(x@w1+b1)
    return softmax(hidden@w2+b2)


def objective(flat, x, labels, l2):
    w1, b1, w2, b2 = unpack(flat)
    hidden = np.tanh(x@w1+b1)
    p = softmax(hidden@w2+b2)
    loss = -np.log(np.maximum(p[np.arange(len(labels)), labels], 1e-15)).mean()
    residual = p.copy()
    residual[np.arange(len(labels)), labels] -= 1
    residual /= len(labels)
    hidden_derivative = (residual@w2.T)*(1-hidden**2)
    gradient = np.r_[(x.T@hidden_derivative+l2*w1).ravel(), hidden_derivative.sum(0),
                     (hidden.T@residual+l2*w2).ravel(), residual.sum(0)]
    loss += 0.5*l2*(np.square(w1).sum()+np.square(w2).sum())
    return float(loss), gradient


def initialize(seed):
    rng = np.random.default_rng(seed)
    return np.r_[rng.normal(0, np.sqrt(2/(6+WIDTH)), (6, WIDTH)).ravel(), np.zeros(WIDTH),
                  rng.normal(0, np.sqrt(2/(WIDTH+5)), (WIDTH, 5)).ravel(), np.zeros(5)]
