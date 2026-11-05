"""Trained bit-valued memory with a portable, exact integer readout.

The artifact is a 24-byte ``<8sHHHHII`` header followed by little-endian
int16 W1 and W2 in C order. Inference uses Q12 inputs/weights, int64 sums,
rounds hidden preactivations with floor((sum + 2048) / 4096), clips to
[-4096, 4096], and emits bit one for nonnegative Q24 logits. Training uses
floating-point hard-tanh/BCE/Adam; evaluation always uses the saved integer
representation. Its source/parent admission is the owner's responsibility.
"""

from dataclasses import dataclass
import hashlib
from pathlib import Path
import struct
import time

import numpy as np


SCALE = 4096
MAGIC = b"HMCELL3\0"
HEADER = struct.Struct("<8sHHHHII")
MAX_INPUTS = 512
MAX_HIDDEN = 1024
MAX_BITS = 32
MAX_ROWS = 1_000_000


def q12_inputs(values):
    """Explicitly quantize normalized finite inputs; never silently wrap."""
    array = np.asarray(values)
    if array.dtype.kind not in "iuf" or array.ndim != 2:
        raise ValueError("inputs must be a finite numeric matrix")
    if not np.isfinite(array).all() or (np.abs(array) > 1).any():
        raise ValueError("normalized inputs must lie in [-1, 1]")
    return np.floor(array.astype(np.float64) * SCALE + 0.5).astype("<i2")


def checked_inputs(values, input_dim):
    array = np.asarray(values)
    if array.ndim != 2 or array.shape[1] != input_dim:
        raise ValueError("input dimension mismatch")
    if array.dtype.kind not in "iu" or array.shape[0] > MAX_ROWS:
        raise ValueError("readout requires bounded integer Q12 inputs")
    if (array < -SCALE).any() or (array > SCALE).any():
        raise ValueError("Q12 input out of range")
    return np.ascontiguousarray(array, dtype="<i2")


def value_bits(values, bits):
    array = np.asarray(values)
    if not 1 <= bits <= MAX_BITS or array.ndim != 1:
        raise ValueError("invalid value shape or bit width")
    if array.dtype.kind not in "iu" or (array < 0).any():
        raise ValueError("memory values must be unsigned integers")
    if (array.astype(np.uint64) >= (1 << bits)).any():
        raise ValueError("memory value exceeds declared bit width")
    return (
        (array.astype(np.uint64)[:, None] >> np.arange(bits, dtype=np.uint64)) & 1
    ).astype(np.uint8)


@dataclass(frozen=True)
class IntegerBitCell:
    """Immutable deployed weights; no source examples or output dictionary."""

    w1: np.ndarray
    w2: np.ndarray

    def __post_init__(self):
        first, second = np.asarray(self.w1), np.asarray(self.w2)
        if first.ndim != 2 or second.ndim != 2:
            raise ValueError("cell weights must be matrices")
        d, h, b = first.shape[0] - 1, first.shape[1], second.shape[1]
        if not (1 <= d <= MAX_INPUTS and 1 <= h <= MAX_HIDDEN and 1 <= b <= MAX_BITS):
            raise ValueError("cell dimensions exceed the artifact contract")
        if second.shape[0] != h + 1:
            raise ValueError("hidden/output weight shapes disagree")
        for name, array in (("w1", first), ("w2", second)):
            if (
                array.dtype.kind not in "iu"
                or (array < -32768).any()
                or (array > 32767).any()
            ):
                raise ValueError("weights must be representable int16 integers")
            owned = np.array(array, dtype="<i2", order="C", copy=True)
            owned.setflags(write=False)
            object.__setattr__(self, name, owned)

    @property
    def input_dim(self):
        return self.w1.shape[0] - 1

    @property
    def hidden(self):
        return self.w1.shape[1]

    @property
    def bits(self):
        return self.w2.shape[1]

    @property
    def parameter_count(self):
        return int(self.w1.size + self.w2.size)

    @property
    def digest(self):
        return hashlib.sha256(self.to_bytes()).hexdigest()

    def logits_q24(self, inputs):
        x = checked_inputs(inputs, self.input_dim)
        out = np.empty((len(x), self.bits), dtype=np.int64)
        first, second = self.w1.astype(np.int64), self.w2.astype(np.int64)
        for start in range(0, len(x), 2048):
            batch = x[start : start + 2048]
            augmented = np.empty((len(batch), self.input_dim + 1), dtype=np.int64)
            augmented[:, :-1], augmented[:, -1] = batch, SCALE
            hidden = np.clip((augmented @ first + SCALE // 2) // SCALE, -SCALE, SCALE)
            h_augmented = np.empty((len(batch), self.hidden + 1), dtype=np.int64)
            h_augmented[:, :-1], h_augmented[:, -1] = hidden, SCALE
            out[start : start + len(batch)] = h_augmented @ second
        return out

    def predict_bits(self, inputs):
        return (self.logits_q24(inputs) >= 0).astype(np.uint8)

    def predict(self, inputs):
        bits = self.predict_bits(inputs).astype(np.uint64)
        return (bits @ (np.uint64(1) << np.arange(self.bits, dtype=np.uint64))).astype(
            np.uint32
        )

    def to_bytes(self):
        header = HEADER.pack(
            MAGIC,
            1,
            self.input_dim,
            self.hidden,
            self.bits,
            SCALE,
            self.parameter_count,
        )
        return header + self.w1.tobytes(order="C") + self.w2.tobytes(order="C")

    @classmethod
    def from_bytes(cls, payload, expected_sha256=None):
        if not isinstance(payload, bytes) or len(payload) < HEADER.size:
            raise ValueError("truncated cell artifact")
        if (
            expected_sha256 is not None
            and hashlib.sha256(payload).hexdigest() != expected_sha256
        ):
            raise ValueError("cell artifact digest mismatch")
        magic, version, d, h, bits, scale, count = HEADER.unpack_from(payload)
        if (magic, version, scale) != (MAGIC, 1, SCALE):
            raise ValueError("unknown cell artifact contract")
        if not (
            1 <= d <= MAX_INPUTS and 1 <= h <= MAX_HIDDEN and 1 <= bits <= MAX_BITS
        ):
            raise ValueError("invalid artifact dimensions")
        expected_count = (d + 1) * h + (h + 1) * bits
        if count != expected_count or len(payload) != HEADER.size + 2 * count:
            raise ValueError("cell artifact length or tensor count mismatch")
        weights = np.frombuffer(payload, dtype="<i2", offset=HEADER.size)
        cut = (d + 1) * h
        return cls(weights[:cut].reshape(d + 1, h), weights[cut:].reshape(h + 1, bits))

    @classmethod
    def load(cls, path, expected_sha256=None):
        path = Path(path)
        maximum = HEADER.size + 2 * (
            (MAX_INPUTS + 1) * MAX_HIDDEN + (MAX_HIDDEN + 1) * MAX_BITS
        )
        if path.is_symlink() or path.stat().st_size > maximum:
            raise ValueError("invalid or oversized artifact path")
        return cls.from_bytes(path.read_bytes(), expected_sha256)

    def save(self, path):
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("xb") as stream:
            stream.write(self.to_bytes())
        return {"bytes": path.stat().st_size, "sha256": self.digest}

    @classmethod
    def fit(
        cls,
        inputs,
        values,
        *,
        hidden,
        bits,
        steps=600,
        batch_size=128,
        learning_rate=0.02,
        seed=0,
        parent=None,
    ):
        started = time.perf_counter()
        x = np.asarray(inputs)
        if x.ndim != 2 or not 1 <= x.shape[1] <= MAX_INPUTS:
            raise ValueError("invalid training input shape")
        xq = checked_inputs(x, x.shape[1])
        target_bits = value_bits(values, bits)
        if len(xq) == 0 or len(xq) != len(target_bits):
            raise ValueError("training examples are empty or misaligned")
        if (
            not 1 <= hidden <= MAX_HIDDEN
            or not 1 <= steps <= 100_000
            or not 1 <= batch_size <= MAX_ROWS
        ):
            raise ValueError("training budget exceeds contract")
        if not np.isfinite(learning_rate) or not 0 < learning_rate <= 1:
            raise ValueError("invalid learning rate")
        if not isinstance(seed, (int, np.integer)) or not 0 <= seed < 2**32:
            raise ValueError("seed must be a uint32")
        rng = np.random.default_rng(seed)
        d = xq.shape[1]
        w1 = rng.normal(0, 1 / np.sqrt(d), (d + 1, hidden))
        w2 = rng.normal(0, 1 / np.sqrt(hidden), (hidden + 1, bits))
        w1[-1], w2[-1] = 0, 0
        inherited = []
        if parent is not None:
            if not isinstance(parent, cls) or (parent.input_dim, parent.bits) != (
                d,
                bits,
            ):
                raise ValueError("parent compatibility mismatch")
            strength = np.sum(parent.w2[:-1].astype(np.float64) ** 2, axis=1)
            inherited = np.argsort(-strength, kind="stable")[
                : min(hidden, parent.hidden)
            ].tolist()
            retained = len(inherited)
            w1[:, :retained] = parent.w1[:, inherited] / SCALE
            w2[:retained] = parent.w2[inherited] / SCALE
            w2[-1] = parent.w2[-1] / SCALE
        xf = np.empty((len(xq), d + 1), dtype=np.float64)
        xf[:, :-1], xf[:, -1] = xq / SCALE, 1.0
        target = target_bits.astype(np.float64)
        m1, v1, m2, v2 = (
            np.zeros_like(w1),
            np.zeros_like(w1),
            np.zeros_like(w2),
            np.zeros_like(w2),
        )
        count = min(batch_size, len(xq))
        losses = []
        optimization_started = time.perf_counter()
        for step in range(1, steps + 1):
            indices = (
                rng.choice(len(xq), size=count, replace=False)
                if count < len(xq)
                else np.arange(len(xq))
            )
            batch, truth = xf[indices], target[indices]
            preactivation = batch @ w1
            activations = np.clip(preactivation, -1.0, 1.0)
            extended = np.empty((count, hidden + 1), dtype=np.float64)
            extended[:, :-1], extended[:, -1] = activations, 1.0
            logits = extended @ w2
            probabilities = 1.0 / (1.0 + np.exp(-np.clip(logits, -50, 50)))
            gradient = (probabilities - truth) / (count * bits)
            g2 = extended.T @ gradient
            g1 = batch.T @ ((gradient @ w2[:-1].T) * (np.abs(preactivation) < 1))
            m1, v1 = 0.9 * m1 + 0.1 * g1, 0.999 * v1 + 0.001 * g1 * g1
            m2, v2 = 0.9 * m2 + 0.1 * g2, 0.999 * v2 + 0.001 * g2 * g2
            correction1, correction2 = 1 - 0.9**step, 1 - 0.999**step
            w1 -= (
                learning_rate * (m1 / correction1) / (np.sqrt(v1 / correction2) + 1e-8)
            )
            w2 -= (
                learning_rate * (m2 / correction1) / (np.sqrt(v2 / correction2) + 1e-8)
            )
            if step == 1 or step == steps or step % 100 == 0:
                losses.append(
                    {
                        "step": step,
                        "batch_bce": float(
                            np.mean(np.logaddexp(0, logits) - truth * logits)
                        ),
                    }
                )
        optimization_seconds = time.perf_counter() - optimization_started
        quantized = []
        saturation = 0
        for weights in (w1, w2):
            scaled = np.floor(weights * SCALE + 0.5)
            saturation += int(((scaled < -32768) | (scaled > 32767)).sum())
            quantized.append(np.clip(scaled, -32768, 32767).astype("<i2"))
        cell = cls(*quantized)
        predictions = cell.predict_bits(xq)
        receipt = {
            "schema": "memory-cell-v3.bitcell-fit.v1",
            "seed": int(seed),
            "optimizer": "Adam; float64 master weights; hard-tanh/BCE; deployed Q12 integer evaluation",
            "optimizer_steps": steps,
            "batch_examples": count,
            "examples_seen": steps * count,
            "dense_multiply_accumulate_estimate": steps
            * count
            * (2 * (d + 1) * hidden + 2 * (hidden + 1) * bits + hidden * bits),
            "optimizer_parameter_updates": steps * cell.parameter_count,
            "final_quantized_read_multiply_accumulate_estimate": len(xq)
            * ((d + 1) * hidden + (hidden + 1) * bits),
            "work_estimate_excludes": "activation, sampling, Adam scalar operations and memory traffic; wall time is separately measured",
            "optimization_seconds": optimization_seconds,
            "fit_wall_seconds": time.perf_counter() - started,
            "parameter_count": cell.parameter_count,
            "parameter_bytes": 2 * cell.parameter_count,
            "artifact_bytes": len(cell.to_bytes()),
            "artifact_sha256": cell.digest,
            "weight_saturation_count": saturation,
            "loss_trace": losses,
            "written_bit_accuracy": float(np.mean(predictions == target_bits)),
            "written_value_accuracy": float(
                np.mean(np.all(predictions == target_bits, axis=1))
            ),
            "parent_digest": parent.digest if parent is not None else None,
            "inherited_hidden_indices": inherited,
            "source_inputs_sha256": hashlib.sha256(xq.tobytes()).hexdigest(),
            "source_values_sha256": hashlib.sha256(
                np.asarray(values, dtype="<u4").tobytes()
            ).hexdigest(),
        }
        return cell, receipt
