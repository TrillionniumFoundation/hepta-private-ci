"""Separate full six-dimensional contraction and public-stream fit reconstruction."""

from collections import Counter
from itertools import permutations
import gzip
import hashlib
import json
import math
from pathlib import Path
import time

import numpy as np

ROOT = Path(__file__).parent


def parameters(sequences):
    initial_count = Counter(v[0] for v in sequences)
    first_count = Counter((v[t - 1], v[t]) for v in sequences for t in range(1, 6))
    second_count = Counter((v[t - 2], v[t - 1], v[t]) for v in sequences for t in range(2, 6))
    initial = np.array([initial_count[i] + .5 for i in range(4)])
    initial /= initial.sum()
    first = np.array([[first_count[i, j] + .5 for j in range(4)] for i in range(4)])
    first /= first.sum(1, keepdims=True)
    second = np.array([[[second_count[i, j, k] + first[j, k] for k in range(4)]
                        for j in range(4)] for i in range(4)])
    second /= second.sum(2, keepdims=True)
    return initial, first, second


def log_probability(sequence, initial, first, second):
    a, b = math.log(initial[sequence[0]]), math.log(initial[sequence[0]])
    for t in range(1, 6):
        a += math.log(first[sequence[t - 1], sequence[t]])
        b += math.log(first[sequence[t - 1], sequence[t]] if t == 1
                      else second[sequence[t - 2], sequence[t - 1], sequence[t]])
    return a, b


def main():
    start = time.process_time()
    prepared = ROOT / "prepare_01"
    training_bytes = (prepared / "training.json.gz").read_bytes()
    model_bytes = (prepared / "MODELS.json.gz").read_bytes()
    diagnostic_bytes = (prepared / "FIT_DIAGNOSTICS.json").read_bytes()
    groups = json.loads(gzip.decompress(training_bytes))
    models = json.loads(gzip.decompress(model_bytes))
    diagnostics = json.loads(diagnostic_bytes)
    totals = {name:{column:np.zeros((4,) * 6) for column in ("same", "distinct")} for name in models}
    fit_maximum, fit_coordinates = 0., 0
    for group, diagnostic in zip(groups, diagnostics, strict=True):
        writes = [[(row[:4].index(1), row[4:8].index(1)) for row in stream if row[12] == 1] for stream in group]
        assert all(len(v) == 6 for v in writes)
        sequences = [[x[1] for x in row] for row in writes]
        initial, first, second = parameters(sequences)
        trial = parameters(sequences[:3 * len(sequences) // 4])
        difference = sum(b - a for a, b in (log_probability(v, *trial) for v in sequences[3 * len(sequences) // 4:]))
        weight = 1 / (1 + math.exp(-min(30., max(-30., difference))))
        q = min(1., max(0., 4 * (sum(row[4][0] != row[5][0] for row in writes) + .5) / (len(writes) + 1) - 3))
        for name, expected in (("initial", initial), ("first", first), ("second", second),
                ("context_weight", np.array(weight)), ("q", np.array(q))):
            error = float(np.max(np.abs(expected - np.asarray(diagnostic[name]))))
            fit_maximum = max(fit_maximum, error)
            assert error < 2e-12, (name, error)
            fit_coordinates += expected.size
        # Tensor contractions avoid candidate sequence-index likelihood code entirely.
        p1 = np.einsum("a,ab,bc,cd,de,ef->abcdef", initial, first, first, first, first, first, optimize=True)
        p2 = np.einsum("a,ab,abc,bcd,cde,def->abcdef", initial, first, second, second, second, second, optimize=True)
        orbit1, orbit2 = np.zeros_like(p1), np.zeros_like(p1)
        for permutation in permutations(range(4)):
            axes = np.ix_(*([permutation] * 6))
            orbit1 += p1[axes] / 24
            orbit2 += p2[axes] / 24
        for name, density in (("first_order", p1), ("orbit_first_order", orbit1),
                ("context_orbit", (1 - weight) * orbit1 + weight * orbit2)):
            assert abs(float(density.sum()) - 1.) < 2e-12
            totals[name]["same"] += density * (1 - q) / 16 / len(groups)
            totals[name]["distinct"] += density * ((1 - q) / 16 + q / 12) / len(groups)
    maximum, coordinates, mass_errors = 0., 0, {}
    for name in models:
        for column in ("same", "distinct"):
            expected = totals[name][column].reshape(-1)
            observed = np.asarray(models[name][column])
            error = float(np.max(np.abs(expected - observed)))
            assert error < 2e-14, (name, column, error)
            maximum = max(maximum, error)
            coordinates += len(expected)
        mass_errors[name] = abs(float(4 * sum(models[name]["same"]) + 12 * sum(models[name]["distinct"])) - 1.)
        assert mass_errors[name] < 2e-12
    record = dict(passed=True, fit_groups=len(groups), training_streams=sum(map(len, groups)),
        fitted_coordinates=fit_coordinates, maximum_fitted_coordinate_difference=fit_maximum,
        tensor_compiled_coordinates=coordinates, maximum_tensor_compilation_difference=maximum,
        key_value_law_mass_errors=mass_errors, hashes={name:hashlib.sha256(data).hexdigest()
            for name, data in (("training.json.gz", training_bytes), ("MODELS.json.gz", model_bytes), ("FIT_DIAGNOSTICS.json", diagnostic_bytes))},
        scope="Independent public-stream Counter fits, scalar validation likelihoods, full6D tensor contractions and24label pullbacks; no candidate imports or heldout worlds",
        process_cpu_seconds=time.process_time() - start)
    print(json.dumps(record, sort_keys=True))


if __name__ == "__main__":
    main()
