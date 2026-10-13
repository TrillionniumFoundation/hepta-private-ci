"""Training-only full pooled covariance; no new runtime or learned Encoder.

The same class prototypes and spherical shrinkage target as V12 are used.
Correlated directions change the metric, not inference storage or class meaning.
"""
from __future__ import annotations

import torch

from cell_prototype_gate import SHRINKAGES, geometry_fit, training_folds
from development_tensors import checked_tensor

MAX_FIT_ELEMENTS = 8_388_608
VARIANCE_FLOOR = 1e-8
SOLVE_TOLERANCE = 1e-8


def fit_envelope(rows, width, classes, shrinkage=.1):
    """Bound explicit float64 fitting intermediates, NOT allocator/RSS or LAPACK."""
    return 4 * rows * width + (0 if shrinkage == 1.0 else 8 * width * width) + 8 * classes * width


def correlated_fit(x, labels, groups, classes, shrinkage, *,
                   maximum_fit_elements=MAX_FIT_ELEMENTS):
    """Fit equal-class/equal-source geometry via a checked Cholesky solve.

    Whole-source averages have unit weight, so repeated identical rows cannot
    increase support. A class covariance is its population second moment about
    its prototype; their mean is shrunk toward trace(S)/d times the identity.
    Only training inputs belong here. No inverse, random completion, adaptive
    jitter, fallback model or differentiation through this fit is permitted.
    """
    checked_tensor(x, 2, 'correlated geometry training')
    if (x.dtype != torch.float32 or not 1 <= x.shape[1] <= 512
            or type(groups) not in (tuple, list) or len(x) != len(groups)
            or type(shrinkage) is not float or shrinkage not in SHRINKAGES
            or type(maximum_fit_elements) is not int
            or not 1 <= maximum_fit_elements <= MAX_FIT_ELEMENTS):
        raise ValueError('invalid correlated fitting profile')
    training_folds(labels, groups, classes)
    d = x.shape[1]
    if fit_envelope(len(x), d, classes, shrinkage) > maximum_fit_elements:
        raise ValueError('correlated fitting scratch budget exceeded')
    if shrinkage == 1.0:
        # Exactly the existing spherical formula: no dense covariance or factor.
        return geometry_fit(x, labels, groups, classes, shrinkage)
    xx = x.detach().double()
    means = []
    covariance = torch.zeros(d, d, dtype=torch.float64)
    for c in range(classes):
        buckets = {}
        for i, (label, group) in enumerate(zip(labels.tolist(), groups)):
            if label == c:
                buckets.setdefault(group, []).append(i)
        values = torch.stack([xx[buckets[g]].mean(0) for g in sorted(buckets)])
        mu = values.mean(0)
        centered = values - mu
        covariance.add_(centered.T @ centered, alpha=1 / (len(values) * classes))
        means.append(mu)
    center = torch.stack(means).mean(0)
    delta = torch.stack(means) - center
    # Absolute floor only regularizes singular/zero-data directions. It is fixed
    # in the protocol; never increased after a failed decomposition or bad score.
    spherical = covariance.diagonal().mean()
    ridge = max(float(shrinkage * spherical), VARIANCE_FLOOR)
    covariance.mul_(1 - shrinkage)
    covariance.diagonal().add_(ridge)
    if not torch.isfinite(covariance).all():
        raise ValueError('nonfinite pooled covariance')
    lower = torch.linalg.cholesky(covariance)
    weight = torch.cholesky_solve(delta.T, lower).T
    residual = covariance @ weight.T - delta.T
    scale = (covariance.abs().sum(1).max() * weight.abs().max()
             + delta.abs().max()).clamp_min(1)
    if (not torch.isfinite(weight).all() or not torch.isfinite(residual).all()
            or not torch.isfinite(scale) or float(residual.abs().max()/scale) > SOLVE_TOLERANCE):
        raise ValueError('correlated linear solve failed residual check')
    bias = -.5 * (delta * weight).sum(1)
    if not torch.isfinite(bias).all():
        raise ValueError('nonfinite correlated geometry bias')
    return weight, bias, center
