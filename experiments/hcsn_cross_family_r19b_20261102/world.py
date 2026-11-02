"""Owner-only stationary families and never-trained coherent process shifts."""

import numpy as np

SEED = 19112187
FAMILIES = {"iid":11, "sticky":23, "rotor":37, "switching_rotor":53, "pair_renewal":71}
STAGES = {"train":109, "public_fit":223, "public_cal":331, "ood":443, "calibration":557, "confirm":661}
TRAINED = ("iid", "sticky", "rotor")
ALL = TRAINED + ("switching_rotor", "pair_renewal")


def event(kind, key, value):
    raw = np.zeros(24, dtype=np.int8)
    raw[[key, 4 + value, 12 + kind, 16]] = 1
    return raw


def sample(stage, family, generator, index, complete=False):
    parameter_rng = np.random.default_rng(np.random.SeedSequence([SEED, STAGES[stage], FAMILIES[family], generator, 991]))
    pi = parameter_rng.dirichlet(np.full(4, .4))
    rho = parameter_rng.uniform(.6, .97)
    direction = int(parameter_rng.choice([-1, 1]))
    q = parameter_rng.uniform()
    rng = np.random.default_rng(np.random.SeedSequence([SEED, STAGES[stage], FAMILIES[family], generator, index, 317]))
    values = [int(rng.choice(4, p=pi))]
    for step in range(1, 6):
        if family == "iid":
            value = int(rng.choice(4, p=pi))
        elif family == "sticky":
            value = values[-1] if rng.random() < rho else int(rng.choice(4, p=pi))
        elif family in ("rotor", "switching_rotor"):
            effective = -direction if family == "switching_rotor" and step >= 3 else direction
            value = (values[-1] + effective) % 4 if rng.random() < rho else int(rng.choice(4, p=pi))
        elif family == "pair_renewal":
            value = values[-1] if step % 2 else int(rng.choice(4, p=pi))
        else:
            raise ValueError("Unknown owner process")
        values.append(value)
    keys = list(map(int, rng.permutation(4)))
    keys += (list(map(int, rng.permutation(4)[:2])) if rng.random() < q else list(map(int, rng.integers(4, size=2))))
    distractors = int(rng.choice([8, 24]))
    positions = sorted(map(int, rng.choice(6 + distractors, 6, replace=False)))
    full = np.stack([event(2, int(rng.integers(4)), int(rng.integers(4))) for _ in range(6 + distractors)])
    targets = np.zeros(4, dtype=np.int8)
    for position, key, value in zip(positions, keys, values, strict=True):
        full[position] = event(0, key, value)
        targets[key] = value
    mask = np.ones(len(full), dtype=bool)
    missing = 0 if complete else int(rng.choice([2, 3, 4]))
    if missing:
        mask[rng.choice(len(full), missing, replace=False)] = False
    prefix = full.copy()
    prefix[~mask] = 0
    aliases, bridges = rng.permutation(4), []
    for alias in rng.permutation(4):
        raw = np.zeros(24, dtype=np.int8)
        raw[[aliases[alias], 15, 16, 17, 19 + alias]] = 1
        bridges.append(raw)
    alias = int(rng.integers(4))
    query = np.zeros(24, dtype=np.int8)
    query[[13, 17, 19 + alias]] = 1
    dt = rng.choice([.25, .5, 1.], len(full))
    dt[-1] += float(rng.choice([20., 100.]))
    return dict(prefix=prefix, observed=mask, bridges=np.stack(bridges), query=query, dt=dt,
                price=float(rng.choice([.02, .12, .3, .6])), owner_events=full,
                target=int(targets[aliases[alias]]), generator=generator, index=index,
                missing_count=missing, distractors=distractors)
