"""Owner-only continuous generator families and raw symbolic alias queries."""

import numpy as np

SEED = 18011773
SPLITS = {"train": 11, "ood_calibration": 23, "risk_calibration": 37, "confirm": 53, "rotor": 71, "vocabulary": 89}


def parameters(split, generator):
    rng = np.random.default_rng(np.random.SeedSequence([SEED, SPLITS[split], generator, 991]))
    return dict(pi=rng.dirichlet(np.full(4, .7)),
                rho=0. if rng.random() < .5 else rng.uniform(.55, .95), q=rng.uniform())


def token(kind, key, value):
    event = np.zeros(24, dtype=np.int8)
    event[[key, 4 + value, 12 + kind, 16]] = 1
    return event


def sample(split, generator, index, complete=False):
    theta = parameters(split, generator)
    rng = np.random.default_rng(np.random.SeedSequence([SEED, SPLITS[split], generator, index, 317]))
    values = [int(rng.choice(4, p=theta["pi"]))]
    for _ in range(5):
        if split == "rotor":
            values.append((values[-1] + 1) % 4 if rng.random() < .95 else int(rng.integers(4)))
        else:
            values.append(values[-1] if rng.random() < theta["rho"] else int(rng.choice(4, p=theta["pi"])))
    keys = list(map(int, rng.permutation(4)))
    keys += (list(map(int, rng.permutation(4)[:2])) if rng.random() < theta["q"]
             else list(map(int, rng.integers(4, size=2))))
    count = int(rng.choice([8, 24]))
    positions = sorted(map(int, rng.choice(6 + count, 6, replace=False)))
    full = np.stack([token(2, int(rng.integers(4)), int(rng.integers(4))) for _ in range(6 + count)])
    target = np.zeros(4, dtype=np.int8)
    for position, key, value in zip(positions, keys, values, strict=True):
        full[position] = token(0, key, value)
        target[key] = value
    mask = np.ones(len(full), dtype=bool)
    missing = 0 if complete else int(rng.choice([2, 3, 4]))
    if missing:
        mask[rng.choice(len(full), missing, replace=False)] = False
    public = full.copy()
    public[~mask] = 0
    alias_to_key = rng.permutation(4)
    bridges = []
    for alias in rng.permutation(4):
        bridge = np.zeros(24, dtype=np.int8)
        bridge[[alias_to_key[alias], 15, 16, 17, 19 + alias]] = 1
        bridges.append(bridge)
    query_alias = int(rng.integers(4))
    query = np.zeros(24, dtype=np.int8)
    query[[13, 17, 19 + query_alias]] = 1
    dt = rng.choice([.25, .5, 1.], len(full))
    dt[-1] += float(rng.choice([20., 100.]))
    if split == "vocabulary":
        # Public schema violation, not a secret out-of-distribution flag.
        visible_write = next(position for position in positions if mask[position])
        public[visible_write, 4:12] = 0
        public[visible_write, 8] = 1
    return dict(prefix=public, observed=mask, bridges=np.stack(bridges), query=query, dt=dt,
                price=float(rng.choice([.02, .12, .3, .6])), owner_events=full,
                target=int(target[alias_to_key[query_alias]]), generator=generator,
                index=index, missing_count=missing, distractors=count)
