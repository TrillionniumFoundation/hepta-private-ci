"""Original average-marginal anchor and fixed decoded categorical utilities."""

import numpy as np

from content_joint.native_model import KEYS
from content_joint.work import independent_cache_work, native_cache_work, native_step_work
from independent.learning import CachedObjective
from model import softmax


class IndependentObjective(CachedObjective):
    """Unchanged old equations, exposing already computed loss components."""

    def __init__(self, arm, model, reward, optimizer=None, ledger=None):
        if arm not in ("S", "H", "A", "N") or reward.shape != (12, 12, 12):
            raise ValueError("fixed arm and actual decoded R required")
        self.arm, self.rho = arm, 1.5
        self.ce_weight = 1. if arm == "S" else .2
        self.optimizer, self.dimensions = optimizer, tuple(model.dimensions)
        self.reward = reward if arm in ("A", "N") else None
        self.shift = reward.min(axis=(1, 2)) if arm == "N" else None
        self.kernel = (np.exp(-self.rho * (reward - self.shift[:, None, None]))
                       if arm == "N" else self.reward)
        self._decoder = ({key: model.params[key].copy() for key in ("decoder", "decoder_bias")}
                         if arm in ("A", "N") else None)
        self.last = None
        self.ledger = ledger
        if ledger is not None:
            ledger.charge_kernel("independent_objective_setup", "original_kernel_cache",
                                 **independent_cache_work(arm), counts={"objective_cache_builds": 1})

    def _policy_gradients_checked(self, p, q, y):
        n, rows = len(p), np.arange(len(p))
        logs = (np.log(np.maximum(p[rows, y], 1e-300))
                + np.log(np.maximum(q[rows, y], 1e-300)))
        meanlogs = np.mean(logs)
        loss = -self.ce_weight * meanlogs / 2
        dt, di = p.copy(), q.copy()
        dt[rows, y] -= 1
        di[rows, y] -= 1
        dt *= self.ce_weight / (2 * n)
        di *= self.ce_weight / (2 * n)
        value = None
        if self.kernel is not None:
            kernel = self.kernel[y]
            kp = np.einsum("nij,nj->ni", kernel, q)
            kq = np.einsum("ni,nij->nj", p, kernel)
            normalizer = np.sum(p * kp, axis=1)
            if self.arm == "A":
                value = normalizer
                dt -= p * (kp - value[:, None]) / n
                di -= q * (kq - value[:, None]) / n
            else:
                if np.any(normalizer <= 0) or not np.isfinite(normalizer).all():
                    raise ValueError("invalid original entropic normalizer")
                value = self.shift[y] - np.log(normalizer) / self.rho
                dt += (p * kp / normalizer[:, None] - p) / (self.rho * n)
                di += (q * kq / normalizer[:, None] - q) / (self.rho * n)
            utility = float(value.mean())
            loss -= utility
        else:
            utility = None
        if self.ledger is not None:
            self.ledger.charge_kernel("loss_evidence", "unweighted_anchor", scalar_ops=1, div_ops=1)
        self.last = dict(loss=float(loss), ce=float(-meanlogs / 2),
                         utility=utility,
                         p=p, q=q, labels=y)
        return float(loss), dt, di


class NativeObjective:
    def __init__(self, arm, model, reward, optimizer=None, ledger=None):
        if arm not in ("S", "H", "A", "N") or reward.shape != (12, 12, 12):
            raise ValueError("fixed arm and original decoded R required")
        self.arm, self.rho = arm, 1.5
        self.ce_weight = 1.0 if arm == "S" else .2
        self.optimizer = optimizer
        self.reward = np.diagonal(reward, axis1=1, axis2=2).copy()
        self.shift = self.reward.min(1) if arm == "N" else None
        self.kernel = (np.exp(-self.rho * (self.reward - self.shift[:, None]))
                       if arm == "N" else None)
        self.decoder = {key: model.params[key].copy() for key in ("decoder", "decoder_bias")}
        self.last = None
        if ledger is not None:
            ledger.charge_kernel("native_objective_setup", "diagonal_cache",
                                 **native_cache_work(arm), counts={"native_objective_cache_builds": 1})

    def policy(self, s, labels):
        n, rows = len(s), np.arange(len(s))
        y = np.asarray(labels)
        if (s.shape != (n, 12) or y.shape != (n,) or y.dtype.kind not in "iu"
                or np.any(y < 0) or np.any(y >= 12) or not np.isfinite(s).all()
                or np.any(s < 0) or not np.allclose(s.sum(1), 1, atol=1e-10, rtol=0)):
            raise ValueError("finite normalized native law and positive target support required")
        return self._policy_checked(s, y)

    def _policy_checked(self, s, y):
        n, rows = len(s), np.arange(len(s))
        if np.any(s[rows, y] <= 1e-300):
            raise ValueError("native target support underflow")
        ce = -np.mean(np.log(s[rows, y]))
        gradient = s.copy()
        gradient[rows, y] -= 1
        gradient *= self.ce_weight / n
        value = None
        if self.arm == "A":
            r = self.reward[y]
            value = np.sum(s * r, axis=1)
            gradient -= s * (r - value[:, None]) / n
        elif self.arm == "N":
            kernel = self.kernel[y]
            normalizer = np.sum(s * kernel, axis=1)
            if np.any(normalizer <= 0) or not np.isfinite(normalizer).all():
                raise ValueError("invalid diagonal entropic normalizer")
            value = self.shift[y] - np.log(normalizer) / self.rho
            gradient += (s * kernel / normalizer[:, None] - s) / (self.rho * n)
        utility = None if value is None else float(value.mean())
        loss = self.ce_weight * ce - (0 if utility is None else utility)
        self.last = dict(loss=float(loss), ce=float(ce),
                         utility=utility,
                         s=s, labels=y)
        return float(loss), gradient

    def step(self, model, x, labels, lr, *, ledger):
        x, y = model._input(x), np.asarray(labels)
        if (y.shape != (len(x),) or y.dtype.kind not in "iu" or np.any(y < 0)
                or np.any(y >= 12) or not np.isfinite(lr) or not 0 < lr <= 1):
            raise ValueError("valid labels/LR required")
        if self.arm in ("A", "N") and any(not np.array_equal(model.params[k], v)
                                           for k, v in self.decoder.items()):
            raise ValueError("decoder changed")
        n = len(x)
        ledger.charge_kernel("search_train", "native_" + self.arm,
            **native_step_work(self.arm, n), counts={"content_updates": 1,
            "model_forward_calls": 1, "model_forward_rows": n,
            "model_backward_calls": 1, "model_backward_rows": n,
            "optimizer_updates": 1, "optimizer_elements": 6892,
            "training_examples": n, "cross_entropy_calls": 1,
            "model_forward_macs": n * 6848, "model_backward_macs": n * 7232,
            "categorical_utility_cells": n * 12 if self.arm in ("A", "N") else 0})
        loss, gradients = self.gradients(model, x, y)
        self.optimizer.apply_gradients(model, gradients, lr)
        return loss

    def gradients(self, model, x, y):
        """Pure equations for numerical verification; caller accounts the work."""
        hidden = np.tanh(x @ model.params["encoder"] + model.params["bias"])
        s = softmax(hidden @ model.params["shared"] + model.params["shared_bias"])
        loss, ds = self._policy_checked(s, y)
        dh = (ds @ model.params["shared"].T) * (1 - hidden * hidden)
        gradients = dict(encoder=x.T @ dh, bias=dh.sum(0),
                         shared=hidden.T @ ds, shared_bias=ds.sum(0))
        return loss, gradients
