"""Useful-only continued training under declared operator-work budgets.

The shared encoder is evaluated once per update. Decoder-fixed additive and
entropic kernels are cached once; no unused objective or diagnostic is computed
by an arm. Inventories below are declared scalar/operator estimates, not hardware
FLOPs, elapsed time, memory traffic, or energy measurements.
"""

import functools

import numpy as np

from independent.accounting import BudgetExceeded
from data import outcome_table


ALIASES = {"S": "S", "H": "H", "A": "A", "N": "N",
           "supervised": "S", "anchor": "H", "anchor-only": "H",
           "additive": "A", "ndu": "N", "ndu_control": "N"}
CONTENT_PARAMETERS = ("encoder", "bias", "text", "text_bias", "image", "image_bias")


def _arm(value):
    try:
        return ALIASES[value]
    except (KeyError, TypeError) as error:
        raise ValueError("unknown efficient training arm") from error


def _geometry(dimensions, n):
    if (not isinstance(dimensions, (tuple, list)) or len(dimensions) != 4
            or any(type(v) is not int or v <= 0 for v in dimensions)
            or type(n) is not int or not 1 <= n <= 65536):
        raise ValueError("bounded model dimensions and batch required")
    return tuple(dimensions)


def _sum_work(*parts):
    result = {}
    for part in parts:
        for key, value in part.items():
            result[key] = result.get(key, 0) + int(value)
    return result


def objective_work(arm, n, k=12):
    """CE plus only the requested cached utility and its logit gradients."""
    arm = _arm(arm)
    if type(n) is not int or not 1 <= n <= 65536 or type(k) is not int or k < 2:
        raise ValueError("bounded objective batch required")
    result = {"scalar_ops": 6 * n * k + 6 * n, "compare_ops": 2 * n,
              "log_ops": 2 * n, "div_ops": 2 * n * k + 1}
    if arm in ("A", "N"):
        # Two batched matrix-vector products and the p dot (Kq) normalizer.
        result = _sum_work(result, {"macs": 2 * n * k * k,
            "scalar_ops": 8 * n * k + 3 * n,
            "div_ops": 2 * n * k + 1})
        if arm == "N":
            result = _sum_work(result, {"log_ops": n,
                "div_ops": 2 * n * k + n, "scalar_ops": n})
    return result


def value_work(arm, n, k=12):
    """Cached utility values without CE loss or unused derivative work."""
    arm = _arm(arm)
    if arm not in ("A", "N") or type(n) is not int or not 1 <= n <= 65536:
        raise ValueError("cached additive or entropic value batch required")
    result = {"macs": n * k * k, "scalar_ops": 2 * n * k - n}
    if arm == "N":
        result.update(log_ops=n, div_ops=n)
        result["scalar_ops"] += n
    return result


@functools.lru_cache(maxsize=128)
def _step_work(dimensions, arm, n):
    d, k, pixels, h = dimensions
    sizes = (d * h, h, h * k, k, h * k, k)
    elements, arrays = sum(sizes), len(sizes)
    forward = {"macs": n * (d * h + 2 * h * k),
        "scalar_ops": n * h + 6 * n * k - 2 * n,
        "compare_ops": 2 * n * (k - 1), "exp_ops": 2 * n * k,
        "div_ops": 2 * n * k, "tanh_ops": n * h}
    backward = {"macs": n * (d * h + 4 * h * k),
        "scalar_ops": 4 * n * h + (n - 1) * (h + 2 * k)}
    optimizer = {"scalar_ops": 13 * elements + 4 * arrays,
        "div_ops": 3 * elements + 1, "sqrt_ops": elements + 1,
        "pow_ops": 2 * arrays, "compare_ops": 2}
    # Input/gradient validation and fixed-decoder equality checks are charged.
    checks = {"compare_ops": 2 * n * d + 2 * elements}
    if arm in ("A", "N"):
        checks["compare_ops"] += k * pixels + pixels
    return _sum_work(forward, backward, optimizer, objective_work(arm, n, k), checks)


def step_work(dimensions, arm, n):
    """Flat inventory for one complete update, suitable for atomic preflight."""
    dims = _geometry(dimensions, n)
    return dict(_step_work(dims, _arm(arm), n))


def setup_work(dimensions, arm):
    """Decoder observation and cached objective preparation, never free work."""
    _, k, pixels, _ = _geometry(dimensions, 1)
    arm = _arm(arm)
    if arm in ("S", "H"):
        return {}
    decoded, distances, cells = k * pixels, k * k * pixels, k**3
    result = {"scalar_ops": 3 * decoded + 3 * distances + 8 * cells,
        "compare_ops": 2 * decoded + 2 * k * k + cells,
        "exp_ops": decoded, "div_ops": decoded + k * k}
    if arm == "N":
        result = _sum_work(result, {"scalar_ops": 2 * cells,
            "compare_ops": cells - k, "exp_ops": cells})
    return result


def _charge(ledger, stage, kernel, work, counts):
    if ledger is None:
        return
    units = ledger.estimate_kernel(**work)
    if units > ledger.remaining_units:
        raise BudgetExceeded(f"{ledger.arm}:{stage} whole {kernel} needs {units} units")
    ledger.charge_kernel(stage, kernel, **work, counts=counts)


class CachedObjective:
    """An immutable decoder-bound objective and one-forward optimizer step.

    ``policy_gradients`` is a pure mathematical operation; callers using it
    outside ``step`` must account for ``objective_work`` themselves. ``step``
    returns mean minimization loss (weighted CE minus declared utility).
    """

    def __init__(self, arm, model, *, rho=1.5, ce_anchor=0.2,
                 ledger=None, stage="search_setup"):
        self.arm = _arm(arm)
        if (type(rho) not in (int, float) or not np.isfinite(rho) or not 0 < rho <= 1e6
                or type(ce_anchor) not in (int, float) or not np.isfinite(ce_anchor)
                or not 0 < ce_anchor <= 1):
            raise ValueError("finite positive fixed risk and CE coefficients required")
        if hasattr(model, "ledger"):
            raise ValueError("plain JointModel required; automatic instrumentation would double charge")
        self.dimensions = tuple(model.dimensions)
        self.rho = float(rho)
        self.ce_weight = 1.0 if self.arm == "S" else float(ce_anchor)
        self.reward = self.kernel = self.shift = None
        self._decoder = None
        if self.arm in ("A", "N"):
            if self.dimensions[1:3] != (12, 192):
                raise ValueError("external observer requires twelve RGB8 scenes")
            _charge(ledger, stage, "objective_cache", setup_work(self.dimensions, self.arm),
                {"objective_cache_builds": 1, "decoder_elements": 12 * 192,
                 "objective_cache_cells": 12**3})
            self.reward = outcome_table(model)
            if self.reward.shape != (12, 12, 12) or not np.isfinite(self.reward).all():
                raise ValueError("invalid fixed external reward")
            self._decoder = {name: model.params[name].copy()
                             for name in ("decoder", "decoder_bias")}
            if self.arm == "N":
                self.shift = self.reward.min(axis=(1, 2))
                self.kernel = np.exp(-self.rho * (self.reward - self.shift[:, None, None]))
            else:
                self.kernel = self.reward
            for array in (self.reward, self.kernel, self.shift):
                if array is not None:
                    array.flags.writeable = False

    def _inputs(self, p, q, labels):
        p, q, y = np.asarray(p), np.asarray(q), np.asarray(labels)
        if (p.ndim != 2 or p.shape != q.shape or not 1 <= len(p) <= 65536
                or p.shape[1] != self.dimensions[1] or y.shape != (len(p),)
                or y.dtype.kind not in "iu" or np.any(y < 0) or np.any(y >= p.shape[1])
                or not np.isfinite(p).all() or not np.isfinite(q).all()
                or np.any(p < 0) or np.any(q < 0)
                or not np.allclose(p.sum(1), 1, rtol=0, atol=1e-10)
                or not np.allclose(q.sum(1), 1, rtol=0, atol=1e-10)):
            raise ValueError("finite matching categorical policies and labels required")
        return p, q, y

    def utility_values(self, p, q, labels, *, ledger=None, stage="critic_targets"):
        """Only fixed utility values, suitable for training-fold critic targets."""
        if self.kernel is None:
            raise ValueError("CE-only arm has no cached utility; observer work is separate")
        p, q, y = self._inputs(p, q, labels)
        _charge(ledger, stage, "cached_utility_values", value_work(self.arm, len(p), p.shape[1]),
                {"utility_value_calls": 1, "utility_value_rows": len(p)})
        kp = np.einsum("nij,nj->ni", self.kernel[y], q)
        normalizer = np.sum(p * kp, axis=1)
        if self.arm == "A":
            return normalizer
        if np.any(normalizer <= 0) or not np.isfinite(normalizer).all():
            raise ValueError("cached entropic normalizer outside finite support")
        return self.shift[y] - np.log(normalizer) / self.rho

    def policy_gradients(self, p, q, labels):
        p, q, y = self._inputs(p, q, labels)
        n, rows = len(p), np.arange(len(p))
        loss = -self.ce_weight * np.mean(np.log(np.maximum(p[rows, y], 1e-300))
                                      + np.log(np.maximum(q[rows, y], 1e-300))) / 2
        dt, di = p.copy(), q.copy()
        dt[rows, y] -= 1
        di[rows, y] -= 1
        dt *= self.ce_weight / (2 * n)
        di *= self.ce_weight / (2 * n)
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
                    raise ValueError("cached entropic normalizer outside finite support")
                value = self.shift[y] - np.log(normalizer) / self.rho
                dt += (p * kp / normalizer[:, None] - p) / (self.rho * n)
                di += (q * kq / normalizer[:, None] - q) / (self.rho * n)
            loss -= value.mean()
        return float(loss), dt, di

    def step(self, model, x, labels, lr, *, ledger=None, stage="search_train"):
        if tuple(model.dimensions) != self.dimensions or hasattr(model, "ledger"):
            raise ValueError("plain matching content model required")
        x, y = model._input(x), np.asarray(labels)
        if (y.shape != (len(x),) or y.dtype.kind not in "iu" or np.any(y < 0)
                or np.any(y >= self.dimensions[1]) or not np.isfinite(lr) or not 0 < lr <= 1):
            raise ValueError("valid labels and learning rate required")
        if self._decoder is not None and any(not np.array_equal(model.params[key], value)
                                            for key, value in self._decoder.items()):
            raise ValueError("decoder changed after objective cache preparation")
        counts = {"content_updates": 1, "optimizer_updates": 1,
            "model_forward_calls": 1, "model_forward_rows": len(x),
            "model_backward_calls": 1, "model_backward_rows": len(x),
            "training_examples": len(x), "cross_entropy_calls": 1}
        d, k, _, h = self.dimensions
        counts.update(model_forward_macs=len(x) * (d * h + 2 * h * k),
                      model_backward_macs=len(x) * (d * h + 4 * h * k),
                      optimizer_elements=d * h + h + 2 * h * k + 2 * k)
        if self.arm in ("A", "N"):
            counts.update(joint_utility_calls=1, joint_utility_cells=len(x) * self.dimensions[1]**2)
            counts[("additive" if self.arm == "A" else "entropic") + "_gradient_calls"] = 1
        _charge(ledger, stage, "efficient_" + self.arm,
                step_work(self.dimensions, self.arm, len(x)), counts)
        x, hidden, p, q = model._forward(x)
        loss, dt, di = self.policy_gradients(p, q, y)
        dh = (dt @ model.params["text"].T + di @ model.params["image"].T) * (1 - hidden * hidden)
        gradients = {"encoder": x.T @ dh, "bias": dh.sum(0),
            "text": hidden.T @ dt, "text_bias": dt.sum(0),
            "image": hidden.T @ di, "image_bias": di.sum(0)}
        model.apply_gradients(gradients, lr)
        return loss
