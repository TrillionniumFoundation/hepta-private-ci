"""Exact-real-arithmetic encoder folding for already expanded low training rows.

Only adaptation opts in. Encoder parameters remain [202, hidden]; folds are
rebuilt from the current weights each update. Floating reduction order changes.
Memory gathering/scattering is covered by actual CPU, not invented FLOP prices.
"""

import functools

import numpy as np


KERNEL_PROFILE = "folded-mixed-encoder-v1"


def _geometry(dimensions, n):
    if (not isinstance(dimensions, (tuple, list)) or len(dimensions) != 4
            or tuple(dimensions[:3]) != (202, 12, 192)
            or any(type(v) is not int for v in dimensions)
            or not 1 <= dimensions[3] <= 512
            or type(n) is not int or not 1 <= n <= 65536):
        raise ValueError("bounded RGB8/instruction10 training geometry required")
    return tuple(dimensions)


@functools.lru_cache(maxsize=512)
def _work(dimensions, arm, n, low_rows):
    from independent.learning import step_work

    result = step_work(dimensions, arm, n)
    h = dimensions[3]
    result["scalar_ops"] += n  # Boolean negation for the low-row index mask.
    result["compare_ops"] += 2 * n  # Two boolean index scans.
    if low_rows is None:
        # Componentwise envelope, safe for any positive operator prices. This
        # combination need not occur in a real step and is never charged.
        result["scalar_ops"] += 144 * h + (202 * h if n > 1 else 0)
        result["compare_ops"] += 144 * n
    elif low_rows:
        result["macs"] -= 288 * h * low_rows
        result["scalar_ops"] += 144 * h  # Fresh four-pixel encoder folding.
        result["compare_ops"] += 144 * low_rows  # Three non-anchor replicas.
        if low_rows < n:
            result["scalar_ops"] += 202 * h  # Merge full/low encoder gradients.
    return result


def mixed_step_work(dimensions, arm, n, low_rows=None):
    """Actual known-mask work, or a reservation-only envelope when omitted."""
    dimensions = _geometry(dimensions, n)
    if low_rows is not None and (type(low_rows) is not int or not 0 <= low_rows <= n):
        raise ValueError("integer low-row count within the batch required")
    return dict(_work(dimensions, arm, n, low_rows))


class MixedEncoderBatch:
    """Checked dense x plus bool full-view mask; no encoder/input gradients twice.

    The caller performs its existing finite x scan before constructing this
    helper. A low row must be the exact expanded 2x2-block representation already
    stored in the training fold. Arbitrary full images are never silently lowed.
    """

    def __init__(self, checked_x, full_mask):
        self.x = np.asarray(checked_x)
        mask = np.asarray(full_mask)
        if (self.x.ndim != 2 or self.x.shape[1] != 202 or self.x.dtype != np.float64
                or not 1 <= len(self.x) <= 65536 or mask.dtype.kind != "b"
                or mask.shape != (len(self.x),)):
            raise ValueError("checked float64 [n,202] input and bool [n] full mask required")
        self.full_indices = np.flatnonzero(mask)
        self.low_indices = np.flatnonzero(~mask)
        self.full_count, self.low_count = len(self.full_indices), len(self.low_indices)
        self.low = None
        if self.low_count:
            rows = self.x[self.low_indices]
            blocks = rows[:, :192].reshape(self.low_count, 4, 2, 4, 2, 3)
            anchor = blocks[:, :, 0, :, 0, :]
            if not all(np.array_equal(blocks[:, :, a, :, b, :], anchor)
                       for a, b in ((0, 1), (1, 0), (1, 1))):
                raise ValueError("low training rows must contain exact repeated 2x2 blocks")
            self.low = np.concatenate((anchor.reshape(self.low_count, 48), rows[:, 192:]), axis=1)

    def preactivation(self, encoder, bias):
        if not self.low_count:
            return self.x @ encoder + bias
        h = encoder.shape[1]
        result = np.empty((len(self.x), h), dtype=np.float64)
        if self.full_count:
            result[self.full_indices] = self.x[self.full_indices] @ encoder
        pixels = encoder[:192].reshape(4, 2, 4, 2, 3, h)
        folded = np.concatenate((pixels.sum(axis=(1, 3)).reshape(48, h), encoder[192:]), axis=0)
        result[self.low_indices] = self.low @ folded
        result += bias
        return result

    def hidden(self, encoder, bias):
        return np.tanh(self.preactivation(encoder, bias))

    def encoder_gradient(self, dh):
        if not self.low_count:
            return self.x.T @ dh
        low = self.low.T @ dh[self.low_indices]
        pixels = low[:48].reshape(4, 4, 3, dh.shape[1]).repeat(2, axis=0).repeat(2, axis=1)
        expanded = np.concatenate((pixels.reshape(192, dh.shape[1]), low[48:]), axis=0)
        if self.full_count:
            return self.x[self.full_indices].T @ dh[self.full_indices] + expanded
        return expanded
