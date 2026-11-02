"""Finite ordinary transition-mixture reference; no analytic neural-core claim."""

import numpy as np

from experiments.hcsn_unknown_generator_r18_20261101.posterior import (
    Posterior, decode, infer as uniform_infer,
)


def fit(groups):
    particles = []
    for prefixes in groups:
        initial, transition, distinct = np.ones(4) * .5, np.ones((4, 4)) * .5, []
        for prefix in prefixes:
            writes = [decode(row) for row in prefix if row[12] == 1]
            if len(writes) != 6:
                raise ValueError("Six public training WRITEs required")
            values = [row[2] for row in writes]
            initial[values[0]] += 1
            np.add.at(transition, (values[:-1], values[1:]), 1)
            distinct.append(writes[4][1] != writes[5][1])
        particles.append(dict(initial=(initial / initial.sum()).tolist(),
            transition=(transition / transition.sum(1, keepdims=True)).tolist(),
            q=float(np.clip(4 * (sum(distinct) + .5) / (len(distinct) + 1) - 3, 0, 1))))
    return particles


def infer(prefix, observed, particles):
    base = uniform_infer(prefix, observed, [dict(pi=[.25] * 4, rho=0., q=0.)])
    known = {i:decode(row) for i, row in enumerate(prefix) if observed[i] and row[12] == 1}
    rows, length = len(base.weights), len(prefix)
    key = np.full((rows, length), -1, dtype=int)
    value = np.full((rows, length), -1, dtype=int)
    for index, (_, k, v) in known.items():
        key[:, index], value[:, index] = k, v
    for col, index in enumerate(base.missing):
        code = base.hidden[:, col]
        key[:, index] = np.where(code >= 0, code // 4, -1)
        value[:, index] = np.where(code >= 0, code % 4, -1)
    order = np.argsort(key < 0, axis=1, kind="stable")[:, :6]
    keys = np.take_along_axis(key, order, axis=1)
    values = np.take_along_axis(value, order, axis=1)
    weight, denominator = np.zeros(rows), np.zeros(rows)
    for particle in particles:
        initial, matrix, q = np.array(particle["initial"]), np.array(particle["transition"]), particle["q"]
        if (initial.shape != (4,) or matrix.shape != (4, 4) or np.any(initial <= 0)
                or np.any(matrix <= 0) or not np.isclose(initial.sum(), 1)
                or not np.allclose(matrix.sum(1), 1) or not 0 <= q <= 1):
            raise ValueError("Invalid full-support transition particle")
        key_factor = (1 - q) / 16 + q / 12 * (keys[:, 4] != keys[:, 5])
        probability = initial[values[:, 0]].copy()
        for step in range(1, 6):
            probability *= matrix[values[:, step - 1], values[:, step]]
        weight += key_factor * probability / len(particles)
        denominator += key_factor / len(particles)
    total = weight.sum()
    if total <= 0 or not np.isfinite(total):
        raise ValueError("Zero or invalid transition-mixture likelihood")
    missing_writes = 6 - len(known)
    surprise = -np.log(total / (denominator.sum() / 4 ** missing_writes)) / max(1, len(known))
    return Posterior(base.final, base.hidden, weight / total, base.missing, float(surprise))
