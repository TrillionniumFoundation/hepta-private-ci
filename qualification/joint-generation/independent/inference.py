"""Frozen full/thumbnail inference with actual, pre-admitted operator work.

The thumbnail encoder is an exact linear folding of the original encoder, not
a second trained model. Operator inventories use the declared accounting price
table; they do not claim measured hardware FLOPs, latency, or memory traffic.
"""

from types import MappingProxyType

import numpy as np

from control import Controller
from model import softmax
from independent.accounting import BudgetExceeded, WorkLedger


def units(work, ledger=None):
    """Price a flat operator inventory using the caller's frozen prices."""
    ledger = WorkLedger("inference-estimate") if ledger is None else ledger
    if not isinstance(ledger, WorkLedger):
        raise TypeError("WorkLedger required")
    return ledger.estimate_kernel(**work)


def _rows(value):
    if type(value) is not int or not 1 <= value <= 65536:
        raise ValueError("bounded positive row count required")
    return value


def _sum_work(*work):
    result = {}
    for row in work:
        for key, value in row.items():
            result[key] = result.get(key, 0) + value
    return result


class FrozenGenerator:
    """Read-only shared content weights, with optional cached low-view folding.

    A full-only baseline passes ``prepare_low=False`` to avoid unused folding.
    If that instance later receives a low request, preparation is admitted and
    charged once before its first low pass. Preparation is separate build work.
    """

    def __init__(self, model, ledger=None, stage="prepare", *, prepare_low=True):
        if (tuple(model.dimensions[:3]) != (202, 12, 192)
                or len(model.dimensions) != 4 or not 1 <= model.dimensions[3] <= 512
                or type(prepare_low) is not bool):
            raise ValueError("expected the bounded RGB8/instruction10 model")
        if ledger is not None and not isinstance(ledger, WorkLedger):
            raise TypeError("WorkLedger required")
        self.dimensions = tuple(model.dimensions)
        self._ledger = ledger
        self._prepare_stage = stage
        parameters = {key: np.array(value, dtype=np.float64, copy=True)
                      for key, value in model.params.items()}
        d, k, pixels, h = self.dimensions
        shapes = {"encoder": (d, h), "bias": (h,), "text": (h, k),
                  "text_bias": (k,), "image": (h, k), "image_bias": (k,),
                  "decoder": (k, pixels), "decoder_bias": (pixels,)}
        if (set(parameters) != set(shapes)
                or any(value.shape != shapes[key] or not np.isfinite(value).all()
                       for key, value in parameters.items())):
            raise ValueError("invalid frozen content parameters")
        for value in parameters.values():
            value.flags.writeable = False
        self.params = MappingProxyType(parameters)
        self._folded_encoder = None
        if prepare_low:
            self._prepare(ledger)

    @property
    def prepared_low(self):
        return self._folded_encoder is not None

    def _ledger_for(self, ledger):
        ledger = self._ledger if ledger is None else ledger
        if ledger is not None and not isinstance(ledger, WorkLedger):
            raise TypeError("WorkLedger required")
        return ledger

    def _admit(self, work, ledger, stage):
        if ledger is not None and units(work, ledger) > ledger.remaining_units:
            raise BudgetExceeded("inference:" + str(stage) + " exceeds remaining work budget")

    def prepare_work(self):
        """Three additions for each of the 48×hidden folded coefficients."""
        return {"scalar_ops": 144 * self.dimensions[3]}

    def _model_work(self, n, input_dim):
        n = _rows(n)
        _, k, _, h = self.dimensions
        return {"macs": n * (input_dim * h + 2 * h * k),
                "scalar_ops": n * h + 6 * n * k - 2 * n,
                "compare_ops": 2 * n * (k - 1), "exp_ops": 2 * n * k,
                "div_ops": 2 * n * k, "tanh_ops": n * h}

    def full_work(self, n):
        return self._model_work(n, 202)

    def thumbnail_work(self, n):
        n = _rows(n)
        return {"scalar_ops": 144 * n, "div_ops": 48 * n}

    def low_work(self, n):
        """One 2×2 thumbnail reduction and one actual 58-input forward."""
        return _sum_work(self.thumbnail_work(n), self._model_work(n, 58))

    def critic_work(self, n, critic=None):
        """Declared arithmetic for Controller features, ridge prediction/decision.

        Shape/domain validation and memory copies follow the same unpriced
        metadata/memory boundary as WorkLedger.model_forward. Log constants,
        feature divisions, sorting and decision comparisons are included.
        """
        n = _rows(n)
        if critic is not None and not isinstance(critic, Controller):
            from independent.gain_head import AffineGainHead
            if not isinstance(critic, AffineGainHead) or critic.hidden_dim != self.dimensions[3]:
                raise ValueError("compatible affine gain head required")
            return critic.work(n)
        k = self.dimensions[1]
        width = 2 * k + 7
        return {"macs": n * width, "scalar_ops": n * (6 * k + width + 3),
                "compare_ops": n * (2 * k + 4), "div_ops": n * (width + 2),
                "log_ops": n * (2 * k + 2), "sort_items": 2 * n * k}

    def _prepare(self, ledger):
        if self.prepared_low:
            return
        self._admit(self.prepare_work(), ledger, self._prepare_stage)
        if ledger is not None:
            ledger.charge_kernel(self._prepare_stage, "thumbnail_encoder_fold",
                **self.prepare_work(), counts={"thumbnail_fold_calls": 1})
        hidden = self.dimensions[3]
        image_weights = self.params["encoder"][:192].reshape(4, 2, 4, 2, 3, hidden)
        folded = image_weights.sum(axis=(1, 3)).reshape(48, hidden)
        self._folded_encoder = np.concatenate((folded, self.params["encoder"][192:]), axis=0)
        self._folded_encoder.flags.writeable = False

    def _input(self, x):
        value = np.asarray(x, dtype=np.float64)
        if (value.ndim != 2 or not 1 <= len(value) <= 65536
                or value.shape[1] != 202 or not np.isfinite(value).all()):
            raise ValueError("expected finite [N,202] full RGB/instruction input")
        return value

    def _content(self, x, encoder, *, return_state=False):
        hidden = np.tanh(x @ encoder + self.params["bias"])
        result = (softmax(hidden @ self.params["text"] + self.params["text_bias"]),
                  softmax(hidden @ self.params["image"] + self.params["image_bias"]))
        return (*result, hidden) if return_state else result

    def forward_full(self, x_full, ledger=None, stage="inference"):
        x = self._input(x_full)
        ledger = self._ledger_for(ledger)
        self._admit(self.full_work(len(x)), ledger, stage)
        if ledger is not None:
            ledger.model_forward(stage, rows=len(x), input_dim=202,
                                 hidden=self.dimensions[3], classes=self.dimensions[1])
        return self._content(x, self.params["encoder"])

    def forward_low(self, x_full, ledger=None, stage="inference"):
        return self.forward_low_state(x_full, ledger, stage)[:2]

    def forward_low_state(self, x_full, ledger=None, stage="inference"):
        """Return p/q and the same admitted low encoder's post-tanh state."""
        x = self._input(x_full)
        ledger = self._ledger_for(ledger)
        work = self.low_work(len(x))
        if not self.prepared_low:
            work = _sum_work(work, self.prepare_work())
        self._admit(work, ledger, stage)
        self._prepare(ledger)
        if ledger is not None:
            ledger.charge_kernel(stage, "thumbnail_kernel", **self.thumbnail_work(len(x)),
                                 counts={"thumbnail_calls": 1, "thumbnail_rows": len(x)})
        thumbnail = x[:, :192].reshape(len(x), 4, 2, 4, 2, 3).mean(axis=(2, 4))
        packed = np.concatenate((thumbnail.reshape(len(x), 48), x[:, 192:]), axis=1)
        if ledger is not None:
            ledger.model_forward(stage, rows=len(x), input_dim=58,
                                 hidden=self.dimensions[3], classes=self.dimensions[1])
        return self._content(packed, self._folded_encoder, return_state=True)

    def continuation(self, x_full, critic, price=0.02, ledger=None, stage="inference"):
        """One cheap low pass, a charged critic, and at most one full pass.

        ``price`` retains the root Controller's extra-full-pass price. The
        evaluator must separately price the complete recorded inference work.
        Insufficient optional budget stops after low; mandatory work rejects.
        """
        x = self._input(x_full)
        if (len(x) != 1 or getattr(critic, "classes", None) != self.dimensions[1]
                or type(price) not in (int, float) or not np.isfinite(price) or price < 0):
            raise ValueError("one request, compatible critic and finite nonnegative price required")
        critic_work = self.critic_work(1, critic)
        affine = not isinstance(critic, Controller)
        ledger = self._ledger_for(ledger)
        required = _sum_work(self.low_work(1), critic_work)
        if not self.prepared_low:
            required = _sum_work(required, self.prepare_work())
        self._admit(required, ledger, stage)
        before = 0 if ledger is None else ledger.consumed_units
        if affine:
            p, q, hidden = self.forward_low_state(x, ledger, stage)
        else:
            p, q = self.forward_low(x, ledger, stage)
        if ledger is not None:
            ledger.charge_kernel(stage, "continuation_critic", **critic_work,
                                 counts={"critic_decisions": 1, "critic_rows": 1})
        available = int(ledger is None or ledger.remaining_units >= units(self.full_work(1), ledger))
        if affine:
            wanted = bool(critic.predict_state(hidden, x[:, 192:])[0] > price)
            continued = bool(available and wanted)
        else:
            continued = bool(critic.decide(p, q, remaining_steps=available, price=price)[0])
        if continued:
            p, q = self.forward_full(x, ledger, stage)
        return p, q, {"continued": continued, "model_forwards": 1 + int(continued),
                      "low_forwards": 1, "full_forwards": int(continued),
                      "charged_units": None if ledger is None else ledger.consumed_units - before,
                      "price_per_extra_full_pass": price}
