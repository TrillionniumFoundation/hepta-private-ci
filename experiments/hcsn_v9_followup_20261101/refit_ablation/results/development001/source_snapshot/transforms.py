"""Exact v8 count transform definition, standalone NumPy import."""
import numpy as np

def transform_counts(probabilities, intervention):
    p = np.asarray(probabilities, dtype=np.float64)
    if p.ndim != 1 or len(p) < 2 or not np.isfinite(p).all() or (p < 0).any():
        raise ValueError("A finite nonnegative count law is required")
    if abs(float(p.sum()) - 1) > 1e-10:
        raise ValueError("Count law must conserve probability")
    if intervention == "original":
        return p.copy()
    result = np.zeros_like(p)
    if intervention == "mean_two_point":
        mean = float(p @ np.arange(len(p)))
        lower = min(int(np.floor(mean)), len(p) - 1)
        if lower == len(p) - 1:
            result[lower] = 1
        else:
            result[lower + 1] = mean - lower
            result[lower] = 1 - result[lower + 1]
    elif intervention == "single_transition":
        result[0], result[1] = p[0], 1 - p[0]
    else:
        raise ValueError("Unknown count intervention")
    return result
