#!/usr/bin/env python3
"""Finite independent arithmetic checks, not execution of repository Rust.

Equivalent to the inline round-three check, with explicit counters for each
assertion's scope. There is no claim of exhaustive coverage beyond these bounds.
Run with: python3 verify_math.py
"""

from fractions import Fraction
from hashlib import sha256
from itertools import product
from math import isqrt
from pathlib import Path
from random import Random
import json
import platform
import sys


SCALE = 1 << 32
SENSOR_SEED = 353
SENSOR_ATTEMPTS = 2000


def check_attainable_statistics():
    cases = 0
    sample_tuples = 0
    empty_extrema_cases = 0
    for count in range(1, 5):
        observed = {}
        for values in product(range(-4, 5), repeat=count):
            sample_tuples += 1
            observed.setdefault((min(values), max(values)), set()).add(
                round(Fraction(sum(values), count))
            )
        for minimum in range(-4, 5):
            for maximum in range(minimum, 5):
                lower = round(Fraction((count - 1) * minimum + maximum, count))
                upper = round(Fraction((count - 1) * maximum + minimum, count))
                admitted = set(range(lower, upper + 1))
                actual = observed.get((minimum, maximum), set())
                assert admitted == actual, (count, minimum, maximum, admitted, actual)
                empty_extrema_cases += int(not actual)
                cases += 1
    return {
        "count_range": [1, 4],
        "individual_raw_value_range": [-4, 4],
        "rounding_oracle": "exact Fraction rounded nearest/ties-to-even",
        "enumerated_sample_tuples": sample_tuples,
        "extrema_and_count_cases": cases,
        "unattainable_extrema_cases": empty_extrema_cases,
        "assertions": "interval of admitted means equals actual enumerated means",
    }


def check_hamilton_probabilities():
    cases = 0
    probability_checks = 0
    for branch_count in range(1, 5):
        for counts in product(range(1, 9), repeat=branch_count):
            total = sum(counts)
            rows = [divmod(count * SCALE, total) for count in counts]
            left = SCALE - sum(base for base, _ in rows)
            order = sorted(range(branch_count), key=lambda i: (-rows[i][1], i))
            raw = [
                base + int(i in order[:left])
                for i, (base, _) in enumerate(rows)
            ]
            assert sum(raw) == SCALE, counts
            assert all(0 < probability <= SCALE for probability in raw), counts
            assert all(
                abs(Fraction(raw[i], SCALE) - Fraction(counts[i], total))
                < Fraction(1, SCALE)
                for i in range(branch_count)
            ), counts
            probability_checks += branch_count
            cases += 1
    return {
        "branch_count_range": [1, 4],
        "positive_count_per_branch_range": [1, 8],
        "maximum_total_count": 32,
        "count_vectors": cases,
        "individual_probability_checks": probability_checks,
        "tie_break": "ascending branch index, representing canonical identity order",
        "assertions": [
            "Q32 probabilities sum exactly to ONE",
            "every probability is positive and at most ONE",
            "absolute quantization error for every branch is strictly below one LSB",
        ],
    }


def check_sensor_geometry():
    rng = Random(SENSOR_SEED)
    cases = 0
    skipped = 0
    representable_separation_cases = 0
    zero_quantized_separation_cases = 0
    for _ in range(SENSOR_ATTEMPTS):
        dimensions = rng.randint(1, 4)
        count = rng.randint(2, 10)
        coordinates = sorted(
            set(
                tuple(rng.randrange(33) for _ in range(dimensions))
                for _ in range(count)
            )
        )
        if len(coordinates) < 2:
            skipped += 1
            continue
        requested = rng.randint(2, len(coordinates))

        def distance(i, j):
            return sum(
                (a - b) ** 2 for a, b in zip(coordinates[i], coordinates[j])
            )

        selected = [0]
        nearest = [distance(i, 0) for i in range(len(coordinates))]
        separation = None
        while len(selected) < requested:
            chosen = max(
                (i for i in range(len(coordinates)) if i not in selected),
                key=lambda i: (nearest[i], -i),
            )
            separation = (
                nearest[chosen]
                if separation is None
                else min(separation, nearest[chosen])
            )
            selected.append(chosen)
            nearest = [
                min(current, distance(i, chosen))
                for i, current in enumerate(nearest)
            ]
        brute = min(
            distance(i, j)
            for left, i in enumerate(selected)
            for j in selected[left + 1 :]
        )
        assert separation == brute, (coordinates, requested)
        h2 = max(nearest)
        h = isqrt(h2) + int(isqrt(h2) ** 2 < h2)
        q = isqrt(separation) // 2
        if q:
            mesh = (h * SCALE + q - 1) // q
            assert mesh <= 4 * SCALE, (coordinates, requested, mesh)
            representable_separation_cases += 1
        else:
            zero_quantized_separation_cases += 1
        cases += 1
    return {
        "seed": SENSOR_SEED,
        "attempts": SENSOR_ATTEMPTS,
        "dimensions_range": [1, 4],
        "generated_candidate_count_range": [2, 10],
        "raw_coordinate_range": [0, 32],
        "ordering": "lexicographically sorted unique coordinates assigned ascending identity indices",
        "requested_count": "uniform integer from 2 through unique candidate count",
        "skipped_with_fewer_than_two_unique_candidates": skipped,
        "separation_checks_against_all_selected_pairs": cases,
        "conservative_mesh_checks_with_positive_quantized_separation": representable_separation_cases,
        "zero_quantized_separation_cases_without_mesh_assertion": zero_quantized_separation_cases,
        "assertions": [
            "nearest-distance reuse equals minimum over all final selected pairs",
            "ceil fill / floor separation gives Q32 mesh no greater than four when separation is representable",
        ],
    }


def main():
    if sys.flags.optimize:
        raise RuntimeError("Assertions must remain enabled; rerun without Python optimization.")
    report = {
        "schema": "learning-operator-round3-independent-math-checks.v1",
        "script_sha256": sha256(Path(__file__).read_bytes()).hexdigest(),
        "python": platform.python_version(),
        "q32_scale": SCALE,
        "scope": "finite independent arithmetic checks; repository Rust is not executed",
        "limitations": [
            "No infinite or full-input-domain proof is claimed.",
            "Rust parsing, serialization, signature verification and Cargo tests are outside this script.",
            "Sensor coverage is restricted to the finite generated designs and raw coordinate range.",
            "Cases whose separation quantizes to zero do not undergo the mesh inequality assertion.",
        ],
        "attainable_statistics": check_attainable_statistics(),
        "hamilton_probabilities": check_hamilton_probabilities(),
        "sensor_geometry": check_sensor_geometry(),
        "result": "all finite independent arithmetic checks passed",
    }
    print(json.dumps(report, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
