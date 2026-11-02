"""Paired-fit uncertainty: original two-domain core gate is unchanged."""

import itertools
import numpy as np
from scipy.stats import t


def contrast(values):
    x = np.asarray(values, dtype=np.float64)
    mean = float(x.mean())
    half = float(t.ppf(.975, len(x) - 1) * x.std(ddof=1) / np.sqrt(len(x)))
    signs = np.asarray(list(itertools.product((-1, 1), repeat=len(x))))
    p = float(np.mean(abs((signs * x).mean(1)) >= abs(mean) - 1e-15))
    return dict(fits=x.tolist(), mean=mean, lower=mean - half, upper=mean + half, signflip_p=p)


def holm(rows):
    ordered = sorted(range(len(rows)), key=lambda i: rows[i]["signflip_p"])
    previous = 0.
    for rank, index in enumerate(ordered):
        previous = max(previous, min(1., (len(rows) - rank) * rows[index]["signflip_p"]))
        rows[index]["holm_p"] = previous
    return rows
