"""Small NumPy models with explicit gradients, schedules and persisted weights."""

import hashlib
import json
from pathlib import Path
import time

import numpy as np

from export_native import canonical, parameter_digest, sha


SEMANTIC_OUTPUTS = (("binary", 4), ("binary", 4), ("binary", 4))
PROCEDURE_OUTPUTS = (("multiclass", 7),) * 4
JOINT_OUTPUTS = SEMANTIC_OUTPUTS + PROCEDURE_OUTPUTS


def objective(raw, target, outputs):
    """Equal weight per declared output group; target is dense bits/probabilities."""
    derivative = np.zeros_like(raw)
    total, start = 0.0, 0
    for kind, width in outputs:
        values, labels = raw[:, start:start + width], target[:, start:start + width]
        if kind == "binary":
            total += float(np.mean(np.maximum(values, 0) - values * labels
                                   + np.log1p(np.exp(-np.abs(values)))))
            positive = values >= 0
            probability = np.empty_like(values)
            probability[positive] = 1 / (1 + np.exp(-values[positive]))
            exponent = np.exp(values[~positive])
            probability[~positive] = exponent / (1 + exponent)
            grad = (probability - labels) / (len(raw) * width)
        elif kind == "multiclass":
            shifted = values - np.max(values, axis=1, keepdims=True)
            exponent = np.exp(shifted)
            logsum = np.log(np.sum(exponent, axis=1, keepdims=True))
            total -= float(np.mean(np.sum(labels * (shifted - logsum), axis=1)))
            grad = (exponent / np.sum(exponent, axis=1, keepdims=True) - labels) / len(raw)
        else:
            raise ValueError("unknown objective group")
        derivative[:, start:start + width] = grad / len(outputs)
        start += width
    if start != raw.shape[1] or target.shape != raw.shape:
        raise ValueError("target/output contract mismatch")
    return total / len(outputs), derivative


class Cell:
    def __init__(self, dimension, width, rank, seed, *, head_mask=None):
        rng = np.random.default_rng(seed)
        self.dimension, self.width, self.rank = dimension, width, rank
        self.arrays = {"head.weight": (rng.normal(size=(width, dimension)) / np.sqrt(dimension)).astype(np.float32),
                       "head.bias": np.zeros(width, dtype=np.float32)}
        if rank:
            self.arrays.update(A=(rng.normal(size=(rank, dimension)) * 0.02).astype(np.float32),
                               B=np.zeros((dimension, rank), dtype=np.float32))
        self.head_mask = head_mask
        if head_mask is not None:
            self.arrays["head.weight"] *= head_mask
        self.head_frozen = False
        self.history, self.lineage = [], set()

    def forward(self, x):
        z = x if not self.rank else x + (x @ self.arrays["A"].T) @ self.arrays["B"].T
        return z @ self.arrays["head.weight"].T + self.arrays["head.bias"]

    def gradients(self, x, derivative):
        if self.rank:
            u = x @ self.arrays["A"].T
            z = x + u @ self.arrays["B"].T
            gz = derivative @ self.arrays["head.weight"]
            result = {"B": gz.T @ u, "A": (gz @ self.arrays["B"]).T @ x}
        else:
            z, result = x, {}
        if not self.head_frozen:
            result["head.weight"] = derivative.T @ z
            if self.head_mask is not None:
                result["head.weight"] *= self.head_mask
            result["head.bias"] = np.sum(derivative, axis=0)
        return result

    def parameters(self):
        return {k: v for k, v in self.arrays.items() if not self.head_frozen or not k.startswith("head.")}

    def fork(self, *, rank=None, seed=0):
        target_rank = self.rank if rank is None else rank
        if target_rank < self.rank:
            raise ValueError("rank expansion cannot remove parent channels")
        other = Cell(self.dimension, self.width, target_rank, seed)
        other.arrays["head.weight"] = self.arrays["head.weight"]
        other.arrays["head.bias"] = self.arrays["head.bias"]
        other.arrays["A"][:self.rank] = self.arrays["A"]
        other.arrays["B"][:, :self.rank] = self.arrays["B"]
        other.head_frozen = True
        other.lineage = set(self.lineage)
        return other

    def identity(self):
        return parameter_digest(self.arrays)

    def save(self, destination, *, encoder_sha256, outputs, extra=None):
        destination = Path(destination)
        destination.mkdir(parents=True, exist_ok=False)
        paths = {}
        for name, array in self.arrays.items():
            payload = array.astype("<f4").tobytes()
            path = destination / f"{name}.f32"
            path.write_bytes(payload)
            paths[name] = {"shape": list(array.shape), "file": path.name,
                           "bytes": len(payload), "sha256": sha(payload)}
        manifest = {"schema": "hepta.memory.v10.numpy-checkpoint.v1", "dimension": self.dimension,
                    "width": self.width, "rank": self.rank, "head_frozen": self.head_frozen,
                    "operator": "joint_block_head" if isinstance(self, JointCell) else "residual",
                    "outputs": outputs, "encoder_sha256": encoder_sha256,
                    "parameter_sha256": self.identity(), "source_ids": sorted(self.lineage),
                    "training_history": self.history, "arrays": paths, "extra": extra or {}}
        (destination / "manifest.json").write_bytes(canonical(manifest))
        return {"path": str(destination), "parameter_sha256": self.identity(),
                "manifest_sha256": sha(canonical(manifest)),
                "stored_bytes": sum(p.stat().st_size for p in destination.iterdir())}


class JointCell(Cell):
    """One global residual on a pair; heads retain the same typed output blocks.

    Its four matrices contain exactly as many free and stored scalars as the
    two rank-four typed cells. A separate dense-head control removes this head
    restriction and explicitly accounts for its larger parameter count.
    """
    def __init__(self, semantic, procedure, seed):
        rng = np.random.default_rng(seed)
        self.dimension, self.width, self.rank = 768, 40, 4
        self.arrays = {"A": (rng.normal(size=(4, 768)) * 0.02).astype(np.float32),
                       "B": np.zeros((768, 4), dtype=np.float32)}
        for prefix, cell in (("semantic", semantic), ("procedure", procedure)):
            for name in ("weight", "bias"):
                self.arrays[f"head.{prefix}.{name}"] = cell.arrays[f"head.{name}"].copy()
        self.head_mask, self.head_frozen = None, False
        self.history, self.lineage = [], set()

    def forward(self, x):
        z = x + (x @ self.arrays["A"].T) @ self.arrays["B"].T
        return np.concatenate([z[:, i * 384:(i + 1) * 384] @ self.arrays[f"head.{name}.weight"].T
                               + self.arrays[f"head.{name}.bias"]
                               for i, name in enumerate(("semantic", "procedure"))], axis=1)

    def gradients(self, x, derivative):
        u = x @ self.arrays["A"].T
        z = x + u @ self.arrays["B"].T
        result, parts = {}, []
        for i, (name, begin, end) in enumerate((("semantic", 0, 12), ("procedure", 12, 40))):
            grad = derivative[:, begin:end]
            parts.append(grad @ self.arrays[f"head.{name}.weight"])
            result[f"head.{name}.weight"] = grad.T @ z[:, i * 384:(i + 1) * 384]
            result[f"head.{name}.bias"] = np.sum(grad, axis=0)
        gz = np.concatenate(parts, axis=1)
        result.update(B=gz.T @ u, A=(gz @ self.arrays["B"]).T @ x)
        return result


class TypedPair:
    """Two typed cells consume the same full pair batch as the joint controls."""
    def __init__(self, semantic, procedure):
        self.cells = (semantic, procedure)

    def forward(self, x):
        return np.concatenate([c.forward(x[:, i * 384:(i + 1) * 384])
                               for i, c in enumerate(self.cells)], axis=1)

    def gradients(self, x, derivative):
        result, offset = {}, 0
        for i, cell in enumerate(self.cells):
            for name, value in cell.gradients(x[:, i * 384:(i + 1) * 384],
                                             derivative[:, offset:offset + cell.width]).items():
                result[f"{i}:{name}"] = value
            offset += cell.width
        return result

    def parameters(self):
        return {f"{i}:{name}": value for i, cell in enumerate(self.cells)
                for name, value in cell.parameters().items()}

    def identity(self):
        return sha(canonical([c.identity() for c in self.cells]))


class RoutedPair:
    """One globally fixed row schedule; only the selected child sees each row."""
    def __init__(self, children, assignments):
        self.cells, self.assignments = children, np.asarray(assignments, dtype=np.int64)
        self.rows = None

    def forward(self, x):
        if self.rows is None:
            raise RuntimeError("explicit row identities required for routing")
        raw = np.zeros((len(x), self.cells[0].width), dtype=np.float32)
        for i, cell in enumerate(self.cells):
            selected = self.assignments[self.rows] == i
            if np.any(selected):
                raw[selected] = cell.forward(x[selected])
        return raw

    def gradients(self, x, derivative):
        result = {}
        for i, cell in enumerate(self.cells):
            selected = self.assignments[self.rows] == i
            if np.any(selected):
                result.update({f"{i}:{name}": value for name, value in cell.gradients(x[selected], derivative[selected]).items()})
        return result

    def parameters(self):
        return {f"{i}:{name}": value for i, cell in enumerate(self.cells)
                for name, value in cell.parameters().items()}

    def identity(self):
        return sha(canonical([c.identity() for c in self.cells]))


def fit(model, x, y, outputs, schedule, *, lr, source_ids, label):
    started, cpu = time.perf_counter(), time.process_time()
    x, y = np.asarray(x, dtype=np.float32), np.asarray(y, dtype=np.float32)
    schedule = np.asarray(schedule, dtype=np.int64)
    if schedule.ndim != 2 or not schedule.size or schedule.min() < 0 or schedule.max() >= len(x):
        raise ValueError("invalid fixed minibatch schedule")
    if len(source_ids) != len(x) or not np.isfinite(x).all() or not np.isfinite(y).all():
        raise ValueError("invalid fit input")
    before = model.identity()
    if isinstance(model, RoutedPair):
        model.rows = np.arange(len(x))
    initial = objective(model.forward(x), y, outputs)[0]
    params = model.parameters()
    first = {k: np.zeros_like(v) for k, v in params.items()}
    second = {k: np.zeros_like(v) for k, v in params.items()}
    updates = {k: 0 for k in params}
    norms = {k: 0.0 for k in params}
    for rows in schedule:
        if isinstance(model, RoutedPair):
            model.rows = rows
        raw = model.forward(x[rows])
        loss, derivative = objective(raw, y[rows], outputs)
        if not np.isfinite(loss):
            raise FloatingPointError("nonfinite loss")
        for name, grad in model.gradients(x[rows], derivative).items():
            if not np.isfinite(grad).all():
                raise FloatingPointError("nonfinite gradient")
            norms[name] = max(norms[name], float(np.linalg.norm(grad)))
            updates[name] += 1
            first[name] *= 0.9
            first[name] += 0.1 * grad
            second[name] *= 0.999
            second[name] += 0.001 * grad * grad
            corrected = first[name] / (1 - 0.9 ** updates[name])
            variance = second[name] / (1 - 0.999 ** updates[name])
            params[name] -= lr * corrected / (np.sqrt(variance) + 1e-8)
    if isinstance(model, RoutedPair):
        model.rows = np.arange(len(x))
    final = objective(model.forward(x), y, outputs)[0]
    receipt = {"schema": "hepta.memory.v10.fit.v1", "label": label,
               "initial_parameter_sha256": before, "final_parameter_sha256": model.identity(),
               "initial_loss": initial, "final_loss": final, "steps": len(schedule),
               "batch_size": schedule.shape[1], "sample_presentations": schedule.size,
               "diagnostic_forward_rows": 2 * len(x), "input_feature_coordinates_per_presentation": x.shape[1],
               "schedule_sha256": sha(schedule.astype("<i8").tobytes()),
               "features_sha256": sha(x.astype("<f4").tobytes()), "targets_sha256": sha(y.astype("<f4").tobytes()),
               "source_ids_sha256": sha(canonical(source_ids)), "max_gradient_norm": norms,
               "parameter_update_counts": updates, "trainable_parameter_count": sum(v.size for v in params.values()),
               "cpu_seconds": time.process_time() - cpu, "wall_seconds": time.perf_counter() - started,
               "optimizer": "numpy float32 Adam beta1=.9 beta2=.999 eps=1e-8", "learning_rate": lr}
    for i, cell in enumerate(model.cells if hasattr(model, "cells") else [model]):
        cell.history.append(receipt)
        seen = np.unique(schedule)
        if isinstance(model, RoutedPair):
            seen = seen[model.assignments[seen] == i]
        for index in seen:
            entry = source_ids[int(index)]
            cell.lineage.update(entry if isinstance(entry, list) else [entry])
    return receipt
