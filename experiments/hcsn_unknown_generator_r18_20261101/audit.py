"""Independent raw-token completion reference for frozen development cases."""

from itertools import product
import json
from pathlib import Path
import time

import numpy as np


def event(kind, key, value):
    result = np.zeros(24, dtype=np.int8)
    result[[key, 4 + value, 12 + kind, 16]] = 1
    return result


def reference(prefix, mask, particles):
    missing = list(map(int, np.flatnonzero(~mask)))
    worlds, hidden, weights = [], [], []
    observed = []
    for raw in prefix:
        observed.append((int(raw[12:16].argmax()), int(raw[:4].argmax()), int(raw[4:8].argmax())))
    # A missing distractor is a single analytically marginalized possibility;
    # every WRITE key/value is enumerated as a raw event independently.
    alphabet = [(2, 0, 0)] + [(0, k, v) for k in range(4) for v in range(4)]
    for absent in product(alphabet, repeat=len(missing)):
        completed = list(observed)
        for index, triple in zip(missing, absent, strict=True):
            completed[index] = triple
        writes = [triple for triple in completed if triple[0] == 0]
        if len(writes) != 6 or sorted(row[1] for row in writes[:4]) != list(range(4)):
            continue
        final, weight = [0] * 4, 0.
        for _, key, value in writes:
            final[key] = value
        for particle in particles:
            pi, rho, q = particle["pi"], particle["rho"], particle["q"]
            probability = pi[writes[0][2]]
            for previous, current in zip(writes, writes[1:]):
                probability *= rho * (previous[2] == current[2]) + (1 - rho) * pi[current[2]]
            probability *= (1 - q) / 16 + (q / 12 if writes[4][1] != writes[5][1] else 0)
            weight += probability / len(particles)
        worlds.append(final)
        hidden.append([4 * key + value if kind == 0 else -1 for kind, key, value in absent])
        weights.append(weight)
    weights = np.array(weights)
    return np.array(worlds), np.array(hidden), weights / weights.sum()


def run():
    from .posterior import infer, query_key
    started, checks, largest = time.process_time(), 0, 0.
    particles = [dict(pi=[.1, .2, .3, .4], rho=0., q=.2),
                 dict(pi=[.4, .3, .2, .1], rho=.8, q=.7)]
    full = np.stack([event(2, 0, 3) for _ in range(14)])
    for index, key, value in zip([1, 3, 5, 8, 10, 12], [0, 1, 2, 3, 1, 3], [0, 1, 1, 2, 1, 2], strict=True):
        full[index] = event(0, key, value)
    for missing in ([3, 9], [2, 3, 12], [2, 3, 9, 12]):
        mask, prefix = np.ones(14, dtype=bool), full.copy()
        mask[missing] = False
        prefix[~mask] = 0
        actual = infer(prefix, mask, particles)
        worlds, hidden, weights = reference(prefix, mask, particles)
        for key in range(4):
            expected = np.bincount(worlds[:, key], weights=weights, minlength=4)
            largest = max(largest, float(np.max(abs(actual.probability(key) - expected))))
            checks += 4
            for column, index in enumerate(missing):
                for code in np.unique(hidden[:, column]):
                    keep = hidden[:, column] == code
                    expected = np.bincount(worlds[keep, key], weights=weights[keep], minlength=4) / weights[keep].sum()
                    raw = event(2, 1, 3) if code == -1 else event(0, code // 4, code % 4)
                    acquired = actual.acquire(index, raw)
                    largest = max(largest, float(np.max(abs(acquired.probability(key) - expected))))
                    assert acquired.acquire(index, raw) is acquired
                    conflicting = event(2, 2, 3) if code == -1 else event(0, code // 4, (code + 1) % 4)
                    try:
                        acquired.acquire(index, conflicting)
                    except ValueError:
                        checks += 1
                    else:
                        raise AssertionError("Conflicting acquired-token replay accepted")
                    checks += 4
            for threshold in [.65, .75, .85, .95]:
                stop = 2 * expected.max() - 1 if expected.max() >= threshold else 0
                # Use the original reference marginal for STOP, not last READ.
                marginal = np.bincount(worlds[:, key], weights=weights, minlength=4)
                stop = 2 * marginal.max() - 1 if marginal.max() >= threshold else 0
                chosen, best = None, stop
                for column, index in enumerate(missing):
                    value = -.12
                    for code in np.unique(hidden[:, column]):
                        keep = hidden[:, column] == code
                        mass = weights[keep].sum()
                        branch = np.bincount(worlds[keep, key], weights=weights[keep], minlength=4) / mass
                        value += mass * (2 * branch.max() - 1 if branch.max() >= threshold else 0)
                    if value > best + 1e-12:
                        chosen, best = index, value
                assert actual.choose(key, .12, threshold)[0] == chosen
                checks += 1
    bridges = []
    for alias, key in enumerate([2, 0, 3, 1]):
        bridge = np.zeros(24, dtype=np.int8)
        bridge[[key, 15, 16, 17, 19 + alias]] = 1
        bridges.append(bridge)
    for alias, key in enumerate([2, 0, 3, 1]):
        query = np.zeros(24, dtype=np.int8)
        query[[13, 17, 19 + alias]] = 1
        assert query_key(bridges, query) == key
        checks += 1
    assert largest < 2e-12
    result = dict(schema="hcsn.r18.independent-development-audit.v1", checks=checks,
                  maximum_absolute_error=largest, cpu_seconds=time.process_time() - started,
                  scope="Independent full missing raw-event completion for2/3/4missing positions; posterior,READconditionals,replay,decision and executed alias mapping")
    with Path(__file__).with_name("DEVELOPMENT_AUDIT.json").open("x") as stream:
        json.dump(result, stream, sort_keys=True, indent=2)
        stream.write("\n")
    print(json.dumps(result))


if __name__ == "__main__":
    run()
