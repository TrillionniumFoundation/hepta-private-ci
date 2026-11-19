"""Declared operator-work budgets, never measured hardware FLOPs or latency.

Every arm receives the same cap and immutable price table, but may spend it on
different useful kernels and update counts. Unused diagnostics must not be run
to equalize counters. Shared initialization is attributed in full to every arm.
"""

from contextlib import contextmanager
import copy
import hashlib
import json
import re
from types import MappingProxyType


MAX_COUNT = 2**63 - 1
DEFAULT_PRICES = MappingProxyType({
    "macs": 2, "scalar_ops": 1, "compare_ops": 1, "div_ops": 4,
    "sqrt_ops": 4, "exp_ops": 8, "log_ops": 8, "tanh_ops": 8,
    "pow_ops": 8, "sort_items": 1,
})
DEFAULT_REQUIRED_STAGES = (
    "base_decoder", "base_pretrain", "base_validation",
    "search_train", "search_validation", "critic_fit",
)


class AccountingError(ValueError):
    pass


class BudgetExceeded(AccountingError):
    pass


class FairnessError(AccountingError):
    pass


def _count(value, name):
    if type(value) is not int or not 0 <= value <= MAX_COUNT:
        raise AccountingError(name + " must be a bounded nonnegative integer")
    return value


def _positive(value, name):
    if _count(value, name) == 0:
        raise AccountingError(name + " must be positive")
    return value


def _name(value, name):
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:/-]{0,95}", value):
        raise AccountingError("invalid " + name)
    return value


def _prices(value):
    result = dict(DEFAULT_PRICES if value is None else value)
    if set(result) != set(DEFAULT_PRICES):
        raise AccountingError("price table must name every declared operator")
    for key, number in result.items():
        _positive(number, key + " price")
    return result


class WorkLedger:
    """Admit kernels atomically against a frozen total declared-work cap.

    ``charge_kernel`` takes explicit operator keywords and an optional ``counts``
    mapping for geometry. A misspelled operator is a Python argument error.
    ``record`` is for externally derived units whose basis must be retained by
    the caller; automatic helpers use ``charge_kernel`` instead.
    """

    def __init__(self, arm, total_cap=MAX_COUNT, *, prices=None):
        self.arm = _name(arm, "arm")
        self._total_cap = _count(total_cap, "total cap")
        self._prices = MappingProxyType(_prices(prices))
        self._stages = {}
        self._kernels = {}
        self._active = []
        self._shared_tokens = set()
        self._shared = []
        self._frozen = False

    @property
    def total_cap(self):
        return self._total_cap

    @property
    def prices(self):
        return self._prices

    @property
    def consumed_units(self):
        return sum(row["consumed_units"] for row in self._stages.values())

    @property
    def remaining_units(self):
        return self.total_cap - self.consumed_units

    @property
    def totals(self):
        result = {"consumed_units": 0}
        for row in self._stages.values():
            for key, value in row.items():
                result[key] = result.get(key, 0) + value
        return result

    def _stage(self, stage):
        if stage is None:
            if not self._active:
                raise AccountingError("an explicit accounting stage is required")
            stage = self._active[-1]
        return _name(stage, "stage")

    @contextmanager
    def phase(self, stage):
        if self._frozen:
            raise AccountingError("ledger is frozen")
        self._active.append(self._stage(stage))
        try:
            yield self
        finally:
            self._active.pop()

    def record(self, stage=None, *, units=0, **counts):
        if self._frozen:
            raise AccountingError("ledger is frozen")
        stage = self._stage(stage)
        clean = {"consumed_units": _count(units, "units")}
        for key, value in counts.items():
            _name(key, "counter")
            if key == "consumed_units":
                raise AccountingError("consumed_units is derived from units")
            clean[key] = _count(value, key)
        if self.consumed_units + units > self.total_cap:
            raise BudgetExceeded(f"{self.arm}:{stage} needs {units} units; {self.remaining_units} remain")
        before = self._stages.get(stage, {})
        after = {**before}
        totals = self.totals
        for key, value in clean.items():
            _count(totals.get(key, 0) + value, "total " + key)
            after[key] = _count(before.get(key, 0) + value, "accumulated " + key)
        self._stages[stage] = after

    def estimate_kernel(self, *, macs=0, scalar_ops=0, compare_ops=0, div_ops=0,
                        sqrt_ops=0, exp_ops=0, log_ops=0, tanh_ops=0,
                        pow_ops=0, sort_items=0):
        operations = {key: value for key, value in locals().items() if key != "self"}
        for key, value in operations.items():
            _count(value, key)
        return _count(sum(value * self.prices[key] for key, value in operations.items()), "kernel units")

    def charge_kernel(self, stage=None, kernel="kernel", *, macs=0, scalar_ops=0,
                      compare_ops=0, div_ops=0, sqrt_ops=0, exp_ops=0,
                      log_ops=0, tanh_ops=0, pow_ops=0, sort_items=0, counts=None):
        stage = self._stage(stage)
        kernel = _name(kernel, "kernel")
        operations = {key: value for key, value in locals().items()
                      if key in DEFAULT_PRICES}
        units = self.estimate_kernel(**operations)
        clean = dict(counts or {})
        for key, value in operations.items():
            if "op_" + key in clean:
                raise AccountingError("operator counters are derived")
            clean["op_" + key] = value
        self.record(stage, units=units, **clean)
        row = self._kernels.setdefault(stage, {}).setdefault(kernel, {"calls": 0, "consumed_units": 0})
        row["calls"] += 1
        row["consumed_units"] += units
        for key, value in operations.items():
            row[key] = row.get(key, 0) + value
        return units

    def model_forward(self, stage=None, *, rows, input_dim, hidden, classes):
        n, d, h, k = (_positive(v, name) for v, name in
                      ((rows, "rows"), (input_dim, "input_dim"), (hidden, "hidden"), (classes, "classes")))
        macs = n * (d * h + 2 * h * k)
        return self.charge_kernel(stage, "model_forward", macs=macs,
            scalar_ops=n * h + 6 * n * k - 2 * n, compare_ops=2 * n * (k - 1),
            exp_ops=2 * n * k, div_ops=2 * n * k, tanh_ops=n * h,
            counts={"model_forward_calls": 1, "model_forward_rows": n, "model_forward_macs": macs})

    def model_backward(self, stage=None, *, rows, input_dim, hidden, classes):
        n, d, h, k = (_positive(v, name) for v, name in
                      ((rows, "rows"), (input_dim, "input_dim"), (hidden, "hidden"), (classes, "classes")))
        macs = n * (d * h + 4 * h * k)
        return self.charge_kernel(stage, "model_backward", macs=macs,
            scalar_ops=4 * n * h + (n - 1) * (h + 2 * k),
            counts={"model_backward_calls": 1, "model_backward_rows": n, "model_backward_macs": macs})

    def utility(self, stage=None, *, rows, text_classes, image_classes=None, profiles=1, units):
        n = _positive(rows, "rows")
        left = _positive(text_classes, "text classes")
        right = left if image_classes is None else _positive(image_classes, "image classes")
        return self.record(stage, units=_positive(units, "utility units"), joint_utility_calls=_positive(profiles, "profiles"),
                           joint_utility_cells=n * left * right * profiles)

    def optimizer(self, stage=None, *, parameter_sizes, decoder=False, content=True):
        sizes = tuple(_positive(value, "parameter size") for value in parameter_sizes)
        if not sizes or type(decoder) is not bool or type(content) is not bool:
            raise AccountingError("optimizer geometry and update roles required")
        elements, arrays = sum(sizes), len(sizes)
        return self.charge_kernel(stage, "adam_update", scalar_ops=13 * elements + 4 * arrays,
            div_ops=3 * elements + 1, sqrt_ops=elements + 1, pow_ops=2 * arrays,
            compare_ops=2, counts={"optimizer_updates": 1, "optimizer_elements": elements,
                "decoder_updates": int(decoder), "content_updates": int(content)})

    def decoder(self, stage=None, *, rows, pixels):
        elements = _positive(rows, "rows") * _positive(pixels, "pixels")
        return self.charge_kernel(stage, "decoder", scalar_ops=3 * elements,
            compare_ops=2 * elements, exp_ops=elements, div_ops=elements,
            counts={"decoder_calls": 1, "decoder_elements": elements})

    def critic_fit(self, stage=None, *, rows, classes):
        n, k = _positive(rows, "rows"), _positive(classes, "classes")
        width = 2 * k + 7
        # Ridge solve is a declared cubic work estimate; LAPACK details and
        # memory traffic are not claimed to equal this scalar inventory.
        return self.charge_kernel(stage, "critic_fit", macs=n * width * width + n * width,
            scalar_ops=6 * n * k + 6 * n * width + width**3,
            compare_ops=2 * n * k, div_ops=2 * n * k + 2 * n * width,
            log_ops=2 * n * k, sort_items=2 * n * k,
            counts={"critic_feature_calls": 1, "critic_feature_rows": n,
                    "critic_feature_elements": n * width, "critic_ridge_fits": 1,
                    "critic_ridge_rows": n, "critic_ridge_features": width,
                    "critic_ridge_gram_macs": n * width * width,
                    "critic_ridge_rhs_macs": n * width})

    def validation(self, stage=None, *, rows, selection=False):
        n = _positive(rows, "rows")
        if type(selection) is not bool:
            raise AccountingError("selection must be boolean")
        counts = {"validation_calls": 1, "validation_rows": n}
        if selection:
            counts.update(selection_validation_rows=n, selection_candidates=1)
        self.record(stage, **counts)

    def freeze(self):
        if self._active:
            raise AccountingError("cannot freeze an active phase")
        self._frozen = True

    def attribute_shared(self, source):
        if not isinstance(source, WorkLedger) or source is self:
            raise AccountingError("distinct shared source ledger required")
        if self._frozen or source._active:
            raise AccountingError("frozen recipient or active shared source")
        if dict(self.prices) != dict(source.prices):
            raise AccountingError("shared source price table differs")
        if source in self._shared_tokens:
            raise AccountingError("shared initialization already attributed")
        if source.consumed_units + self.consumed_units > self.total_cap:
            raise BudgetExceeded("shared initialization exceeds recipient cap")
        merged = copy.deepcopy(self._stages)
        for stage, row in source._stages.items():
            target = merged.setdefault(stage, {})
            for key, value in row.items():
                target[key] = _count(target.get(key, 0) + value, "shared accumulated " + key)
        kernels = copy.deepcopy(self._kernels)
        for stage, entries in source._kernels.items():
            for name, row in entries.items():
                target = kernels.setdefault(stage, {}).setdefault(name, {})
                for key, value in row.items():
                    target[key] = _count(target.get(key, 0) + value, "shared kernel " + key)
        totals = {}
        for row in merged.values():
            for key, value in row.items():
                totals[key] = _count(totals.get(key, 0) + value, "shared total " + key)
        source.freeze()
        self._stages, self._kernels = merged, kernels
        self._shared_tokens.add(source)
        self._shared.append({"source": source.arm, "consumed_units": source.consumed_units,
                             "sha256": source.digest()})

    def snapshot(self):
        return {"schema": "hepta.independent-work-ledger.v1", "arm": self.arm,
                "unit_profile": "declared-priced-operator-work-v1",
                "hardware_flops_or_latency": False, "total_cap": self.total_cap,
                "prices": dict(self.prices), "consumed_units": self.consumed_units,
                "remaining_units": self.remaining_units, "totals": self.totals,
                "stages": copy.deepcopy(self._stages), "kernels": copy.deepcopy(self._kernels),
                "shared_sources": copy.deepcopy(self._shared)}

    def digest(self):
        return hashlib.sha256(json.dumps(self.snapshot(), sort_keys=True,
                             separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def compare_budgets(ledgers, *, required_stages=DEFAULT_REQUIRED_STAGES):
    """Same cap/price admission, allowing cheap arms more useful updates."""
    rows = list(ledgers.values()) if isinstance(ledgers, dict) else list(ledgers)
    if len(rows) < 2 or any(not isinstance(row, WorkLedger) for row in rows):
        raise FairnessError("at least two work ledgers required")
    if len({row.arm for row in rows}) != len(rows):
        raise FairnessError("duplicate arm identities")
    if len({row.total_cap for row in rows}) != 1 or any(dict(row.prices) != dict(rows[0].prices) for row in rows):
        raise FairnessError("arms must have the same cap and operator prices")
    for row in rows:
        if row.consumed_units > row.total_cap:
            raise FairnessError("arm exceeds its cap: " + row.arm)
        stages = required_stages.get(row.arm) if isinstance(required_stages, dict) else required_stages
        if stages is None:
            raise FairnessError("required-stage policy missing for " + row.arm)
        for stage in stages:
            counts = row._stages.get(stage, {})
            if (counts.get("consumed_units", 0) <= 0
                    or not any(value > 0 for key, value in counts.items() if key != "consumed_units")):
                raise FairnessError("missing substantive stage " + stage + " for " + row.arm)
        if any(stage.startswith("base_") for stage in stages) and not row._shared:
            raise FairnessError("shared base was not attributed for " + row.arm)
    return {"same_total_cap": True, "same_operator_prices": True,
            "all_within_budget": True, "counter_equality_required": False,
            "total_cap": rows[0].total_cap,
            "consumed_units": {row.arm: row.consumed_units for row in rows},
            "remaining_units": {row.arm: row.remaining_units for row in rows}}


def compare_ledgers(ledgers, *, required_stages=DEFAULT_REQUIRED_STAGES):
    """Strict narrow work matching; never the efficient-baseline budget gate."""
    rows = list(ledgers.values()) if isinstance(ledgers, dict) else list(ledgers)
    result = compare_budgets(rows, required_stages=required_stages)
    if any(row._stages != rows[0]._stages or row._kernels != rows[0]._kernels for row in rows[1:]):
        raise FairnessError("stage/operator work differs; equal counters are only a narrow control")
    return {**result, "counter_equality_required": True, "equal_stage_and_kernel_counts": True}


def counted_model_class(base_class):
    """Instrument the unchanged finite model without installing global hooks.

    The caller supplies the exact base class used by the experiment. Tensor
    kernels are charged before execution; admissions can stop mid-update after
    earlier useful kernels have consumed budget. Callers should preflight the
    complete next update when deciding whether another update fits.
    """
    import numpy as np

    class CountedModel(base_class):
        def __init__(self, *args, ledger, **kwargs):
            if not isinstance(ledger, WorkLedger):
                raise AccountingError("WorkLedger required")
            self.ledger = ledger
            super().__init__(*args, **kwargs)

        def _forward(self, x):
            x = self._input(x)
            d, k, _, h = self.dimensions
            self.ledger.model_forward(rows=len(x), input_dim=d, hidden=h, classes=k)
            return super()._forward(x)

        def gradients(self, x, dtext, dimage):
            x, h, pt, pi = self._forward(x)
            dt, di = np.asarray(dtext), np.asarray(dimage)
            if (dt.shape != pt.shape or di.shape != pi.shape
                    or not np.isfinite(dt).all() or not np.isfinite(di).all()):
                raise ValueError("invalid logit gradients")
            d, k, _, hidden = self.dimensions
            self.ledger.model_backward(rows=len(x), input_dim=d, hidden=hidden, classes=k)
            dh = (dt @ self.params["text"].T + di @ self.params["image"].T) * (1 - h * h)
            return {"encoder": x.T @ dh, "bias": dh.sum(axis=0),
                    "text": h.T @ dt, "text_bias": dt.sum(axis=0),
                    "image": h.T @ di, "image_bias": di.sum(axis=0)}

        def apply_gradients(self, grads, lr):
            if not np.isfinite(lr) or not 0 < lr <= 1 or not grads:
                raise ValueError("invalid optimizer step")
            for key, grad in grads.items():
                array = np.asarray(grad, dtype=np.float64)
                if (key not in self.params or array.shape != self.params[key].shape
                        or not np.isfinite(array).all()):
                    raise ValueError("invalid parameter gradient")
            self.ledger.optimizer(parameter_sizes=[self.params[key].size for key in grads],
                decoder=any(key.startswith("decoder") for key in grads),
                content=any(not key.startswith("decoder") for key in grads))
            return super().apply_gradients(grads, lr)

        def supervised_step(self, x, labels, lr=0.003):
            pt, pi = self.forward(x)
            y = np.asarray(labels)
            if (y.shape != (len(pt),) or y.dtype.kind not in "iu"
                    or np.any(y < 0) or np.any(y >= self.dimensions[1])):
                raise ValueError("invalid labels")
            n, k = len(y), self.dimensions[1]
            self.ledger.charge_kernel(kernel="supervised_loss_and_gradient",
                scalar_ops=4 * n + 1, compare_ops=2 * n, log_ops=2 * n,
                div_ops=2 * n * k + 2, counts={"supervised_rows": n})
            rows = np.arange(n)
            loss = -np.mean(np.log(np.maximum(pt[rows, y], 1e-300))
                            + np.log(np.maximum(pi[rows, y], 1e-300))) / 2
            dt, di = pt.copy(), pi.copy()
            dt[rows, y] -= 1
            di[rows, y] -= 1
            self.train_step(x, dt / (2 * n), di / (2 * n), lr)
            return float(loss)

        def utility_step(self, x, rewards, rho=1.0, lr=0.003, *, utility_units=None):
            if utility_units is None:
                raise AccountingError("utility_step requires frozen actual-kernel utility_units")
            x = self._input(x)
            self.ledger.utility(rows=len(x), text_classes=self.dimensions[1], units=utility_units)
            return super().utility_step(x, rewards, rho, lr)

        def decode_images(self, class_ids):
            ids = np.asarray(class_ids)
            if (ids.ndim != 1 or not 1 <= len(ids) <= 65536 or ids.dtype.kind not in "iu"
                    or np.any(ids < 0) or np.any(ids >= self.dimensions[1])):
                raise ValueError("invalid image content ids")
            self.ledger.decoder(rows=len(ids), pixels=self.dimensions[2])
            return super().decode_images(ids)

        def fit_decoder(self, target_pixels, steps=300, lr=0.05):
            target = np.asarray(target_pixels, dtype=np.float64)
            if (target.shape != (self.dimensions[1], self.dimensions[2])
                    or not np.isfinite(target).all() or np.any(target < 0) or np.any(target > 1)
                    or type(steps) is not int or not 1 <= steps <= 10000):
                raise ValueError("invalid decoder training data")
            elements, pixels = target.size, self.dimensions[2]
            for _ in range(steps):
                prediction = self.decode_images(np.arange(self.dimensions[1]))
                self.ledger.charge_kernel(kernel="decoder_gradient",
                    scalar_ops=elements + elements - pixels, div_ops=elements)
                grad = (prediction - target) / target.size
                self.apply_gradients({"decoder": grad, "decoder_bias": grad.sum(axis=0)}, lr)
            prediction = self.decode_images(np.arange(self.dimensions[1]))
            self.ledger.charge_kernel(kernel="decoder_mse", scalar_ops=3 * elements - 1, div_ops=1)
            return float(np.mean((prediction - target) ** 2))

        def clone(self, *, ledger=None):
            out = type(self)(*self.dimensions[:3], hidden=self.dimensions[3],
                             ledger=self.ledger if ledger is None else ledger)
            out.params = {name: value.copy() for name, value in self.params.items()}
            return out

        @classmethod
        def load(cls, path, *, ledger):
            loaded = base_class.load(path)
            out = cls(*loaded.dimensions[:3], hidden=loaded.dimensions[3], ledger=ledger)
            out.params = {name: value.copy() for name, value in loaded.params.items()}
            return out

    return CountedModel
