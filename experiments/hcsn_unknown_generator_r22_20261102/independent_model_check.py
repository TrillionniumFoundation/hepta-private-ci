"""Independent public-count, rational-key, grouped-moment and equality-orbit audit."""

from collections import Counter, defaultdict
from fractions import Fraction
import gzip
from itertools import product
import hashlib
import json
import math
from pathlib import Path
import time

import numpy as np

from .predictive_reference import probability

ROOT = Path(__file__).parent
SEQUENCES = list(product(range(4), repeat=6))
KINDS = ("homogeneous", "lag1", "skip2", "full2")


def fit_counts(sequences):
    initial, pair = [0.5] * 4, [[0.5] * 4 for _ in range(4)]
    homogeneous = [[0.5] * 4 for _ in range(4)]
    rows = [[[0.5] * 4 for _ in range(n)] for n in (4, 4, 16)]
    for v in sequences:
        initial[v[0]] += 1
        pair[v[0]][v[1]] += 1
        for t in range(1, 6):
            homogeneous[v[t - 1]][v[t]] += 1
            if t >= 2:
                rows[0][v[t - 1]][v[t]] += 1
                rows[1][v[t - 2]][v[t]] += 1
                rows[2][4 * v[t - 2] + v[t - 1]][v[t]] += 1
    return initial, homogeneous, pair, rows


def softmax(values):
    values = [math.exp(x - max(values)) for x in values]
    total = math.fsum(values)
    return [x / total for x in values]


def rational_q(distinct, same):
    # Integrate (3+q)^D*(1-q)^S and q times that polynomial exactly.
    coefficients = [0] * (distinct + same + 1)
    for a in range(distinct + 1):
        first = math.comb(distinct, a) * 3 ** (distinct - a)
        for b in range(same + 1):
            coefficients[a + b] += first * math.comb(same, b) * (-1) ** b
    denominator = sum((Fraction(c, k + 1) for k, c in enumerate(coefficients)), Fraction())
    numerator = sum((Fraction(c, k + 2) for k, c in enumerate(coefficients)), Fraction())
    assert 0 < numerator < denominator
    return float(numerator / denominator)


def orbit_classes():
    classes = defaultdict(list)
    for index, sequence in enumerate(SEQUENCES):
        seen, pattern = {}, []
        for value in sequence:
            if value not in seen:
                seen[value] = len(seen)
            pattern.append(seen[value])
        classes[tuple(pattern)].append(index)
    assert len(classes) == 187
    return list(classes.values())


def orbit_average(raw, classes):
    result = np.empty(4096)
    for indices in classes:
        mean = math.fsum(float(raw[i]) for i in indices) / len(indices)
        result[indices] = mean
    return result


def extract(raw_groups):
    groups = []
    for raw in raw_groups:
        sequences, distinct = [], []
        for stream in raw:
            assert len(stream) in (14, 30)
            writes = []
            for event in stream:
                assert len(event) == 24 and all(x in (0, 1) for x in event)
                assert sum(event[:4]) == sum(event[4:8]) == sum(event[12:16]) == 1
                if event[12] == 1:
                    writes.append((event[:4].index(1), event[4:8].index(1)))
            assert len(writes) == 6 and len({k for k, _ in writes[:4]}) == 4
            sequences.append(tuple(v for _, v in writes))
            distinct.append(writes[4][0] != writes[5][0])
        groups.append((sequences, distinct))
    return groups


def main():
    start = time.process_time()
    directory = ROOT / "development_fit_final"
    fit_identity = json.loads((directory / "FIT_IDENTITY.json").read_text())
    input_path = ROOT.parent / fit_identity["input_path"]
    assert hashlib.sha256(input_path.read_bytes()).hexdigest() == fit_identity["input_sha256"]
    for name, expected in fit_identity["files"].items():
        data = (directory / name).read_bytes()
        assert hashlib.sha256(data).hexdigest() == expected["sha256"]
        assert hashlib.sha256(gzip.decompress(data)).hexdigest() == expected["raw_sha256"]
    groups = extract(json.loads(gzip.decompress(input_path.read_bytes())))
    diagnostics = json.loads(gzip.decompress((directory / "DIAGNOSTICS.json.gz").read_bytes()))
    published = json.loads(gzip.decompress((directory / "MODELS.json.gz").read_bytes()))
    contributions = {name:{k:[] for k in ("same", "distinct")} for name in ("first", "context")}
    max_fit, fit_checks, max_mass = 0., 0, 0.
    def compare(expected, actual):
        nonlocal max_fit, fit_checks
        a, b = np.asarray(expected), np.asarray(actual)
        assert a.shape == b.shape
        error = float(np.max(np.abs(a - b)))
        max_fit, fit_checks = max(max_fit, error), fit_checks + a.size
        assert error < 2e-10
    for (sequences, distinct), detail in zip(groups, diagnostics["groups"], strict=True):
        split = 3 * len(sequences) // 4
        initial, homogeneous, pair, rows = fit_counts(sequences[:split])
        heads = [initial, pair, pair, pair]
        matrices = [homogeneous] + rows
        scores = [math.fsum(math.log(probability(v, h, m, kind)) for v in sequences[split:])
                  for h, m, kind in zip(heads, matrices, KINDS, strict=True)]
        fw, cw = softmax(scores[:2]), softmax(scores)
        initial, homogeneous, pair, rows = fit_counts(sequences)
        q = rational_q(sum(distinct), len(distinct) - sum(distinct))
        for key, actual in (("homogeneous_initial", initial), ("homogeneous_rows", homogeneous), ("pair", pair)):
            compare(detail[key], actual)
        for a, b in zip(detail["rows"], rows, strict=True):
            compare(a, b)
        for a, b in ((detail["selection_log_likelihoods"], scores), (detail["first_weights"], fw),
                     (detail["context_weights"], cw), ([detail["q_posterior_mean"]], [q])):
            compare(a, b)
        heads, matrices = [initial, pair, pair, pair], [homogeneous] + rows
        tables = np.array([[probability(v, h, m, kind) for v in SEQUENCES]
                           for h, m, kind in zip(heads, matrices, KINDS, strict=True)])
        max_mass = max(max_mass, max(abs(math.fsum(row) - 1) for row in tables))
        assert max_mass < 2e-12 and np.all(tables > 0)
        for name, density in (("first", np.asarray(fw) @ tables[:2]), ("context", np.asarray(cw) @ tables)):
            contributions[name]["same"].append(density * (1 - q) / 16)
            contributions[name]["distinct"].append(density * ((1 - q) / 16 + q / 12))
    classes = orbit_classes()
    contributions = {n:{k:np.asarray(v) for k, v in cols.items()} for n, cols in contributions.items()}
    grid = diagnostics["orientation_grid"]
    cv, fold_records = [], []
    for fold in range(4):
        train = [i for i in range(len(groups)) if i % 4 != fold]
        raw = {n:{k:contributions[n][k][train].mean(0) for k in ("same", "distinct")} for n in contributions}
        orbit = {n:{k:orbit_average(v, classes) for k, v in cols.items()} for n, cols in raw.items()}
        score = []
        for weight in grid:
            terms = []
            for index, (sequences, distinct) in enumerate(groups):
                if index % 4 != fold:
                    continue
                for values, diff in zip(sequences, distinct, strict=True):
                    code = sum(v * 4 ** (5 - t) for t, v in enumerate(values))
                    key = "distinct" if diff else "same"
                    for name in contributions:
                        terms.append(.5 * math.log((1 - weight) * raw[name][key][code] + weight * orbit[name][key][code]))
            score.append(math.fsum(terms))
        fold_records.append(score)
    cv = [math.fsum(row[j] for row in fold_records) for j in range(len(grid))]
    compare(diagnostics["orientation_group_crossvalidation_scores"], cv)
    for expected, actual in zip(diagnostics["folds"], fold_records, strict=True):
        compare(expected["score_contribution"], actual)
    weight = max(zip(cv, grid, strict=True))[1]
    assert weight == diagnostics["orientation_orbit_weight"] == fit_identity["orientation_orbit_weight"]
    max_compiled, coordinates, masses = 0., 0, {}
    for name in contributions:
        for key in ("same", "distinct"):
            raw = contributions[name][key].mean(0)
            orbit = orbit_average(raw, classes)
            for suffix, value in (("orbit", orbit), ("mixture", (1 - weight) * raw + weight * orbit)):
                actual = np.asarray(published[name + "_" + suffix][key])
                error = float(np.abs(actual - value).max())
                max_compiled, coordinates = max(max_compiled, error), coordinates + 4096
                assert error < 2e-13 and np.all(actual > 0)
    for name, law in published.items():
        masses[name] = abs(4 * math.fsum(law["same"]) + 12 * math.fsum(law["distinct"]) - 1)
        assert masses[name] < 2e-12
    print(json.dumps(dict(passed=True, public_groups=len(groups), public_streams=sum(len(s) for s, _ in groups),
        fitted_and_cv_coordinates=fit_checks, compiled_coordinates=coordinates, orbit_equality_classes=len(classes),
        maximum_fitted_or_cv_difference=max_fit, maximum_compiled_difference=max_compiled,
        maximum_component_mass_error=max_mass, final_law_mass_errors=masses, selected_orbit_weight=weight,
        orientation_cv_independent_scores=cv, model_gzip_sha256=hashlib.sha256((directory / "MODELS.json.gz").read_bytes()).hexdigest(),
        checker_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(), process_cpu_seconds=time.process_time() - start,
        methods="Countercounts; exactrationalqintegrals; grouped60digitDirichletmoments;187equality-patternorbits; leave-generator-outCV",
        candidate_imported=False, new_world_generator_called=False), sort_keys=True))


if __name__ == "__main__":
    main()
