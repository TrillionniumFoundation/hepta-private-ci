"""Ordinary finite sequence likelihoods, fitted only from public WRITE streams."""

import numpy as np
from scipy.special import gammaln

NAMES = ("transition_particles", "exchangeable_dirichlet", "row_dirichlet")


def raw_likelihood(values, model):
    """Return per-class sequence weights for equal/repeated final update keys."""
    values = np.asarray(values, dtype=int)
    q = model["mean_q"]
    key_factor = np.array([(1 - q) / 16, (1 - q) / 16 + q / 12])
    result = np.zeros((len(values), 3, 2))
    for particle in model["particles"]:
        pi, matrix, pq = np.array(particle["pi"]), np.array(particle["transition"]), particle["q"]
        probability = pi[values[:, 0]].copy()
        for step in range(1, 6):
            probability *= matrix[values[:, step - 1], values[:, step]]
        factor = np.array([(1 - pq) / 16, (1 - pq) / 16 + pq / 12])
        result[:, 0] += probability[:, None] * factor[None] / len(model["particles"])
    counts = np.stack([(values == value).sum(1) for value in range(4)], 1)
    transitions = np.zeros((len(values), 4, 4))
    for step in range(1, 6):
        transitions[np.arange(len(values)), values[:, step - 1], values[:, step]] += 1
    start = np.array(model["start"])[values[:, 0]]
    for concentration in (.1, .5, 2., 8.):
        alpha = np.array(model["pooled"]) * concentration
        log_iid = gammaln(alpha.sum()) - gammaln(alpha.sum() + 6)
        log_iid += (gammaln(counts + alpha[None]) - gammaln(alpha[None])).sum(1)
        result[:, 1] += np.exp(log_iid)[:, None] * key_factor[None] / 4
        alpha = np.array(model["pooled_transition"]) * concentration
        log_row = (gammaln(alpha.sum(1))[None] - gammaln(alpha.sum(1)[None] + transitions.sum(2))).sum(1)
        log_row += (gammaln(transitions + alpha[None]) - gammaln(alpha[None])).sum((1, 2))
        result[:, 2] += (start * np.exp(log_row))[:, None] * key_factor[None] / 4
    return result


def fit_base(groups):
    particles, pooled, initial, transition_total, qs = [], np.zeros(4), np.zeros(4), np.zeros((4, 4)), []
    for group in groups:
        first, transition, distinct = np.zeros(4), np.zeros((4, 4)), []
        for prefix in group:
            writes = prefix[prefix[:, 12] == 1]
            values, keys = writes[:, 4:8].argmax(1), writes[:, :4].argmax(1)
            first[values[0]] += 1
            pooled += np.bincount(values, minlength=4)
            for before, after in zip(values, values[1:]):
                transition[before, after] += 1
            distinct.append(keys[-1] != keys[-2])
        pi = (first + .5) / (first.sum() + 2)
        matrix = (transition + .2) / (transition.sum(1)[:, None] + .8)
        q = float(np.clip(4 * (sum(distinct) + .5) / (len(distinct) + 1) - 3, 0, 1))
        particles.append(dict(pi=pi.tolist(), transition=matrix.tolist(), q=q))
        initial += first
        transition_total += transition
        qs.append(q)
    model = dict(particles=particles, mean_q=float(np.mean(qs)),
                 pooled=((pooled + .5) / (pooled.sum() + 2)).tolist(),
                 start=((initial + .5) / (initial.sum() + 2)).tolist(),
                 pooled_transition=((transition_total + .2) / (transition_total.sum(1)[:, None] + .8)).tolist())
    return model


def likelihood(values, model):
    if "sequence_table" not in model:
        return raw_likelihood(values, model)
    code = np.asarray(values, dtype=int) @ np.array([1024, 256, 64, 16, 4, 1])
    return model["sequence_table"][code]


def tempered_table(model, beta):
    from itertools import product
    sequences = np.array(list(product(range(4), repeat=6)))
    raw = raw_likelihood(sequences, model)
    key_mass = raw.sum(0, keepdims=True)
    conditional = np.divide(raw, key_mass, out=np.zeros_like(raw), where=key_mass > 0)
    tempered = conditional ** beta
    normalizer = tempered.sum(0, keepdims=True)
    tempered = np.divide(tempered, normalizer, out=np.zeros_like(tempered), where=normalizer > 0)
    return tempered * key_mass
