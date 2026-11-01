"""Shared learned linear binding with three ordinary causal memory families.

No function in this module receives private key identities or query targets.
The delta memory is a gated linear associative recurrence, not a trained GRU or
modern selective SSM. The slot baselines make stronger content access available.
"""

import itertools
import time

import numpy as np

from .task import CLASSES, DIMENSION, SLOTS


def unit(vector):
    norm = np.linalg.norm(vector)
    if not np.isfinite(norm) or norm == 0:
        raise ValueError("Invalid public feature")
    return vector / norm


def fit_encoders(train_a, train_b, select_a, select_b):
    """All regularizers are retained and charged; paired selection is separate."""
    candidates = []
    for penalty in (.0001, .01, 1.):
        start = time.process_time()
        weight = np.linalg.solve(train_b.T @ train_b + penalty * np.eye(DIMENSION),
                                 train_b.T @ train_a)
        loss = float(np.mean((select_b @ weight - select_a) ** 2))
        candidates.append(dict(penalty=penalty, weight=weight.tolist(), selection_mse=loss,
                               cpu_seconds=time.process_time() - start))
    index = min(range(len(candidates)), key=lambda i: (candidates[i]["selection_mse"], i))
    return candidates, index


def configurations(kind):
    if kind == "cosine":
        return [dict(threshold=x) for x in (.75, .85, .92)]
    if kind == "ridge":
        return [dict(threshold=x, penalty=y) for x, y in itertools.product((.75, .85, .92), (.0001, .01, .1))]
    if kind == "gated_delta":
        return [dict(step=x, decay=y, passes=z) for x, y, z in itertools.product((.5, 1.), (0., .01, .1), (1, 3))]
    raise ValueError("Unknown memory family")


class Memory:
    """Bounded state with shared raw WRITE/QUERY features and typed events."""

    def __init__(self, weight, kind, config):
        self.weight, self.kind, self.config = np.asarray(weight), kind, config
        self.used, self.clock = 0, 0.
        if kind == "gated_delta":
            self.state = np.zeros((DIMENSION, CLASSES))
        else:
            self.keys = np.zeros((SLOTS, DIMENSION))
            self.values = np.zeros((SLOTS, CLASSES))
            self.age = np.zeros(SLOTS)
            self.coefficients = np.zeros((0, CLASSES))
        self.operations = dict(writes=0, queries=0, distractors=0, evictions=0,
                               binding_matvecs=0, ridge_solves=0)

    def step(self, event):
        self.clock += event["dt"]
        kind = event["kind"]
        if self.kind == "gated_delta":
            self.state *= np.exp(-self.config["decay"] * event["dt"])
        if kind == "DISTRACTOR":
            self.operations["distractors"] += 1
            return None
        feature = np.asarray(event["feature"])
        if kind == "QUERY":
            feature = feature @ self.weight
            self.operations["binding_matvecs"] += 1
        key = unit(feature)
        if kind == "WRITE":
            self.operations["writes"] += 1
            value = np.eye(CLASSES)[event["value"]]
            if self.kind == "gated_delta":
                for _ in range(self.config["passes"]):
                    self.state += self.config["step"] * np.outer(key, value - key @ self.state)
            else:
                similarities = self.keys[:self.used] @ key
                index = int(np.argmax(similarities)) if self.used else 0
                if not self.used or similarities[index] < self.config["threshold"]:
                    if self.used < SLOTS:
                        index, self.used = self.used, self.used + 1
                    else:
                        index = int(np.argmin(self.age))
                        self.operations["evictions"] += 1
                self.keys[index], self.values[index], self.age[index] = key, value, self.clock
                if self.kind == "ridge":
                    keys = self.keys[:self.used]
                    self.coefficients = np.linalg.solve(
                        keys @ keys.T + self.config["penalty"] * np.eye(self.used),
                        self.values[:self.used])
                    self.operations["ridge_solves"] += 1
            return None
        if kind != "QUERY":
            raise ValueError("Unknown public event")
        self.operations["queries"] += 1
        if self.kind == "gated_delta":
            scores = key @ self.state
        elif self.kind == "cosine":
            scores = self.values[int(np.argmax(self.keys[:self.used] @ key))]
        else:
            keys = self.keys[:self.used]
            scores = (key @ keys.T) @ self.coefficients
        return int(np.argmax(scores))


def predict(public, weight, kind, config):
    started = time.process_time()
    model = Memory(weight, kind, config)
    answers = [answer for event in public if (answer := model.step(event)) is not None]
    state_bytes = (model.state.nbytes if kind == "gated_delta" else
                   model.keys.nbytes + model.values.nbytes + model.age.nbytes + model.coefficients.nbytes)
    return dict(answers=answers, operations=model.operations, state_array_bytes=state_bytes,
                encoder_array_bytes=model.weight.nbytes, cpu_seconds=time.process_time() - started)
