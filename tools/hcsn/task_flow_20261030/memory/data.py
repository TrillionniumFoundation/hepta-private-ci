"""New paired cohorts; challenge semantics stay in the generator only."""
from functools import lru_cache
import hashlib
import json
from pathlib import Path
import sys

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from benchmarks.data import make_data, fingerprint
from next.sequence.challenge import retrieval
from third.confirmation.data import historical
from third.memory.data import input_hashes


def overwrite(seed, count, length):
    """Four keys and one later conflicting write to the queried key."""
    rng = np.random.default_rng(seed)
    x = np.zeros((count, length, 16), np.float32)
    labels = np.zeros(count, np.int32)
    for i in range(count):
        keys = rng.choice(8, 4, replace=False)
        values = rng.integers(0, 4, 4)
        positions = np.sort(rng.choice(length - 2, 5, replace=False))
        query = rng.integers(4)
        replacement = (values[query] + rng.integers(1, 4)) % 4
        x[i, positions[:4], keys] = 1.
        x[i, positions[:4], 8 + values] = 1.
        x[i, positions[:4], 12] = 1.
        x[i, positions[4], keys[query]] = 1.
        x[i, positions[4], 8 + replacement] = 1.
        x[i, positions[4], 12] = 1.
        x[i, -1, keys[query]] = x[i, -1, 13] = 1.
        labels[i] = replacement
    filler = x[:, :, 12] + x[:, :, 13] == 0
    x[:, :, :12] += (rng.normal(0, .05, x[:, :, :12].shape) * filler[:, :, None]).astype(np.float32)
    return dict(x=x, dt=np.ones((count, length), np.float32), y=labels)


def make_suite(task, seed, protocol):
    base = (protocol["data_seed_base"] + protocol["tasks"].index(task) * protocol["data_task_offset"]
            + 1000 * seed)
    train = [make_data(task, base + length, protocol["training_examples_per_length"], length)
             for length in protocol["training_lengths"]]
    n = protocol["evaluation_examples"]
    suite = dict(validation32=make_data(task, base + 201, protocol["validation_examples"], 32),
                 test128=make_data(task, base + 428, n, 128),
                 test512=make_data(task, base + 812, n, 512))
    if task == "retrieval":
        suite.update(capacity8_512=retrieval(base + 1501, n, 512, 8, .05),
                     overwrite128=overwrite(base + 1502, n, 128),
                     interference128=retrieval(base + 1503, n, 128, 4, .2))
    hashes = {"train" + str(length): fingerprint(d)
              for length, d in zip(protocol["training_lengths"], train)}
    hashes.update({name: fingerprint(d) for name, d in suite.items()})
    return train, suite, hashes


def audit_freshness(protocol):
    """Enumerate old constructed cohorts only; never instantiate old confirmation."""
    checks = []
    for task in protocol["tasks"]:
        previous = {n: historical(task, n) for n in (32, 128, 512)}
        new_seen = {n: set() for n in previous}
        train32 = set()
        for seed in protocol["seeds"]:
            training, _, _ = make_suite(task, seed, protocol)
            train32.update(input_hashes(training[-1]))
        for seed in protocol["seeds"]:
            _, suite, _ = make_suite(task, seed, protocol)
            for name, d in suite.items():
                n = d["x"].shape[1]
                current = input_hashes(d)
                overlap = len(current & previous[n]) + len(current & new_seen[n])
                if n == 32:
                    overlap += len(current & train32)
                checks.append(dict(task=task, seed=seed, split=name, exact_input_overlap=overlap,
                                   unique=len(current), expected=len(d["y"])))
                new_seen[n].update(current)
    return dict(passed=all(r["exact_input_overlap"] == 0 and r["unique"] == r["expected"] for r in checks),
                checks=checks, old_confirmation_constructed=False,
                scope="Old benchmarks/v3/v4/third development plus current evaluations and train32; short finite-vocabulary training may repeat")
