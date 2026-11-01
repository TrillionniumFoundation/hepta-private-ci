"""Independent streams and label-preserving stressors for the continuation.

The original generator is reused unchanged. Its public train interface accepts
an arbitrary seed; disjoint seed ranges below create new development and locked
confirmation streams instead of silently reusing the original fixed test set.
"""

import numpy as np

from experiments.hcsn_four_stage_flow_20261031 import synthetic_data, dynamic_data
from experiments.hcsn_four_stage_flow_20261031.extended_eval import stress_data


STREAMS = {"train": 200000000, "dev": 310000000, "confirm": 420000000}
CONTENT_TASKS = ("mqar", "selective", "binding")
CONDITIONS = ("base", "irregular", "missing", "long_delay", "resample",
              "long_tokens_64", "long_tokens_128", "matched_silence_64",
              "matched_silence_128", "query_swap")


def batch(task, count, seed, split="train", condition="base"):
    if split not in STREAMS or not 0 <= int(seed) < 100000000:
        raise ValueError("Disjoint registered stream and seed required")
    actual_seed = STREAMS[split] + int(seed)
    generator = dynamic_data if task == "dynamics" else synthetic_data
    if condition in ("long_tokens_64", "long_tokens_128", "matched_silence_64",
                     "matched_silence_128", "query_swap"):
        base = generator.batch(task, count, actual_seed, "train", "base")
        return stress_data(task, base, condition)
    result = generator.batch(task, count, actual_seed, "train", condition)
    if task == "dynamics" and condition == "long_delay":
        raise ValueError("Original dynamics generator has no long-delay intervention")
    return result


def informative_time_intervention(data, kind):
    """Change only the model's clock, keeping the same world's labels.

This is an evaluation intervention, not resampling or a new physical trajectory.
    """
    result = {key: np.array(value, copy=True) for key, value in data.items()}
    if kind == "unit_clock":
        result["dt"][:] = .5
    elif kind == "reverse_clock":
        result["dt"] = result["dt"][:, ::-1].copy()
    else:
        raise ValueError(kind)
    return result


def read_opportunity(task, count, seed, split):
    """A delayed real read of a missing FINAL write, with no target in input.

Every arm first receives the same corrupted history. READ returns an observed
    raw write event; STOP does not. The READ continuation first observes the query
    without answering, spends 0.1 time units acquiring the event, and re-queries
    at zero additional elapsed time. The removed event is a final
write, so delayed acquisition does not reorder a newer update. Costs are drawn
independently and are known when the controller chooses. Labels and dependency
selection are environment-only and are never controller features.
    """
    base = batch(task, count, seed, split)
    stop = {key: np.array(value, copy=True) for key, value in base.items()}
    rng = np.random.default_rng(np.random.SeedSequence([STREAMS[split] + seed, 771]))
    n, steps, width = base["x"].shape
    read_x = np.zeros((n, 1, width), np.float32)
    removed = []
    for row in range(n):
        key = int(rng.integers(4))
        writes = np.flatnonzero((base["x"][row, :, 12] > 0)
                               & (base["x"][row, :, key] > 0))
        index = int(writes[-1])
        read_x[row, 0] = base["x"][row, index]
        stop["x"][row, index] = 0
        stop["observed"][row, index] = False
        if "target_available" in stop:
            removed_value = int(read_x[row, 0, 4:12].argmax())
            stop["target_available"][row, stop["y"][row] == removed_value] = False
        removed.append(index)
    query = steps - 4
    insertion = dict(x=np.concatenate((read_x, stop["x"][:, query:query+1]), 1),
        dt=np.concatenate((np.full((n, 1), .1, np.float32), np.zeros((n, 1), np.float32)), 1),
        observed=np.ones((n, 2), bool),
        y=np.concatenate((np.full((n, 1), -100, np.int64), stop["y"][:, query:query+1]), 1),
        sample_weight=np.concatenate((np.zeros((n, 1), np.float32),
                                      stop["sample_weight"][:, query:query+1]), 1))
    read = {}
    for key, value in insertion.items():
        prefix = stop[key][:, :query+1].copy()
        if key == "y":
            prefix[:, query] = -100
        elif key == "sample_weight":
            prefix[:, query] = 0
        read[key] = np.concatenate((prefix, value, stop[key][:, query+1:]), axis=1)
    read["query_mask"] = read["y"] >= 0
    prices = rng.choice(np.asarray([.02, .08, .16, .24, .32], np.float64), n)
    return stop, read, prices, np.asarray(removed, np.int64)
