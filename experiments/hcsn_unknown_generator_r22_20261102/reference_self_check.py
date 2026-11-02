"""Synthetic ordered-law normalization check, without candidate or world imports."""

from itertools import product
import json
import math
import time

from .predictive_reference import probability


def verify():
    start = time.process_time()
    records = {}
    for kind in ("homogeneous", "lag1", "skip2", "full2"):
        head = [float(j + .5) for j in range(4)] if kind == "homogeneous" else [[1 + r + .25 * c for c in range(4)] for r in range(4)]
        nrow = 16 if kind == "full2" else 4
        rows = [[.375 + .125 * (4 * r + c) for c in range(4)] for r in range(nrow)]
        values, maximum = [], 0.
        for sequence in product(range(4), repeat=6):
            expected = probability(sequence, head, rows, kind)
            if kind == "homogeneous":
                direct = head[sequence[0]] / sum(head)
            else:
                direct = head[sequence[0]][sequence[1]] / sum(map(sum, head))
            used = [[0] * 4 for _ in range(nrow)]
            for t in range(1 if kind == "homogeneous" else 2, 6):
                row = (4 * sequence[t - 2] + sequence[t - 1] if kind == "full2"
                       else sequence[t - (2 if kind == "skip2" else 1)])
                target = sequence[t]
                direct *= (rows[row][target] + used[row][target]) / (sum(rows[row]) + sum(used[row]))
                used[row][target] += 1
            maximum = max(maximum, abs(expected - direct))
            values.append(expected)
        mass_error = abs(math.fsum(values) - 1)
        assert maximum < 2e-14 and mass_error < 2e-13 and min(values) > 0
        records[kind] = dict(sequences=len(values), scalar_decimal_vs_sequential_maximum=maximum,
                             normalization_error=mass_error, minimum_probability=min(values))
    return dict(passed=True, components=records, process_cpu_seconds=time.process_time() - start,
                world_generator_called=False, candidate_imported=False, input_scope="Syntheticpositivehead/rowcoordinates only")


if __name__ == "__main__":
    print(json.dumps(verify(), sort_keys=True))
