"""Bounded resident features and exact block recursive ridge for a frozen encoder."""
from collections import OrderedDict
import hashlib
import json

import numpy as np


class FeatureCache:
    """An instance belongs to one immutable encoder/source identity; labels are not keys."""

    def __init__(self, encoder, identity, capacity=2048):
        if not identity or capacity < 1:
            raise ValueError("A frozen identity and positive capacity are required")
        self.encoder, self.identity, self.capacity = encoder, identity, capacity
        self.entries = OrderedDict()
        self.hits = self.misses = 0

    def features(self, rows):
        if not rows or len(rows) > self.capacity:
            raise ValueError("Feature request exceeds the bounded cache")
        keys, missing = [], OrderedDict()
        for row in rows:
            value = {"encoder": self.identity, "query": row["query"],
                     "candidates": row["candidates"]}
            key = hashlib.sha256(json.dumps(value, sort_keys=True,
                                           ensure_ascii=False).encode()).hexdigest()
            keys.append(key)
            if key not in self.entries:
                missing[key] = row
        self.hits += len(rows) - len(missing)
        self.misses += len(missing)
        if missing:
            arrays = self.encoder.features(list(missing.values()))
            for i, key in enumerate(missing):
                self.entries[key] = tuple(np.array(a[i], copy=True) for a in arrays)
        result = tuple(np.stack([self.entries[key][i] for key in keys]) for i in range(3))
        for key in keys:
            self.entries.move_to_end(key)
        while len(self.entries) > self.capacity:
            self.entries.popitem(last=False)
        return result


def checked(x, y):
    x, y = np.array(x, dtype=np.float64, copy=True), np.array(y, dtype=np.float64, copy=True)
    if x.ndim != 2 or y.shape != (len(x),) or not len(x) or not x.shape[1]:
        raise ValueError("Expected nonempty matrix and one target per row")
    if not np.isfinite(x).all() or not np.isfinite(y).all():
        raise ValueError("Nonfinite regression data")
    return x, y


def direct(x, y, regularizer=0.2):
    gram = x @ x.T + regularizer * np.eye(len(x))
    return x.T @ np.linalg.solve(gram, y)


class RecursiveRidge:
    """Bounded kernel RLS via a Schur complement, with no forgetting or changed loss."""

    def __init__(self, x, y, regularizer=0.2, max_rows=1024):
        x, y = checked(x, y)
        if not np.isfinite(regularizer) or regularizer <= 0 or len(x) > max_rows:
            raise ValueError("Positive regularizer and bounded row count required")
        self.regularizer, self.max_rows = regularizer, max_rows
        self.x, self.y = x, y
        self.inverse = np.linalg.solve(x @ x.T + regularizer * np.eye(len(x)), np.eye(len(x)))
        self.weights = x.T @ (self.inverse @ y)

    def append(self, x, y):
        x, y = checked(x, y)
        if x.shape[1] != self.x.shape[1] or len(self.x) + len(x) > self.max_rows:
            raise ValueError("Feature identity/dimension or row bound changed")
        cross = self.x @ x.T
        projected = self.inverse @ cross
        schur = x @ x.T + self.regularizer * np.eye(len(x)) - cross.T @ projected
        small_inverse = np.linalg.solve(schur, np.eye(len(x)))
        correction = small_inverse @ (y - x @ self.weights)
        weights = self.weights + (x.T - self.x.T @ projected) @ correction
        off = -projected @ small_inverse
        inverse = np.block([[self.inverse - off @ projected.T, off],
                            [off.T, small_inverse]])
        if not np.isfinite(weights).all() or not np.isfinite(inverse).all():
            raise ValueError("Unusable update; previous state retained")
        self.x, self.y = np.concatenate((self.x, x)), np.concatenate((self.y, y))
        self.inverse = (inverse + inverse.T) / 2
        self.weights = weights
        return self.weights.copy()
