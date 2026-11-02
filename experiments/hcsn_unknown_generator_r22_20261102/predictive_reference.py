"""Independent grouped-count Dirichlet moment reference for ordered six-value laws."""

from collections import Counter
from decimal import Decimal, localcontext
from functools import lru_cache
from itertools import product
import math


@lru_cache(maxsize=32768)
def row_moment(alpha, counts):
    """E[product_j T_j**counts_j]; no multinomial coefficient for ordered paths."""
    if len(alpha) != 4 or len(counts) != 4 or any(a <= 0 or not math.isfinite(a) for a in alpha):
        raise ValueError("Four positive finite Dirichlet coordinates required")
    if any(int(c) != c or c < 0 for c in counts):
        raise ValueError("Nonnegative integer transition counts required")
    counts = tuple(map(int, counts))
    with localcontext() as context:
        context.prec = 60
        a = [Decimal.from_float(float(x)) for x in alpha]
        numerator = Decimal(1)
        for coordinate, count in zip(a, counts, strict=True):
            for j in range(count):
                numerator *= coordinate + j
        denominator = Decimal(1)
        total = sum(a)
        for j in range(sum(counts)):
            denominator *= total + j
        return float(numerator / denominator)


def probability(sequence, head, rows, kind):
    """Integrated independent rows; homogeneous uses t=1, free-pair models use t=2."""
    if any(int(x) != x for x in sequence):
        raise ValueError("Integer values required")
    values = tuple(map(int, sequence))
    if len(values) != 6 or any(not 0 <= x < 4 for x in values):
        raise ValueError("Expected six values in0..3")
    if kind not in ("homogeneous", "lag1", "skip2", "full2"):
        raise ValueError("Unknown declared context")
    flat_head = (tuple(map(float, head)) if kind == "homogeneous"
                 else tuple(float(x) for row in head for x in row))
    expected_head = 4 if kind == "homogeneous" else 16
    if len(flat_head) != expected_head or any(x <= 0 or not math.isfinite(x) for x in flat_head):
        raise ValueError("Positive declared head coordinates required")
    expected_rows = 16 if kind == "full2" else 4
    if len(rows) != expected_rows:
        raise ValueError("Wrong number of context rows")
    counts = Counter()
    for t in range(1 if kind == "homogeneous" else 2, 6):
        row = (4 * values[t - 2] + values[t - 1] if kind == "full2"
               else values[t - (2 if kind == "skip2" else 1)])
        counts[row, values[t]] += 1
    head_index = values[0] if kind == "homogeneous" else 4 * values[0] + values[1]
    result = flat_head[head_index] / math.fsum(flat_head)
    for row in {row for row, _ in counts}:
        result *= row_moment(tuple(map(float, rows[row])), tuple(counts[row, v] for v in range(4)))
    return result


def table(head, rows, kind):
    return [probability(sequence, head, rows, kind) for sequence in product(range(4), repeat=6)]
