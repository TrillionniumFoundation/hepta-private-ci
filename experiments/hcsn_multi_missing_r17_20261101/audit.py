"""Independent exhaustive tiny-world reference, without importing posterior code.

The complete latent law is enumerated before applying a mask. Integer world
counts yield the conditional posterior and likelihood, independently of the
production method's missing-slot/key/value completion.
"""

from collections import defaultdict
from itertools import combinations, permutations, product
from fractions import Fraction

import numpy as np


def universe(generator):
    rows = []
    for positions in combinations(range(4), 2):
        for key_order in permutations(range(2)):
            value_orders = permutations(range(3)) if generator == "without_replacement" else product(range(3), repeat=3)
            for values in value_orders:
                for overwrite_key in range(2):
                    for distractors in product(range(6), repeat=2):
                        events, wi, di = [], 0, 0
                        final = [0, 0]
                        for pos in range(4):
                            if pos in positions:
                                key, value = key_order[wi], values[wi]
                                events.append((0, key, value))
                                final[key] = value
                                wi += 1
                            else:
                                code = distractors[di]
                                events.append((2, code // 3, code % 3))
                                di += 1
                        events.append((0, overwrite_key, values[2]))
                        final[overwrite_key] = values[2]
                        rows.append((tuple(events), tuple(final)))
    return rows


def grouped_cases(generator, mask):
    worlds = universe(generator)
    grouped = defaultdict(list)
    for events, final in worlds:
        prefix = tuple(event if visible else None for event, visible in zip(events, mask, strict=True))
        grouped[prefix].append((events, final))
    keys = sorted(grouped, key=repr)
    selected = [keys[index] for index in np.linspace(0, len(keys) - 1, min(24, len(keys)), dtype=int)]
    result = []
    for key in selected:
        rows = grouped[key]
        p = np.zeros((2, 3))
        for _, final in rows:
            for address, value in enumerate(final):
                p[address, value] += 1 / len(rows)
        result.append(dict(prefix=key, marginals=p.tolist(), evidence=float(Fraction(len(rows), len(worlds))),
                           rows=rows))
    return result
