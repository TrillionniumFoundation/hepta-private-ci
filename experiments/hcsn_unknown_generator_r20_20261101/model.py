"""Ordinary first-order versus context-and-label-orbit finite content references."""

from itertools import permutations, product

import numpy as np

from experiments.hcsn_unknown_generator_r18_20261101.posterior import Posterior, decode, infer as uniform_infer

SEQUENCES = np.array(list(product(range(4), repeat=6)), dtype=int)


def _parameters(sequences):
    initial, first, second = np.ones(4) * .5, np.ones((4, 4)) * .5, np.zeros((4, 4, 4))
    np.add.at(initial, sequences[:, 0], 1)
    for step in range(1, 6):
        np.add.at(first, (sequences[:, step - 1], sequences[:, step]), 1)
    first /= first.sum(1, keepdims=True)
    for step in range(2, 6):
        np.add.at(second, (sequences[:, step - 2], sequences[:, step - 1], sequences[:, step]), 1)
    second += first[None, :, :]
    second /= second.sum(2, keepdims=True)
    return initial / initial.sum(), first, second


def _likelihood(sequences, initial, first, second):
    p1, p2 = initial[sequences[:, 0]].copy(), initial[sequences[:, 0]].copy()
    for step in range(1, 6):
        p1 *= first[sequences[:, step - 1], sequences[:, step]]
        p2 *= (first[sequences[:, 0], sequences[:, 1]] if step == 1
               else second[sequences[:, step - 2], sequences[:, step - 1], sequences[:, step]])
    return p1, p2


def fit(groups):
    models = {name:dict(same=np.zeros(4096), distinct=np.zeros(4096))
              for name in ("context_orbit", "orbit_first_order", "first_order")}
    diagnostics = []
    for prefixes in groups:
        writes = [[decode(row) for row in prefix if row[12] == 1] for prefix in prefixes]
        if any(len(sequence) != 6 for sequence in writes):
            raise ValueError("Six complete public training WRITEs required")
        sequences = np.array([[event[2] for event in sequence] for sequence in writes])
        split = 3 * len(sequences) // 4
        if split < 2 or split == len(sequences):
            raise ValueError("Independent public within-group selection streams required")
        trial = _parameters(sequences[:split])
        p1, p2 = _likelihood(sequences[split:], *trial)
        difference = float(np.log(p2).sum() - np.log(p1).sum())
        context_weight = float(1 / (1 + np.exp(-np.clip(difference, -30, 30))))
        initial, first, second = _parameters(sequences)
        distinct = sum(sequence[-2][1] != sequence[-1][1] for sequence in writes)
        q = float(np.clip(4 * (distinct + .5) / (len(writes) + 1) - 3, 0, 1))
        first_probability, _ = _likelihood(SEQUENCES, initial, first, second)
        context_probability, orbit_first_probability = np.zeros(4096), np.zeros(4096)
        # All24 symbol permutations are a declared inductive assumption, not new training information.
        for permutation in permutations(range(4)):
            relabelled = np.array(permutation)[SEQUENCES]
            a, b = _likelihood(relabelled, initial, first, second)
            context_probability += ((1 - context_weight) * a + context_weight * b) / 24
            orbit_first_probability += a / 24
        for name, probability in (("context_orbit", context_probability),
                ("orbit_first_order", orbit_first_probability), ("first_order", first_probability)):
            models[name]["same"] += probability * (1 - q) / 16 / len(groups)
            models[name]["distinct"] += probability * ((1 - q) / 16 + q / 12) / len(groups)
        diagnostics.append(dict(initial=initial.tolist(), first=first.tolist(), second=second.tolist(),
            q=q, context_weight=context_weight, selection_log_likelihood_difference=difference))
    for model in models.values():
        if np.any(model["same"] <= 0) or np.any(model["distinct"] <= 0):
            raise ValueError("Compiled law lost full support")
        if not np.isclose(4 * model["same"].sum() + 12 * model["distinct"].sum(), 1., atol=1e-12):
            raise ValueError("Compiled six-WRITE law is not normalized")
    return {n:{k:v.tolist() for k, v in m.items()} for n, m in models.items()}, diagnostics


def infer(prefix, observed, model):
    base = uniform_infer(prefix, observed, [dict(pi=[.25] * 4, rho=0., q=0.)])
    known = {i:decode(row) for i, row in enumerate(prefix) if observed[i] and row[12] == 1}
    count, length = len(base.weights), len(prefix)
    keys, values = np.full((count, length), -1, dtype=int), np.full((count, length), -1, dtype=int)
    for index, (_, key, value) in known.items():
        keys[:, index], values[:, index] = key, value
    for column, index in enumerate(base.missing):
        code = base.hidden[:, column]
        keys[:, index], values[:, index] = np.where(code >= 0, code // 4, -1), np.where(code >= 0, code % 4, -1)
    order = np.argsort(keys < 0, axis=1, kind="stable")[:, :6]
    keys, values = np.take_along_axis(keys, order, 1), np.take_along_axis(values, order, 1)
    same, distinct = np.asarray(model["same"]), np.asarray(model["distinct"])
    if (same.shape != (4096,) or distinct.shape != (4096,) or not np.isfinite(same).all()
            or not np.isfinite(distinct).all() or np.any(same <= 0) or np.any(distinct <= 0)
            or not np.isclose(4 * same.sum() + 12 * distinct.sum(), 1., atol=1e-12)):
        raise ValueError("Invalid compiled law")
    indices = values @ np.array([1024, 256, 64, 16, 4, 1])
    weights = np.where(keys[:, 4] != keys[:, 5], distinct[indices], same[indices])
    total = float(weights.sum())
    if total <= 0 or not np.isfinite(total):
        raise ValueError("Impossible public observation under compiled law")
    # Uniform structural enumeration integrates every legal content assignment for the denominator.
    key_normalizer = np.where(keys[:, 4] != keys[:, 5], distinct.sum(), same.sum()).sum()
    surprise = -np.log(total / (key_normalizer / 4 ** (6 - len(known)))) / max(1, len(known))
    return Posterior(base.final, base.hidden, weights / total, base.missing, float(surprise))
