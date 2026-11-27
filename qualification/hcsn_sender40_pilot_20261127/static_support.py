"""Budget, exact F32 scope and frozen-key mathematics; no model import."""
import contextlib
from fractions import Fraction
import hashlib
import json
import math
import os
from pathlib import Path
import time

import numpy as np


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def write_json(path, value):
    path = Path(path)
    with path.open("x") as stream:
        json.dump(value, stream, indent=2, sort_keys=True, allow_nan=False)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())


def write_bytes(path, value):
    with Path(path).open("xb") as stream:
        stream.write(value)
        stream.flush()
        os.fsync(stream.fileno())


class Ledger:
    def __init__(self, output, cold_start):
        self.path = Path(output) / "calls.jsonl"
        self.path.touch(exist_ok=False)
        self.start = cold_start
        self.counts = dict(forwards=0, body_ticks=0, paired_queries=0, backwards=0,
                           optimizer_steps=0, analytic_solves=0, trace_linear_replays=0)
        self.event("opened")

    def event(self, kind, **values):
        record = dict(kind=kind, counts=dict(self.counts), cpu_seconds=time.process_time(),
                      wall_seconds=time.monotonic() - self.start, **values)
        with self.path.open("a") as stream:
            stream.write(json.dumps(record, sort_keys=True, allow_nan=False) + "\n")
            stream.flush()
            os.fsync(stream.fileno())

    def charge(self, name, amount=1):
        caps = dict(forwards=33, body_ticks=198, paired_queries=1114, backwards=17,
                    optimizer_steps=16, analytic_solves=2, trace_linear_replays=6)
        if name not in caps or type(amount) is not int or amount < 0:
            raise ValueError("unknown counter or invalid nonnegative charge")
        if self.counts[name] + amount > caps[name]:
            raise RuntimeError("frozen budget exceeded: " + name)
        self.counts[name] += amount

    def check_time(self):
        if time.process_time() > 180 or time.monotonic() - self.start > 300:
            raise RuntimeError("overall CPU/wall budget exhausted")

    @contextlib.contextmanager
    def forward(self, label, queries):
        self.check_time()
        self.charge("forwards")
        self.charge("paired_queries", queries)
        self.event("forward_started", label=label, queries=queries)
        start = time.monotonic()
        try:
            yield
            if time.monotonic() - start > 20:
                raise RuntimeError("completed forward exceeded fixed 20-second return gate")
            self.check_time()
        except BaseException as error:
            self.event("forward_failed", label=label, error=repr(error))
            raise
        self.event("forward_completed", label=label, elapsed=time.monotonic() - start)

    def backward(self, loss):
        self.check_time()
        self.charge("backwards")
        self.event("backward_started")
        start = time.monotonic()
        try:
            loss.backward()
            if time.monotonic() - start > 20:
                raise RuntimeError("completed backward exceeded fixed 20-second return gate")
            self.check_time()
        except BaseException as error:
            self.event("backward_failed", error=repr(error))
            raise
        self.event("backward_completed", elapsed=time.monotonic() - start)


def exact_norm2(values, parent):
    values, parent = np.asarray(values, dtype="<f4"), np.asarray(parent, dtype="<f4")
    if (values.shape != (40,) or parent.shape != (40,) or
            not np.isfinite(values).all() or not np.isfinite(parent).all()):
        raise ValueError("finite 40-coordinate F32 vectors required")
    return sum((Fraction(float(a)) - Fraction(float(b))) ** 2 for a, b in zip(values, parent))


def realized(parent, delta, cap_squared=Fraction(1)):
    """Compile once, with at most 16 rounding-only inward corrections; no scores."""
    parent = np.asarray(parent, dtype="<f4")
    delta = np.asarray(delta, dtype=np.float64)
    if delta.shape != (40,) or not np.isfinite(delta).all() or cap_squared < 0:
        raise ValueError("invalid parameter proposal")
    norm = float(np.linalg.norm(delta))
    cap = math.sqrt(float(cap_squared))
    scale = min(1., cap * (1. - 2. ** -16) / norm) if norm else 1.
    for attempt in range(17):
        candidate = (parent.astype(np.float64) + scale * delta).astype("<f4")
        norm2 = exact_norm2(candidate, parent)
        if norm2 <= cap_squared:
            return candidate, dict(norm2_numerator=str(norm2.numerator),
                                   norm2_denominator=str(norm2.denominator),
                                   norm=math.sqrt(float(norm2)), inward_steps=attempt,
                                   proposal_scale=scale)
        scale *= 1. - 2. ** -16
    raise ValueError("represented F32 radius cannot be compiled within fixed corrections")


def metrics(scores, labels):
    values = np.asarray(scores, dtype=np.float32)
    labels = np.asarray(labels, dtype=np.int64)
    if (values.shape != (len(labels), 2) or labels.ndim != 1 or not len(labels) or
            not np.isin(labels, (0, 1)).all() or not np.isfinite(values).all()):
        raise ValueError("finite binary-choice scores required")
    double = values.astype(np.float64)
    shifted = double - double.max(axis=1, keepdims=True)
    probs = np.exp(shifted)
    probs /= probs.sum(axis=1, keepdims=True)
    ce = np.log(np.exp(shifted).sum(axis=1)) - shifted[np.arange(len(labels)), labels]
    return dict(correct=int((values.argmax(axis=1) == labels).sum()), n=len(labels),
                accuracy=float((values.argmax(axis=1) == labels).mean()),
                brier=float(np.square(probs[:, 1] - labels).mean()), ce=float(ce.mean()))


def trust_region(keys, targets, protected_keys, radius=1.):
    keys, targets, protected_keys = (np.asarray(value, dtype=np.float64)
                                     for value in (keys, targets, protected_keys))
    if (keys.ndim != 2 or keys.shape[1] != 10 or targets.shape != (len(keys), 4) or
            protected_keys.ndim != 2 or protected_keys.shape[1] != 10 or
            not all(np.isfinite(value).all() for value in (keys, targets, protected_keys)) or
            not math.isfinite(radius) or radius <= 0):
        raise ValueError("finite frozen-key quadratic dimensions and positive radius required")
    if not len(keys) or not len(protected_keys):
        raise ValueError("both failed and protected training keys are required")
    gram = keys.T @ keys / len(keys) + .25 * protected_keys.T @ protected_keys / len(protected_keys)
    gram += .02 * np.eye(10)
    rhs = keys.T @ targets / len(keys)
    eig, basis = np.linalg.eigh(gram)
    if not np.isfinite(eig).all() or eig.min() <= 0:
        raise ValueError("surrogate quadratic is not positive definite")
    projected = basis.T @ rhs
    solution = basis @ (projected / eig[:, None])
    multiplier = 0.
    if np.linalg.norm(solution) > radius:
        lower, upper = 0., max(1., float(np.linalg.norm(rhs)) / radius)
        for _ in range(128):
            middle = (lower + upper) / 2
            candidate = basis @ (projected / (eig[:, None] + middle))
            if np.linalg.norm(candidate) > radius:
                lower = middle
            else:
                upper = middle
        multiplier = upper
        solution = basis @ (projected / (eig[:, None] + multiplier))
    residual = (gram + multiplier * np.eye(10)) @ solution - rhs
    return solution, dict(multiplier=multiplier, kkt_max_abs=float(np.abs(residual).max()),
                          surrogate_norm=float(np.linalg.norm(solution)), iterations=128 if multiplier else 0)


def flat_from_matrix(matrix):
    return np.concatenate((matrix[:9].T.reshape(-1), matrix[9]))


def role_ids(labels):
    labels = np.asarray(labels)
    if labels.ndim != 1 or not np.isin(labels, (0, 1)).all():
        raise ValueError("semantic roles require binary target positions")
    return (np.arange(2)[None, :] == labels[:, None]).reshape(-1).astype("int64")


def eligible(candidate, parent, labels):
    before = parent.argmax(axis=1) == labels
    after = candidate.argmax(axis=1) == labels
    return bool(not (before & ~after).any() and
                metrics(candidate, labels)["brier"] <= metrics(parent, labels)["brier"] + .01)


def choose(rows):
    """Rows already pass protection. KEEP wins a full tie; then fixed declaration order."""
    return min(rows, key=lambda r: (-r["dev"]["correct"], r["dev"]["brier"], r["norm"],
                                    0 if r["name"] == "KEEP" else 1, r["declaration_index"]))
