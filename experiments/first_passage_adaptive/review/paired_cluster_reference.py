"""Independent reference for the registered conditional-on-fits inference.

Inputs are the two paired mean-utility differences per complete context. Every
row already keeps all 64 within-context repeats together. This reference is
an audit aid, not the study runner, and its self-check uses artificial data.
"""

import json

import numpy as np


def summarize(effects, fit_labels, stratum_labels, *, fit_order, stratum_order,
              replicates=4000, random_seed=2026102985, tail=0.003125, margin=0.005):
    effects = np.asarray(effects, dtype=float)
    fit_labels, stratum_labels = np.asarray(fit_labels), np.asarray(stratum_labels)
    if (effects.ndim != 2 or effects.shape[1] != 2
            or fit_labels.shape != (len(effects),)
            or stratum_labels.shape != (len(effects),)
            or not np.isfinite(effects).all()
            or len(fit_order) != 3 or len(stratum_order) != 3
            or len(set(fit_order)) != 3 or len(set(stratum_order)) != 3):
        raise ValueError("Expected two paired contrasts in each of nine fixed fit/stratum cells")
    if (set(fit_labels) != set(fit_order)
            or set(stratum_labels) != set(stratum_order)):
        raise ValueError("Unknown or absent registered labels")
    rng = np.random.default_rng(random_seed)
    cell_means = np.empty((3, 3, 2))
    cell_bootstrap = np.empty((3, 3, replicates, 2))
    counts = np.empty((3, 3), dtype=int)
    for f, fit in enumerate(fit_order):
        for s, stratum in enumerate(stratum_order):
            rows = effects[(fit_labels == fit) & (stratum_labels == stratum)]
            if len(rows) == 0:
                raise ValueError("Empty fit/stratum cell")
            counts[f, s] = len(rows)
            cell_means[f, s] = rows.mean(axis=0)
            # One set of context indices jointly resamples both paired contrasts.
            sample = rng.integers(0, len(rows), size=(replicates, len(rows)))
            cell_bootstrap[f, s] = rows[sample].mean(axis=1)
    per_fit = cell_means.mean(axis=1)
    pooled = per_fit.mean(axis=0)
    stratum_means = cell_means.mean(axis=0)
    pooled_bootstrap = cell_bootstrap.mean(axis=(0, 1))
    stratum_bootstrap = cell_bootstrap.mean(axis=0)
    pooled_intervals = np.quantile(pooled_bootstrap, [tail, 1-tail], axis=0).T
    stratum_intervals = np.quantile(stratum_bootstrap, [tail, 1-tail], axis=1)
    stratum_intervals = np.moveaxis(stratum_intervals, 0, -1)
    primary = bool(np.all(pooled_intervals[:, 0] > margin) and np.all(per_fit > 0))
    cross = bool(primary and np.all(stratum_intervals[:, :, 0] > margin))
    return {
        "counts_by_fit_stratum": counts.tolist(),
        "per_fit_pooled_means": per_fit.tolist(),
        "pooled_effects": pooled.tolist(),
        "pooled_intervals": pooled_intervals.tolist(),
        "stratum_effects": stratum_means.tolist(),
        "stratum_intervals": stratum_intervals.tolist(),
        "primary_gate": primary,
        "cross_stratum_gate": cross,
        "family_comparisons": 8,
        "interval_tail_probability": tail,
        "limits": "Empirical percentile intervals conditional on the three frozen fits",
    }


def artificial_self_check():
    effects, fits, strata = [], [], []
    # Unequal cell sizes make observation-weighted pooling detectably wrong.
    for f in range(3):
        for s, count in enumerate((1, 2, 5)):
            row = np.array([0.02 + 0.01*f + 0.03*s, 0.04 + 0.02*f + 0.01*s])
            effects.extend([row] * count)
            fits.extend([f] * count)
            strata.extend([s] * count)
    result = summarize(effects, fits, strata, fit_order=(0, 1, 2), stratum_order=(0, 1, 2))
    expected = [0.06, 0.07]
    np.testing.assert_allclose(result["pooled_effects"], expected, atol=1e-15)
    np.testing.assert_allclose(result["pooled_intervals"], [[0.06, 0.06], [0.07, 0.07]], atol=1e-15)
    assert result["primary_gate"] and result["cross_stratum_gate"]
    assert not np.allclose(np.mean(effects, axis=0), expected)
    # An overall positive average does not override a negative fitted-seed mean.
    bad = np.asarray(effects).copy()
    bad[np.asarray(fits) == 0] -= 0.1
    veto = summarize(bad, fits, strata, fit_order=(0, 1, 2), stratum_order=(0, 1, 2))
    assert np.all(np.asarray(veto["pooled_intervals"])[:, 0] > 0.005)
    assert not veto["primary_gate"]
    return {"positive_fixture": result, "negative_fit_seed_veto": veto, "status": "passed"}


if __name__ == "__main__":
    print(json.dumps(artificial_self_check(), indent=2, sort_keys=True, allow_nan=False))
