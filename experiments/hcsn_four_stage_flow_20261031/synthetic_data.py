"""Raw symbolic content tasks with independent content and physical clocks.

Every key is queried once. The four retained values are distinct, exchangeable
draws from eight classes, so a majority-value rule cannot solve a whole episode.
No posterior, computed address, future value or label is supplied to a model.
"""

import numpy as np


TASKS = {"mqar": 1, "selective": 2, "binding": 3}
SPLITS = {"train": 1, "dev": 2, "test": 3}
STRESSES = ("base", "long_delay", "irregular", "missing", "resample")
FIXED_SEEDS = {"dev": 71001, "test": 81001}
INPUT_DIM = 24
IGNORE_LABEL = -100


def _contract(task, batch_size, seed, split, stress):
    split = "dev" if split in ("val", "validation") else split
    if task not in TASKS or split not in SPLITS or stress not in STRESSES:
        raise ValueError("Unknown task, split or stress condition")
    if not isinstance(batch_size, int) or batch_size <= 0:
        raise ValueError("batch_size must be a positive integer")
    if not isinstance(seed, (int, np.integer)) or seed < 0:
        raise ValueError("seed must be a nonnegative integer")
    actual_seed = FIXED_SEEDS.get(split, int(seed))
    return split, actual_seed


def _event(key, value, kind, modality):
    x = np.zeros(INPUT_DIM, dtype=np.float32)
    x[key] = 1
    if value is not None:
        x[4 + value] = 1
    x[12 + kind] = 1  # write=0, query=1, distractor=2; other=3 is reserved.
    x[16 + modality] = 1
    return x


def _episode(task, rng):
    # Sampling without replacement prevents the previous majority-value shortcut.
    values = rng.permutation(8)
    retained = values[:4].copy()
    prelude = [_event(key, int(retained[key]), 0, 0) for key in rng.permutation(4)]
    for _ in range(4):
        prelude.append(_event(int(rng.integers(4)), int(rng.integers(8)), 2, 0))
    prelude = [prelude[index] for index in rng.permutation(8)]
    if task == "selective":
        # Genuine marked writes overwrite two keys. Distractor key/value pairs do
        # not overwrite. New values are distinct from all four original values.
        for key, value in zip(rng.permutation(4)[:2], values[4:6], strict=True):
            prelude.append(_event(int(key), int(value), 0, 0))
            retained[key] = value
    queries = rng.permutation(4)
    if task == "binding":
        # Episode-local aliases: the B query carries no A key. Only observed
        # bridge tokens reveal the relation, and bridges carry no target value.
        b_for_a = rng.permutation(4)
        bridges = []
        for key in rng.permutation(4):
            bridge = _event(int(key), None, 3, 0)
            bridge[19 + b_for_a[key]] = 1
            bridge[17] = 1
            bridges.append(bridge)
        prelude = bridges + prelude
        query_events = []
        for key in queries:
            query = np.zeros(INPUT_DIM, dtype=np.float32)
            query[19 + b_for_a[key]] = 1
            query[13] = query[17] = 1
            query_events.append(query)
    else:
        query_events = [_event(int(key), None, 1, 0) for key in queries]
    sequence = prelude + query_events
    labels = np.full(len(sequence), IGNORE_LABEL, dtype=np.int64)
    labels[-4:] = retained[queries]
    final_write = {}
    for index, event in enumerate(prelude):
        if event[12]:
            final_write[int(event[:4].argmax())] = index
    dependencies = np.full(len(sequence), -1, dtype=np.int64)
    dependencies[-4:] = [final_write[int(key)] for key in queries]
    return np.stack(sequence), labels, dependencies


def batch(task, batch_size, seed, split="train", stress="base"):
    """Return matched episodes; dev/test seeds are fixed independently of fits.

    Elapsed time precedes each observation. In ``resample`` an unobserved half
    interval precedes the original observation's half interval. In ``missing``
    the world's target is retained after removing one informative write; that
    missing information must not be reconstructed from a leaked target.
    """
    split, actual_seed = _contract(task, batch_size, seed, split, stress)
    namespace = [actual_seed, TASKS[task], SPLITS[split]]
    content_rng = np.random.default_rng(np.random.SeedSequence(namespace + [11]))
    clock_rng = np.random.default_rng(np.random.SeedSequence(namespace + [23]))
    stress_rng = np.random.default_rng(np.random.SeedSequence(namespace + [37]))
    episodes = [_episode(task, content_rng) for _ in range(batch_size)]
    x = np.stack([row[0] for row in episodes]).astype(np.float32)
    y = np.stack([row[1] for row in episodes])
    dependencies = np.stack([row[2] for row in episodes])
    dt = clock_rng.choice(np.array([0.25, 0.5, 1.0], dtype=np.float32), y.shape)
    observed = np.ones(y.shape, dtype=bool)
    query_mask = y != IGNORE_LABEL
    target_available = query_mask.copy()

    if stress == "long_delay":
        dt[:, -4] += 4.0  # One extra silent gap before the first query.
    elif stress == "irregular":
        dt = stress_rng.choice(np.array([0.25, 0.5, 1.0], dtype=np.float32), y.shape)
    elif stress == "missing":
        for row in range(batch_size):
            candidates = np.flatnonzero(x[row, :, 12] == 1)
            index = int(stress_rng.choice(candidates))
            x[row, index] = 0
            observed[row, index] = False
            target_available[row, dependencies[row] == index] = False
    elif stress == "resample":
        original_shape = y.shape
        refined_x = np.zeros((batch_size, 2 * original_shape[1], INPUT_DIM), dtype=np.float32)
        refined_x[:, 1::2] = x
        refined_y = np.full((batch_size, 2 * original_shape[1]), IGNORE_LABEL, dtype=np.int64)
        refined_y[:, 1::2] = y
        refined_observed = np.zeros(refined_y.shape, dtype=bool)
        refined_observed[:, 1::2] = observed
        refined_available = np.zeros(refined_y.shape, dtype=bool)
        refined_available[:, 1::2] = target_available
        x, y, observed = refined_x, refined_y, refined_observed
        target_available = refined_available
        dt = np.repeat(dt / 2, 2, axis=1)
        query_mask = y != IGNORE_LABEL

    if np.any(x[..., 4:12][query_mask]):
        raise AssertionError("Query input contains a target value")
    if not np.all(query_mask.sum(1) == 4) or np.any(query_mask & ~observed):
        raise AssertionError("Exactly four observed queries must survive each stress")
    return dict(x=x, dt=dt.astype(np.float32), observed=observed, y=y,
                sample_weight=query_mask.astype(np.float32), query_mask=query_mask,
                target_available=target_available)


def metadata(task, batch_size, seed, split="train", stress="base"):
    """Protocol-only metadata; does not materialize any episode or holdout."""
    split, actual_seed = _contract(task, batch_size, seed, split, stress)
    base_steps = {"mqar": 12, "selective": 14, "binding": 16}[task]
    return dict(schema="hcsn-four-stage.symbolic.v1", task=task, split=split,
        content_seed=actual_seed, stress=stress, batch_size=batch_size,
        shape=[batch_size, base_steps * (2 if stress == "resample" else 1), INPUT_DIM],
        keys=4, value_classes=8, queries_per_episode=4,
        slices=dict(key=[0, 4], value=[4, 12], event_type=[12, 16],
                    modality=[16, 19], binding_b_key=[19, 23], reserved=[23, 24]),
        event_types=["write", "query", "distractor", "other"],
        timing="dt seconds precede each accepted observation; unobserved steps still consume time",
        missing="Remove one real nonquery write; preserve original world's targets and clock",
        binding="Episode-random A/B permutation; four observed A+B bridges without values; B-only queries",
        binding_scope="Symbolic alias binding, not real audiovisual data",
        target_available="Evaluation-only boolean: final write for this query remains observed; never model input",
        target_balance="Each retained value marginal is uniform over eight classes; all four distinct",
        readout="Score every query and all-four-correct per episode; nonquery labels are -100",
        split_seeds="train follows supplied per-step seed; dev=71001; test=81001")
