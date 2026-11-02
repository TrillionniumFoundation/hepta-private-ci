"""Environment-only finite physical trajectories and supervised calibration.

True rate coefficients and sampled X,Y never enter a planner interface. Y is a
fixed task bit. An outage is the marked transition X2->recovery, not a Y flip.
"""
import numpy as np

# Environment truth; estimators receive transition counts/exposure, not this.
COEFFICIENTS = np.array([[-.4, .3, .2], [-1.8, -.15, .2], [.2, .8, -.4], [-.1, .2, .3]])
READ_ACCURACY = np.array([.97, .78, .52, .5])
PRIOR_COUNTS = np.array([
    [0, 0, 500, 500, 0, 0, 0, 0],
    [250, 250, 0, 0, 250, 250, 0, 0],
    [500, 0, 0, 0, 0, 500, 0, 0],
    [0, 500, 0, 0, 500, 0, 0, 0],
    [900, 100, 0, 0, 0, 0, 0, 0],
    [100, 900, 0, 0, 0, 0, 0, 0],
    [0, 0, 0, 0, 0, 0, 500, 500],
    [0, 0, 0, 0, 500, 500, 0, 0],
], dtype=np.int64)


def rates(context):
    return np.exp(COEFFICIENTS @ np.r_[1., context])


def advance(state, duration, physical_rates, rng):
    """Direct Gillespie path, including remaining time after every outage/reset."""
    remaining, events, segments = float(duration), 0, []
    up, down, outage, recover = physical_rates
    while remaining > 0:
        choices = {0: [(1, up, 0)], 1: [(2, up, 0), (0, down, 1)],
                   2: [(1, down, 1), (3, outage, 2)], 3: [(0, recover, 3)]}[state]
        total = sum(row[1] for row in choices)
        waiting = rng.exponential(1 / total)
        if waiting >= remaining:
            segments.append((state, state, remaining, -1))
            break
        threshold, cumulative = rng.random() * total, 0.
        for target, rate, kind in choices:
            cumulative += rate
            if threshold < cumulative:
                break
        segments.append((state, target, waiting, kind))
        events += int(kind == 2)
        state = target
        remaining -= waiting
    return state, events, segments


def training(seed):
    rng = np.random.default_rng(np.random.SeedSequence([seed, 671]))
    contexts = rng.uniform(-.8, .8, (24, 2))
    counts, exposure, segments = np.zeros((24, 4)), np.zeros((24, 4)), []
    for context_index, context in enumerate(contexts):
        for trajectory in range(64):
            initial = int(rng.integers(4))
            _, _, path = advance(initial, 5., rates(context), rng)
            for state, target, duration, kind in path:
                exposure[context_index] += duration * np.array([state in (0, 1), state in (1, 2), state == 2, state == 3])
                if kind >= 0:
                    counts[context_index, kind] += 1
                segments.append((context_index, trajectory, state, target, duration, kind))
    prior_samples = np.concatenate([np.column_stack((np.full(1000, cue), rng.permutation(np.repeat(np.arange(8), row)))) for cue, row in enumerate(PRIOR_COUNTS)])
    read_state = np.repeat(np.arange(4), 4000)
    read_target = np.tile(np.repeat(np.arange(2), 2000), 4)
    read_observed = np.where(rng.random(len(read_state)) < READ_ACCURACY[read_state], read_target, 1 - read_target)
    return dict(contexts=contexts, counts=counts, exposure=exposure, segments=np.asarray(segments), prior_samples=prior_samples,
                read_state=read_state, read_target=read_target, read_observed=read_observed)


def initial(cue, rng):
    index = int(rng.choice(8, p=PRIOR_COUNTS[cue] / 1000))
    return index // 2, index % 2
