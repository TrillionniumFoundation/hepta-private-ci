"""Known immediate costs are exact; only post-action continuation is learned."""

import numpy as np

from tools.hcsn.round8_20261031.value_calibration.head import CalibratedHead, fit


class CostFactoredHead(CalibratedHead):
    def predict(self, joined, stop):
        joined = np.asarray(joined)
        q = super().predict(joined, stop)
        return q + joined[..., 16, None] - joined[..., 13:17]


def fit_continuation(joined, target, legal, weights, seed, *, hidden, iterations, direct=False):
    # q + cost(action) - cost(STOP) has advantage E[V_next] - current quality.
    # STOP stays exactly anchored. Illegal entries remain excluded by the mask.
    factored = target + joined[..., 13:17] - joined[..., 16, None]
    if direct:
        # All 17 rows are algebraically identical in this deterministic control.
        # Collapsing duplicates preserves the full weighted objective exactly.
        assert np.max(abs(joined - joined[:, :1])) == 0
        assert np.allclose(target, target[:, :1], atol=0, rtol=0)
        joined, factored = joined[:, :1], factored[:, :1]
    head, metadata = fit(joined, factored, legal, weights, seed, hidden=hidden, iterations=iterations)
    metadata.update({"decoder": "exact action cost plus learned continuation", "direct_duplicate_rows_collapsed": direct})
    return CostFactoredHead(**head.record()), metadata


class PreservedNominalHead:
    """A total executable policy: old head on known input rows, new head elsewhere."""

    def __init__(self, old, new, support):
        self.old, self.new = old, new
        self.support = frozenset(tuple(row) for row in support)

    def predict(self, joined, stop):
        joined, stop = np.asarray(joined), np.asarray(stop)
        if joined.ndim == 1:
            head = self.old if tuple(joined[:18]) in self.support else self.new
            return head.predict(joined, stop)
        q = self.new.predict(joined, stop)
        # Public inputs repeat across latent states; membership does not use z.
        nominal = np.array([tuple(row) in self.support for row in joined[:, 0, :18]])
        if nominal.any():
            q[nominal] = self.old.predict(joined[nominal], stop[nominal])
        return q
