"""Compact public-only value inputs and the exact frozen admission calculation."""

import numpy as np

from ...next_20261025.native_h2.admission import hidden
from ...next_20261025.native_h2.qualification import calibrated, probabilities


Q = 1 << 24
FEATURE_SCHEMA = 'hepta.advance.public-semantic-admission-features.v1'
DIM = 109


def absence(public):
    extra = np.asarray(public)[:, 672:762]
    return (extra[:, 66:68].sum(1) == 0) & (extra[:, 70:72].sum(1) == 0)


def public_proxy(public):
    extra = np.asarray(public)[:, 672:762]
    image = extra[:, 20:40].reshape(-1, 2, 10).argmax(-1)
    caption = extra[:, 40:60].reshape(-1, 2, 10).argmax(-1)
    valid = extra[:, 89] > .5
    disagreement = (image != caption).mean(1)
    return np.where(valid, 1 - disagreement, -1.)


def encode(public, horizon, predictor, calibration, *, prior_public_utility=None):
    public = np.asarray(public, dtype=np.float32)
    if public.ndim != 2 or public.shape[1] != 763 or not np.isfinite(public).all():
        raise ValueError('Exactly 763 finite public features required')
    if horizon not in (1, 2):
        raise ValueError('Only the existing H1/H2 action system is supported')
    h = hidden(predictor, public, horizon)
    raw = probabilities(predictor, h, horizon)
    absent = absence(public)
    confidence = calibrated(calibration, raw, absent[:, None], horizon, np.arange(5))
    allowed = confidence >= .75
    if horizon == 1:
        allowed[:, 1] = False
    extra = public[:, 672:762].astype(np.float64)
    pair_products = extra[:, 72:78].reshape(-1, 3, 2).prod(-1)
    joint_relation = pair_products * extra[:, 78:79]
    if prior_public_utility is None:
        prior = public_proxy(public) if horizon == 1 else np.zeros(len(public))
    else:
        prior = np.broadcast_to(np.asarray(prior_public_utility, dtype=np.float64), (len(public),))
    if not np.isfinite(prior).all() or (np.abs(prior) > 1).any():
        raise ValueError('The observed public utility must be finite in [-1,1]')
    # 90 original semantic coordinates + 3 pair products + 3 relation products
    # + raw 5 + calibrated 5 + observed prior 1 + absent 1 + horizon 1 = 109.
    x = np.column_stack((extra, pair_products, joint_relation, raw, confidence,
                         prior, absent.astype(np.float64), np.full(len(public), horizon / 2)))
    if x.shape != (len(public), DIM) or not np.isfinite(x).all() or (np.abs(x) > 1.000001).any():
        raise ValueError('Bounded public feature ABI mismatch')
    # Native transport and offline fit use identical Q24 inputs.
    x = np.rint(x * Q).astype(np.int64).astype(np.float64) / Q
    return x, allowed, confidence
