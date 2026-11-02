"""Declared Markov training population and two held-out higher-order families."""

import numpy as np

from experiments.hcsn_unknown_generator_r18_20261101.world import token

SEED = 19011179
SPLITS = {"train": 11, "ood": 23, "calibrate": 37, "confirm": 53, "reverse": 71, "lag2": 89}


def sample(split, generator, index, complete=False):
    parameter_rng = np.random.default_rng(np.random.SeedSequence([SEED, SPLITS[split], generator, 991]))
    pi = parameter_rng.dirichlet(np.full(4, .7))
    rho, q = parameter_rng.uniform(.6, .98), parameter_rng.uniform()
    family = int(parameter_rng.integers(3)) if split not in ("reverse", "lag2") else split
    rng = np.random.default_rng(np.random.SeedSequence([SEED, SPLITS[split], generator, index, 317]))
    values = [int(rng.choice(4, p=pi))]
    for step in range(1, 6):
        if family == 0:
            proposed = int(rng.choice(4, p=pi))
        elif family == 1:
            proposed = values[-1]
        elif family == 2:
            proposed = (values[-1] + 1) % 4
        elif family == "reverse":
            proposed = (values[-1] - 1) % 4
        else:
            proposed = (values[-2] + 1) % 4 if step >= 2 else int(rng.choice(4, p=pi))
        values.append(proposed if rng.random() < rho else int(rng.choice(4, p=pi)))
    keys = list(map(int, rng.permutation(4)))
    keys += (list(map(int, rng.permutation(4)[:2])) if rng.random() < q
             else list(map(int, rng.integers(4, size=2))))
    count = int(rng.choice([8, 24]))
    positions = sorted(map(int, rng.choice(6 + count, 6, replace=False)))
    full = np.stack([token(2, int(rng.integers(4)), int(rng.integers(4))) for _ in range(6 + count)])
    targets = np.zeros(4, dtype=np.int8)
    for position, key, value in zip(positions, keys, values, strict=True):
        full[position], targets[key] = token(0, key, value), value
    mask = np.ones(len(full), dtype=bool)
    if not complete:
        mask[rng.choice(len(full), int(rng.choice([2, 3, 4])), replace=False)] = False
    prefix = full.copy()
    prefix[~mask] = 0
    alias_to_key = rng.permutation(4)
    bridges = []
    for alias in rng.permutation(4):
        bridge = np.zeros(24, dtype=np.int8)
        bridge[[alias_to_key[alias], 15, 16, 17, 19 + alias]] = 1
        bridges.append(bridge)
    query_alias = int(rng.integers(4))
    query = np.zeros(24, dtype=np.int8)
    query[[13, 17, 19 + query_alias]] = 1
    return dict(prefix=prefix, observed=mask, bridges=np.stack(bridges), query=query,
        dt=np.full(len(full), .5), price=float(rng.choice([.02, .12, .3, .6])),
        owner_events=full, target=int(targets[alias_to_key[query_alias]]), family=family,
        generator=generator, index=index)
