"""Owner-only data generator independent of the inference implementation."""

import numpy as np


def sample(rng, generator, task, missing_count):
    values = (rng.permutation(8)[:6] if generator == "without_replacement" else rng.integers(8, size=6))
    rows = []
    for key in rng.permutation(4):
        token = np.zeros(24, dtype=np.int8)
        token[[key, 4 + values[key], 12, 16]] = 1
        rows.append(token)
    for _ in range(4):
        token = np.zeros(24, dtype=np.int8)
        token[[rng.integers(4), 4 + rng.integers(8), 14, 16]] = 1
        rows.append(token)
    rows = [rows[i] for i in rng.permutation(8)]
    final = np.array(values[:4], copy=True)
    if task == "selective":
        for j, key in enumerate(rng.permutation(4)[:2]):
            token = np.zeros(24, dtype=np.int8)
            token[[key, 4 + values[4 + j], 12, 16]] = 1
            rows.append(token)
            final[key] = values[4 + j]
    full = np.stack(rows)
    mask = np.ones(len(rows), dtype=bool)
    mask[rng.choice(len(rows), missing_count, replace=False)] = False
    observed = full.copy()
    observed[~mask] = 0
    aliases = rng.permutation(4) if task == "binding" else np.arange(4)
    return dict(prefix=observed, observed=mask, owner_events=full, target=final, aliases=aliases)
