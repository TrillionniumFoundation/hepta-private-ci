"""Controlled relaxation with noisy partial observations and a mid-episode jump.

Labels derive from the independently integrated physical trajectory. Changing
physical time changes the trajectory; splitting a fixed interval does not.
"""

import numpy as np


def batch(task, batch_size, seed, split="train", stress="base"):
    if task != "dynamics":
        raise ValueError(task)
    namespace = {"train": 1, "dev": 2, "test": 3}[split]
    rng = np.random.default_rng(np.random.SeedSequence([seed, namespace, 101]))
    clock = np.random.default_rng(np.random.SeedSequence([seed, namespace, 102]))
    stress_clock = np.random.default_rng(np.random.SeedSequence([seed, namespace, 103]))
    n, steps = batch_size, 16
    dt = clock.choice([.25, .5, 1.], (n, steps)).astype(np.float32)
    if stress == "irregular":
        dt *= stress_clock.choice([.5, 1., 2.], (n, steps)).astype(np.float32)
    forcing = rng.uniform(-1.2, 1.2, (n, 2))
    noise = rng.normal(0, .25, (n, steps))
    state = rng.uniform(-1.2, 1.2, n)
    x = np.zeros((n, steps, 24), np.float32)
    observed = np.ones((n, steps), bool)
    y = np.full((n, steps), -100, np.int64)
    for t in range(steps):
        target = forcing[:, int(t >= steps // 2)]
        state = target + (state - target) * np.exp(-.8 * dt[:, t])
        # A forcing change is observable; the latent state is never supplied.
        x[:, t, 2] = target
        if t % 2 == 0:
            x[:, t, 0] = state + noise[:, t]
            x[:, t, 1] = 1
        else:
            x[:, t, 3] = 1
            y[:, t] = np.digitize(state, [-.5, 0., .5])
    if stress == "missing":
        observed[:, 8] = False
        x[:, 8] = 0
    weight = (y >= 0).astype(np.float32)
    if stress == "resample":
        sx = np.zeros((n, 2 * steps, 24), np.float32)
        so = np.zeros((n, 2 * steps), bool)
        sy = np.full((n, 2 * steps), -100, np.int64)
        sw = np.zeros((n, 2 * steps), np.float32)
        sx[:, 1::2], so[:, 1::2], sy[:, 1::2], sw[:, 1::2] = x, observed, y, weight
        x, observed, y, weight = sx, so, sy, sw
        dt = np.repeat(dt / 2, 2, axis=1)
    return dict(x=x, dt=dt, observed=observed, y=y, sample_weight=weight, query_mask=y >= 0)
