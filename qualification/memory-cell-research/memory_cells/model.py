"""Trainable numerical memory cell and checked, parameter-only artifact format.

The cell is a two-layer tanh classifier over a shared frozen encoder. It is not a
language model or a production Hepta wire protocol. Softmax outputs are not
claimed to be calibrated. Training stores no examples in the model or artifact.
"""

import hashlib
import io
import json
from pathlib import Path
import re
import time
import zipfile

import numpy as np

from .encoding import FrozenEncoder, canonical_bytes


def _digest(data):
    return hashlib.sha256(data).hexdigest()


def _positive_int(value, name, maximum):
    if type(value) is not int or not 1 <= value <= maximum:
        raise ValueError(f"{name} must be an integer in [1, {maximum}]")
    return value


def _validate_lineage(lineage):
    if not isinstance(lineage, dict) or set(lineage) - {
        "parent",
        "dataset",
        "source_commit",
    }:
        raise ValueError("lineage only accepts parent, dataset, source_commit digests")
    for name, value in lineage.items():
        length = 40 if name == "source_commit" else 64
        if not isinstance(value, str) or not re.fullmatch(
            rf"[0-9a-f]{{{length}}}", value
        ):
            raise ValueError("lineage entries must be lowercase content digests")


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON field")
        result[key] = value
    return result


class MemoryCell:
    """A privately trainable nonlinear map; callers own data and adoption policy."""

    def __init__(self, input_dim, rank, num_classes, seed=0):
        self.input_dim = _positive_int(input_dim, "input_dim", 4096)
        self.rank = _positive_int(rank, "rank", 4096)
        self.num_classes = _positive_int(num_classes, "num_classes", 4096)
        if num_classes < 2 or self.trainable_params > 8_000_000:
            raise ValueError("unsupported model capacity")
        if type(seed) is not int or not 0 <= seed < 2**32:
            raise ValueError("seed must be an unsigned 32-bit integer")
        self.seed = seed
        rng = np.random.default_rng(seed)
        self.A = rng.normal(0, 1 / np.sqrt(input_dim), (input_dim, rank))
        self.B = rng.normal(0, 0.05, (rank, num_classes))
        self.total_steps = 0

    @property
    def trainable_params(self):
        return self.rank * (self.input_dim + self.num_classes)

    @property
    def parameter_bytes(self):
        return int(self.A.nbytes + self.B.nbytes)

    def clone(self, seed=None):
        cell = MemoryCell(
            self.input_dim,
            self.rank,
            self.num_classes,
            self.seed if seed is None else seed,
        )
        cell.A = self.A.copy()
        cell.B = self.B.copy()
        cell.total_steps = self.total_steps
        return cell

    def resize_rank(self, new_rank, seed=None):
        """Inherit prefix units; expansion adds zero-output units, shrinking is lossy.

        The receipt describes this transformation, not suitability for adoption.
        A smaller child must be retrained and independently evaluated.
        """
        cell = MemoryCell(
            self.input_dim,
            new_rank,
            self.num_classes,
            self.seed if seed is None else seed,
        )
        inherited = min(self.rank, cell.rank)
        cell.A[:, :inherited] = self.A[:, :inherited]
        cell.B[:inherited] = self.B[:inherited]
        if cell.rank > self.rank:
            cell.B[self.rank :] = 0.0
        cell.total_steps = self.total_steps
        return cell, {
            "operation": "prefix-inheritance-zero-output-expansion",
            "old_rank": self.rank,
            "new_rank": cell.rank,
            "inherited_units": inherited,
            "dropped_units": self.rank - inherited,
            "algebraically_function_preserving": cell.rank >= self.rank,
            "requires_independent_evaluation": True,
        }

    def _inputs(self, X):
        X = np.asarray(X, dtype=np.float64)
        if (
            X.ndim != 2
            or X.shape[1] != self.input_dim
            or X.shape[0] > 65536
            or not np.isfinite(X).all()
        ):
            raise ValueError("invalid or non-finite feature matrix")
        if not np.isfinite(self.A).all() or not np.isfinite(self.B).all():
            raise ValueError("non-finite model weights")
        return X

    def _targets(self, y, count):
        y = np.asarray(y)
        if (
            y.shape != (count,)
            or y.dtype.kind not in "iu"
            or count == 0
            or np.any(y < 0)
            or np.any(y >= self.num_classes)
        ):
            raise ValueError("targets must be integer classes for every input")
        return y.astype(np.int64, copy=False)

    def proba(self, X):
        X = self._inputs(X)
        if not len(X):
            return np.empty((0, self.num_classes), dtype=np.float64)
        logits = np.tanh(X @ self.A) @ self.B
        logits -= logits.max(axis=1, keepdims=True)
        exp = np.exp(logits)
        return exp / exp.sum(axis=1, keepdims=True)

    def predict(self, X):
        return self.proba(X).argmax(axis=1)

    def loss_and_gradients(self, X, y):
        """Exact mean cross-entropy and analytic gradients for the declared MLP."""
        X = self._inputs(X)
        y = self._targets(y, len(X))
        hidden = np.tanh(X @ self.A)
        logits = hidden @ self.B
        logits -= logits.max(axis=1, keepdims=True)
        exp = np.exp(logits)
        normalizer = exp.sum(axis=1, keepdims=True)
        loss = np.mean(np.log(normalizer[:, 0]) - logits[np.arange(len(y)), y])
        delta = exp / normalizer
        delta[np.arange(len(y)), y] -= 1
        delta /= len(y)
        grad_B = hidden.T @ delta
        grad_A = X.T @ ((delta @ self.B.T) * (1 - hidden**2))
        return float(loss), grad_A, grad_B

    def fit(self, X, y, steps=300, lr=0.03, batch_size=None):
        """Apply Adam steps, with a fresh optimizer per call and bounded batches.

        Retention/replay is explicit: callers supply the intended training mixture.
        The receipt reports actual work; it makes no memory-quality acceptance claim.
        """
        X = self._inputs(X)
        y = self._targets(y, len(X))
        steps = _positive_int(steps, "steps", 100000)
        if not np.isfinite(lr) or not 0 < lr <= 1:
            raise ValueError("lr must be finite and in (0, 1]")
        batch_size = (
            len(X)
            if batch_size is None
            else _positive_int(batch_size, "batch_size", len(X))
        )
        rng = np.random.default_rng(self.seed + self.total_steps)
        moments = [np.zeros_like(self.A), np.zeros_like(self.B)]
        variances = [np.zeros_like(self.A), np.zeros_like(self.B)]
        started = time.perf_counter()
        initial_loss = self.loss_and_gradients(X, y)[0]
        for step in range(1, steps + 1):
            indices = (
                np.arange(len(X))
                if batch_size == len(X)
                else rng.choice(len(X), batch_size, replace=False)
            )
            loss, grad_A, grad_B = self.loss_and_gradients(X[indices], y[indices])
            if not np.isfinite(loss):
                raise ValueError("non-finite training loss")
            for index, (weights, gradient) in enumerate(
                ((self.A, grad_A), (self.B, grad_B))
            ):
                moments[index] *= 0.9
                moments[index] += 0.1 * gradient
                variances[index] *= 0.999
                variances[index] += 0.001 * gradient**2
                weights -= (
                    lr
                    * (moments[index] / (1 - 0.9**step))
                    / (np.sqrt(variances[index] / (1 - 0.999**step)) + 1e-8)
                )
        self.total_steps += steps
        final_loss = self.loss_and_gradients(X, y)[0]
        seconds = time.perf_counter() - started
        return {
            "optimizer": "adam-reset-per-fit",
            "optimizer_steps": steps,
            "examples_seen": steps * batch_size,
            "batch_size": batch_size,
            "trainable_params": self.trainable_params,
            "parameter_bytes": self.parameter_bytes,
            "optimizer_bytes": self.parameter_bytes * 2,
            "seconds": seconds,
            "initial_loss": initial_loss,
            "final_loss": final_loss,
            "extra_full_batch_gradient_evaluations": 2,
            "estimated_training_matmul_flops": int(
                (steps * batch_size + 2 * len(X))
                * (4 * self.input_dim * self.rank + 6 * self.rank * self.num_classes)
            ),
        }

    def save(self, directory, *, encoder_manifest, lineage=None):
        """Write a new immutable artifact directory; no source payload is accepted."""
        encoder = FrozenEncoder.from_manifest(encoder_manifest)
        if encoder.dim != self.input_dim:
            raise ValueError("encoder and cell dimensions differ")
        lineage = {} if lineage is None else dict(lineage)
        _validate_lineage(lineage)
        self._inputs(np.empty((0, self.input_dim)))
        stream = io.BytesIO()
        np.savez(stream, A=self.A.astype("<f8"), B=self.B.astype("<f8"))
        tensor_bytes = stream.getvalue()
        manifest = {
            "schema": "hepta.memory-cell.parameters.v1",
            "input_dim": self.input_dim,
            "rank": self.rank,
            "num_classes": self.num_classes,
            "seed": self.seed,
            "encoder": encoder_manifest,
            "encoder_digest": encoder.digest,
            "tensor_file": "tensors.npz",
            "tensor_sha256": _digest(tensor_bytes),
            "tensor_nbytes": len(tensor_bytes),
            "trainable_params": self.trainable_params,
            "parameter_bytes": self.parameter_bytes,
            "lineage": lineage,
            "total_steps": self.total_steps,
        }
        manifest["manifest_sha256"] = _digest(canonical_bytes(manifest))
        directory = Path(directory)
        directory.mkdir(parents=True, exist_ok=False)
        (directory / "tensors.npz").write_bytes(tensor_bytes)
        (directory / "manifest.json").write_bytes(canonical_bytes(manifest) + b"\n")
        return manifest

    @classmethod
    def load(cls, directory, *, expected_encoder_digest=None):
        directory = Path(directory)
        manifest_file = directory / "manifest.json"
        if manifest_file.stat().st_size > 16384:
            raise ValueError("oversized manifest")
        manifest = json.loads(
            manifest_file.read_text(), object_pairs_hook=_unique_object
        )
        required = {
            "schema",
            "input_dim",
            "rank",
            "num_classes",
            "seed",
            "encoder",
            "encoder_digest",
            "tensor_file",
            "tensor_sha256",
            "tensor_nbytes",
            "trainable_params",
            "parameter_bytes",
            "lineage",
            "total_steps",
            "manifest_sha256",
        }
        if not isinstance(manifest, dict) or set(manifest) != required:
            raise ValueError("unexpected manifest fields")
        digest = manifest.pop("manifest_sha256")
        if digest != _digest(canonical_bytes(manifest)):
            raise ValueError("manifest digest mismatch")
        if (
            manifest["schema"] != "hepta.memory-cell.parameters.v1"
            or manifest["tensor_file"] != "tensors.npz"
        ):
            raise ValueError("unsupported artifact format")
        _validate_lineage(manifest["lineage"])
        encoder = FrozenEncoder.from_manifest(manifest["encoder"])
        if encoder.digest != manifest["encoder_digest"] or (
            expected_encoder_digest is not None
            and encoder.digest != expected_encoder_digest
        ):
            raise ValueError("encoder digest mismatch")
        cell = cls(
            manifest["input_dim"],
            manifest["rank"],
            manifest["num_classes"],
            manifest["seed"],
        )
        if encoder.dim != cell.input_dim:
            raise ValueError("encoder dimension mismatch")
        tensor_file = directory / "tensors.npz"
        if (
            tensor_file.stat().st_size != manifest["tensor_nbytes"]
            or tensor_file.stat().st_size > 65_000_000
        ):
            raise ValueError("tensor size mismatch or limit exceeded")
        tensor_bytes = tensor_file.read_bytes()
        if _digest(tensor_bytes) != manifest["tensor_sha256"]:
            raise ValueError("tensor digest mismatch")
        with zipfile.ZipFile(io.BytesIO(tensor_bytes)) as archive:
            infos = archive.infolist()
            if len(infos) != 2 or {item.filename for item in infos} != {
                "A.npy",
                "B.npy",
            }:
                raise ValueError("unexpected archive inventory")
            if any(
                item.compress_type != zipfile.ZIP_STORED
                or item.file_size > cell.parameter_bytes + 1024
                for item in infos
            ):
                raise ValueError("unsupported compressed or oversized tensors")
        with np.load(io.BytesIO(tensor_bytes), allow_pickle=False) as arrays:
            if set(arrays.files) != {"A", "B"}:
                raise ValueError("unexpected tensor inventory")
            A, B = arrays["A"], arrays["B"]
            if (
                A.shape != cell.A.shape
                or B.shape != cell.B.shape
                or A.dtype != np.dtype("<f8")
                or B.dtype != np.dtype("<f8")
                or not np.isfinite(A).all()
                or not np.isfinite(B).all()
            ):
                raise ValueError("invalid tensor shape, dtype, or finite state")
            cell.A, cell.B = A.copy(), B.copy()
        if (
            manifest["trainable_params"] != cell.trainable_params
            or manifest["parameter_bytes"] != cell.parameter_bytes
            or type(manifest["total_steps"]) is not int
            or manifest["total_steps"] < 0
        ):
            raise ValueError("model accounting mismatch")
        cell.total_steps = manifest["total_steps"]
        return cell
