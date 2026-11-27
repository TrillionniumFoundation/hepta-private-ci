"""TRAIN-only estimators of the unchanged per-request joint objective."""

import numpy as np

from independent.accounting import BudgetExceeded
from independent.learning import CachedObjective, step_work
from independent.mixed_training import mixed_step_work


def weighted_work(n, k=12):
    return {"scalar_ops": 2 * n * k + 4 * n}


class WeightedObjective(CachedObjective):
    """Importance weights multiply whole requests, including their CE anchor.

    The log stays inside each request. The IID path retains the existing code.
    """

    row_weights = None

    def _policy_gradients_checked(self, p, q, y):
        if self.row_weights is None:
            return super()._policy_gradients_checked(p, q, y)
        w = np.asarray(self.row_weights)
        if w.shape != (len(y),) or not np.isfinite(w).all() or np.any(w <= 0):
            raise ValueError("positive finite per-request importance weights required")
        n, rows = len(p), np.arange(len(p))
        loss = (
            -self.ce_weight
            * np.mean(
                w
                * (
                    np.log(np.maximum(p[rows, y], 1e-300))
                    + np.log(np.maximum(q[rows, y], 1e-300))
                )
            )
            / 2
        )
        dt, di = p.copy(), q.copy()
        dt[rows, y] -= 1
        di[rows, y] -= 1
        dt *= (self.ce_weight * w / (2 * n))[:, None]
        di *= (self.ce_weight * w / (2 * n))[:, None]
        kernel = self.kernel[y]
        kp = np.einsum("nij,nj->ni", kernel, q)
        kq = np.einsum("ni,nij->nj", p, kernel)
        normalizer = np.sum(p * kp, axis=1)
        if self.arm == "A":
            value = normalizer
            dt -= p * (kp - value[:, None]) * (w / n)[:, None]
            di -= q * (kq - value[:, None]) * (w / n)[:, None]
        else:
            if np.any(normalizer <= 0) or not np.isfinite(normalizer).all():
                raise ValueError("nonpositive entropic normalizer")
            value = self.shift[y] - np.log(normalizer) / self.rho
            dt += (p * kp / normalizer[:, None] - p) * (w / (self.rho * n))[:, None]
            di += (q * kq / normalizer[:, None] - q) * (w / (self.rho * n))[:, None]
        return float(loss - np.mean(w * value)), dt, di

    def step(
        self, model, x, labels, lr, *, ledger=None, stage="search_train", full_mask=None
    ):
        extra = {} if self.row_weights is None else weighted_work(len(labels))
        if ledger is not None and extra:
            work = (
                step_work(self.dimensions, self.arm, len(labels))
                if full_mask is None
                else mixed_step_work(
                    self.dimensions,
                    self.arm,
                    len(labels),
                    int(np.count_nonzero(~full_mask)),
                )
            )
            if (
                ledger.estimate_kernel(**work) + ledger.estimate_kernel(**extra)
                > ledger.remaining_units
            ):
                raise BudgetExceeded(
                    "weighted complete update exceeds remaining budget"
                )
        loss = super().step(
            model, x, labels, lr, ledger=ledger, stage=stage, full_mask=full_mask
        )
        if ledger is not None and extra:
            ledger.charge_kernel(stage, "request_importance_weights", **extra)
        return loss


class Sampler:
    """Exactly 64 draws; fixed proportional strata and unbiased request weights."""

    def __init__(self, labels, kind, seed, batch_size=64):
        self.labels = np.asarray(labels)
        if kind not in ("iid", "stratified") or batch_size < 12:
            raise ValueError("unsupported sampler or undersized batch")
        self.kind, self.batch_size = kind, batch_size
        self.rng = np.random.default_rng(seed)
        self.views = np.random.default_rng(seed + 100000)
        self.members = [np.flatnonzero(self.labels == y) for y in range(12)]
        if any(not len(x) for x in self.members):
            raise ValueError("all twelve TRAIN target classes required")
        self.mass = np.array([len(x) for x in self.members]) / len(labels)
        quota = 1 + (batch_size - 12) * self.mass
        self.counts = np.floor(quota).astype(int)
        order = np.lexsort((np.arange(12), -(quota - self.counts)))
        self.counts[order[: batch_size - int(self.counts.sum())]] += 1

    def draw(self):
        if self.kind == "iid":
            idx = self.rng.integers(len(self.labels), size=self.batch_size)
            weights = None
        else:
            idx = np.concatenate(
                [
                    m[self.rng.integers(len(m), size=int(c))]
                    for m, c in zip(self.members, self.counts)
                ]
            )
            weights = (
                self.batch_size
                * self.mass[self.labels[idx]]
                / self.counts[self.labels[idx]]
            )
        return idx, weights, self.views.random(self.batch_size) < 0.5
