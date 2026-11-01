"""Joint finite posterior under a learned ordinary Markov-generator mixture."""

from dataclasses import dataclass
from itertools import combinations, permutations, product

import numpy as np


def decode(event):
    x = np.asarray(event)
    if (x.shape != (24,) or not np.isin(x, [0, 1]).all() or x[:4].sum() != 1
            or x[4:12].sum() != 1 or x[12:16].sum() != 1):
        raise ValueError("Invalid raw key/value token")
    kind, key, value = int(x[12:16].argmax()), int(x[:4].argmax()), int(x[4:12].argmax())
    expected = np.zeros(24, dtype=np.int8)
    expected[[key, 4 + value, 12 + kind, 16]] = 1
    if kind not in (0, 2) or value >= 4 or not np.array_equal(expected, x):
        raise ValueError("Raw token is outside the declared four-value schema")
    return kind, key, value


def query_key(bridges, query):
    mapping = {}
    for row in np.asarray(bridges):
        if (row.shape != (24,) or not np.isin(row, [0, 1]).all() or row[:4].sum() != 1
                or row[19:23].sum() != 1):
            raise ValueError("Expected a complete raw alias bridge")
        key, alias = int(row[:4].argmax()), int(row[19:23].argmax())
        expected = np.zeros(24, dtype=np.int8)
        expected[[key, 15, 16, 17, 19 + alias]] = 1
        if not np.array_equal(row, expected) or alias in mapping:
            raise ValueError("Invalid or repeated alias bridge")
        mapping[alias] = key
    q = np.asarray(query)
    if sorted(mapping) != list(range(4)) or sorted(mapping.values()) != list(range(4)):
        raise ValueError("Incomplete alias permutation")
    if q.shape != (24,) or q[19:23].sum() != 1:
        raise ValueError("Invalid raw alias query")
    alias = int(q[19:23].argmax())
    expected = np.zeros(24, dtype=np.int8)
    expected[[13, 17, 19 + alias]] = 1
    if not np.array_equal(q, expected):
        raise ValueError("Query contains unexpected fields")
    return mapping[alias]


@dataclass(frozen=True)
class Posterior:
    final: np.ndarray
    hidden: np.ndarray
    weights: np.ndarray
    missing: tuple
    surprise: float
    receipts: tuple = ()

    def probability(self, key):
        return np.bincount(self.final[:, key], weights=self.weights, minlength=4)

    def acquire(self, index, event):
        kind, key, value = decode(event)
        previous = dict(self.receipts)
        if index in previous:
            if previous[index] != (kind, key, value):
                raise ValueError("Conflicting indexed acquisition replay")
            return self
        code = 4 * key + value if kind == 0 else -1
        keep = self.hidden[:, self.missing.index(index)] == code
        mass = self.weights[keep].sum()
        if mass <= 0:
            raise ValueError("Acquired event has zero model likelihood")
        return Posterior(self.final[keep], self.hidden[keep], self.weights[keep] / mass,
                         self.missing, self.surprise, self.receipts + ((index, (kind, key, value)),))

    def choose(self, key, price, threshold):
        p = self.probability(key)
        confidence = float(p.max())
        stop = 2 * confidence - 1 if confidence >= threshold else 0.
        best, best_value = None, stop
        for column, index in enumerate(self.missing):
            expected = -price
            for code in np.unique(self.hidden[:, column]):
                keep = self.hidden[:, column] == code
                mass = self.weights[keep].sum()
                branch = np.bincount(self.final[keep, key], weights=self.weights[keep], minlength=4) / mass
                maximum = float(branch.max())
                expected += mass * (2 * maximum - 1 if maximum >= threshold else 0.)
            if expected > best_value + 1e-12:
                best, best_value = index, expected
        return best, p


def infer(prefix, observed, particles):
    x, mask = np.asarray(prefix), np.asarray(observed)
    if (x.ndim != 2 or x.shape[1] != 24 or mask.shape != (len(x),) or mask.dtype != bool
            or len(x) not in (14, 30) or not np.isfinite(x).all() or np.any(x[~mask])):
        raise ValueError("Invalid finite raw prefix or observation mask")
    known = {int(i):decode(x[i]) for i in np.flatnonzero(mask)}
    known_writes = {i:event for i, event in known.items() if event[0] == 0}
    missing = tuple(map(int, np.flatnonzero(~mask)))
    if len(missing) > 4:
        raise ValueError("More than four missing positions exceeds the bounded profile")
    needed = 6 - len(known_writes)
    if needed < 0 or needed > len(missing):
        raise ValueError("Public event kinds contradict six-WRITE schedule")
    sequence_values, sequence_keys, finals, hidden = [], [], [], []
    for absent_writes in combinations(missing, needed):
        slots = sorted(tuple(known_writes) + absent_writes)
        first, later = slots[:4], slots[4:]
        known_first = {i:known_writes[i][1] for i in first if i in known_writes}
        if len(set(known_first.values())) != len(known_first):
            continue
        first_unknown = [i for i in first if i not in known_writes]
        later_unknown = [i for i in later if i not in known_writes]
        for initial_keys in permutations(sorted(set(range(4)) - set(known_first.values()))):
            for update_keys in product(range(4), repeat=len(later_unknown)):
                keymap = {i:event[1] for i, event in known_writes.items()}
                keymap.update(zip(first_unknown + later_unknown, initial_keys + update_keys, strict=True))
                for values in product(range(4), repeat=needed):
                    valuemap = {i:event[2] for i, event in known_writes.items()}
                    valuemap.update(zip(absent_writes, values, strict=True))
                    ks, vs = [keymap[i] for i in slots], [valuemap[i] for i in slots]
                    final = np.zeros(4, dtype=np.int8)
                    for key, value in zip(ks, vs, strict=True):
                        final[key] = value
                    sequence_keys.append(ks)
                    sequence_values.append(vs)
                    finals.append(final)
                    hidden.append([keymap[i] * 4 + valuemap[i] if i in keymap else -1 for i in missing])
    if not finals:
        raise ValueError("Raw prefix has zero model support")
    values, keys = np.array(sequence_values), np.array(sequence_keys)
    weight, key_weight = np.zeros(len(values)), np.zeros(len(values))
    for particle in particles:
        pi, rho, q = np.array(particle["pi"]), particle["rho"], particle["q"]
        key_factor = (1 - q) / 16 + q / 12 * (keys[:, 4] != keys[:, 5])
        value_factor = pi[values[:, 0]]
        for step in range(1, 6):
            value_factor *= rho * (values[:, step] == values[:, step - 1]) + (1 - rho) * pi[values[:, step]]
        weight += key_factor * value_factor / len(particles)
        key_weight += key_factor / len(particles)
    total = float(weight.sum())
    denominator = key_weight.sum() / 4 ** needed
    if total <= 0 or not np.isfinite(total):
        raise ValueError("Zero or invalid fitted-model likelihood")
    surprise = -np.log(total / denominator) / max(1, len(known_writes))
    return Posterior(np.array(finals), np.array(hidden, dtype=np.int16).reshape(len(finals), len(missing)),
                     weight / total, missing, float(surprise))
