"""Small trained associative cells and a bounded procedure interpreter.

The model learns address-to-class associations. The value catalog is explicit,
fully serialized and charged; this is not language-model or program compression.
Serving never accesses a training target table. SHA-256 addresses only gate the
closed support set and identify source dependencies, not the predicted value.
"""

import base64
from copy import deepcopy
import hashlib
import json
import math
import time

import numpy as np

from .values import execute_program as execute_program


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def key_digest(key):
    if not isinstance(key, str) or not 0 < len(key.encode()) <= 4096:
        raise ValueError("cell key must be nonempty and bounded")
    return hashlib.sha256(key.encode()).hexdigest()


def encode(keys, dimension):
    """Deterministic, value-independent random address features, not semantics."""
    rows = []
    for key in keys:
        digest = key_digest(key)
        raw = hashlib.shake_256(bytes.fromhex(digest)).digest(dimension)
        row = np.frombuffer(raw, dtype=np.uint8).astype(np.float64)
        rows.append((row - 127.5) / 73.9002706355 / np.sqrt(dimension))
    return np.array(rows).reshape(len(keys), dimension)


class AssociativeCell:
    """A trained tanh MLP with isolated parameters and an explicit value catalog."""

    @classmethod
    def fit(
        cls,
        keys,
        values,
        seed=0,
        *,
        support_ids=None,
        kind="semantic",
        hidden=32,
        dimension=64,
        steps=400,
        learning_rate=0.025,
        parent=None,
        catalog_values=None,
    ):
        if kind not in {"semantic", "procedure"}:
            raise ValueError("unsupported cell type")
        if not keys or len(keys) != len(values) or len(keys) > 4096:
            raise ValueError("bounded aligned training rows required")
        if not 1 <= hidden <= 256 or not 8 <= dimension <= 1024 or not 1 <= steps <= 5000:
            raise ValueError("model or training budget exceeded")
        if type(seed) is not int or not 0 <= seed < 2**32 or not 0 < learning_rate <= 0.1:
            raise ValueError("invalid optimizer configuration")
        addresses = [key_digest(key) for key in keys]
        if len(set(addresses)) != len(addresses):
            raise ValueError("resolve duplicate/current revisions before fitting")
        encoded_values = [canonical(value) for value in values]
        catalog = sorted(
            set(encoded_values if catalog_values is None else [canonical(value) for value in catalog_values])
        )
        if not 1 <= len(catalog) <= 4096 or not set(encoded_values) <= set(catalog):
            raise ValueError("fixed catalog must contain all training values")
        if any(len(value) > 8192 for value in catalog):
            raise ValueError("value catalog entry exceeds limit")
        labels = np.array([catalog.index(value) for value in encoded_values])
        if support_ids is None:
            support_ids = [["unbound:" + address] for address in addresses]
        if len(support_ids) != len(keys):
            raise ValueError("source support must align with training rows")
        supports = {}
        for address, source_ids in zip(addresses, support_ids):
            if isinstance(source_ids, str):
                source_ids = [source_ids]
            if (
                not source_ids
                or len(source_ids) > 128
                or any(not isinstance(item, str) or not 0 < len(item) <= 256 for item in source_ids)
            ):
                raise ValueError("invalid source support")
            supports[address] = sorted(set(source_ids))
        cell = cls()
        cell.kind, cell.dimension, cell.hidden = kind, dimension, hidden
        cell.catalog = [json.loads(value) for value in catalog]
        cell.supports, cell.threshold = supports, 0.5
        cell.acceptance_enabled = True
        cell.lineage_sources = sorted(
            {item for ids in supports.values() for item in ids}
            | (set() if parent is None else set(parent.lineage_sources))
        )
        cell.calibration = None
        rng = np.random.default_rng(seed)
        cell.A = rng.normal(0, 1, (dimension, hidden))
        cell.a = np.zeros(hidden)
        cell.B = rng.normal(0, 0.03, (hidden, len(catalog)))
        cell.b = np.zeros(len(catalog))
        if parent is not None:
            if parent.kind != kind or parent.dimension != dimension:
                raise ValueError("incompatible parent representation")
            inherited = min(parent.hidden, hidden)
            cell.A[:, :inherited] = parent.A[:, :inherited]
            cell.a[:inherited] = parent.a[:inherited]
            for old_index, value in enumerate(parent.catalog):
                if value in cell.catalog:
                    index = cell.catalog.index(value)
                    cell.B[:inherited, index] = parent.B[:inherited, old_index]
                    cell.b[index] = parent.b[old_index]
        initial_parameters = cell.parameters_digest()
        x = encode(keys, dimension)
        arrays = [cell.A, cell.a, cell.B, cell.b]
        moments, variances = [np.zeros_like(v) for v in arrays], [np.zeros_like(v) for v in arrays]
        started_wall, started_cpu = time.perf_counter(), time.process_time()
        initial_loss = None
        for step in range(1, steps + 1):
            hidden_values = np.tanh(x @ cell.A + cell.a)
            logits = hidden_values @ cell.B + cell.b
            logits -= logits.max(axis=1, keepdims=True)
            probabilities = np.exp(logits)
            probabilities /= probabilities.sum(axis=1, keepdims=True)
            loss = -np.log(np.maximum(probabilities[np.arange(len(labels)), labels], 1e-300)).mean()
            if initial_loss is None:
                initial_loss = float(loss)
            delta = probabilities.copy()
            delta[np.arange(len(labels)), labels] -= 1
            delta /= len(labels)
            propagated = (delta @ cell.B.T) * (1 - hidden_values**2)
            gradients = [x.T @ propagated, propagated.sum(axis=0), hidden_values.T @ delta, delta.sum(axis=0)]
            norm = math.sqrt(sum(float((gradient**2).sum()) for gradient in gradients))
            for index, (weights, gradient) in enumerate(zip(arrays, gradients)):
                gradient *= min(1.0, 5.0 / max(norm, 1e-12))
                moments[index] = 0.9 * moments[index] + 0.1 * gradient
                variances[index] = 0.999 * variances[index] + 0.001 * gradient**2
                weights -= (
                    learning_rate
                    * (moments[index] / (1 - 0.9**step))
                    / (np.sqrt(variances[index] / (1 - 0.999**step)) + 1e-8)
                )
            if not np.isfinite(loss) or any(not np.isfinite(array).all() for array in arrays):
                raise ValueError("nonfinite trained model")
        cell.A, cell.a, cell.B, cell.b = [array.astype(np.float32) for array in arrays]
        final = cell.probabilities(keys)
        cell.training_receipt = {
            "kind": "actual-numpy-tanh-mlp-adam",
            "seed": seed,
            "steps": steps,
            "examples_seen": steps * len(keys),
            "rows": len(keys),
            "initial_cross_entropy": initial_loss,
            "final_cross_entropy": float(-np.log(np.maximum(final[np.arange(len(labels)), labels], 1e-300)).mean()),
            "training_accuracy": float(np.mean(final.argmax(axis=1) == labels)),
            "wall_seconds": time.perf_counter() - started_wall,
            "cpu_seconds": time.process_time() - started_cpu,
            "parent_parameters": None if parent is None else parent.parameters_digest(),
            "initial_parameters": initial_parameters,
            "inherited_hidden_units": 0 if parent is None else min(parent.hidden, hidden),
            "dataset_digest": hashlib.sha256(canonical(list(zip(addresses, values, support_ids)))).hexdigest(),
            "source_bound": not any(item.startswith("unbound:") for ids in supports.values() for item in ids),
            "catalog_contains_explicit_values": True,
            "language_model_finetuning": False,
            "catalog_fixed_by_caller": catalog_values is not None,
            "catalog_digest": hashlib.sha256(canonical(cell.catalog)).hexdigest(),
        }
        return cell

    def probabilities(self, keys):
        hidden = np.tanh(encode(keys, self.dimension) @ self.A + self.a)
        scores = hidden @ self.B + self.b
        scores -= scores.max(axis=1, keepdims=True)
        result = np.exp(scores)
        return result / result.sum(axis=1, keepdims=True)

    def read(self, key):
        address = key_digest(key)
        if address not in self.supports:
            return {"value": None, "confidence": 0.0, "abstain": "outside-written-support", "support_ids": []}
        probabilities = self.probabilities([key])[0]
        index = int(probabilities.argmax())
        confidence = float(probabilities[index])
        accepted = self.acceptance_enabled and confidence >= self.threshold
        return {
            "value": deepcopy(self.catalog[index]) if accepted else None,
            "confidence": confidence,
            "confidence_kind": "uncalibrated-softmax",
            "abstain": None if accepted else "below-selection-threshold",
            "support_ids": list(self.supports[address]),
            "parameter_digest": self.parameters_digest(),
            "kind": self.kind,
        }

    def calibrate(self, keys, values, *, maximum_error=0.05):
        if len(keys) != len(values) or not keys or not 0 <= maximum_error < 1:
            raise ValueError("invalid calibration rows or risk")
        probabilities = self.probabilities(keys)
        candidates = []
        for threshold in (0.0, 0.5, 0.7, 0.85, 0.9, 0.95, 0.99, 1.0):
            accepted = [
                i
                for i, key in enumerate(keys)
                if key_digest(key) in self.supports and probabilities[i].max() >= threshold
            ]
            errors = sum(self.catalog[int(probabilities[i].argmax())] != values[i] for i in accepted)
            candidates.append(
                {
                    "threshold": threshold,
                    "accepted": len(accepted),
                    "errors": errors,
                    "observed_risk": errors / len(accepted) if accepted else 0.0,
                }
            )
        feasible = [row for row in candidates if row["observed_risk"] <= maximum_error]
        selected = (
            min(feasible, key=lambda row: (-row["accepted"], row["errors"], row["threshold"]))
            if feasible
            else {"threshold": 1.0, "accepted": 0, "errors": 0, "observed_risk": 0.0}
        )
        self.acceptance_enabled = bool(feasible)
        self.threshold = selected["threshold"]
        self.calibration = {
            "selected": selected,
            "candidates": candidates,
            "rows": len(keys),
            "population_risk_guarantee": False,
        }
        return deepcopy(self.calibration)

    def parameters_digest(self):
        raw = b"".join(array.astype("<f4").tobytes() for array in (self.A, self.a, self.B, self.b))
        return hashlib.sha256(raw).hexdigest()

    def to_bytes(self):
        arrays = {}
        for name in ("A", "a", "B", "b"):
            value = getattr(self, name).astype("<f4")
            arrays[name] = {"shape": list(value.shape), "data": base64.b64encode(value.tobytes()).decode()}
        payload = {
            "schema": "hepta.memory.v6.associative-cell.v1",
            "kind": self.kind,
            "dimension": self.dimension,
            "hidden": self.hidden,
            "catalog": self.catalog,
            "supports": self.supports,
            "threshold": self.threshold,
            "calibration": self.calibration,
            "acceptance_enabled": self.acceptance_enabled,
            "lineage_sources": self.lineage_sources,
            "arrays": arrays,
            "training_receipt": self.training_receipt,
        }
        return canonical({"payload": payload, "sha256": hashlib.sha256(canonical(payload)).hexdigest()})

    @classmethod
    def from_bytes(cls, raw):
        if not isinstance(raw, bytes) or len(raw) > 32_000_000:
            raise ValueError("invalid cell artifact size")
        envelope = json.loads(raw)
        if set(envelope) != {"payload", "sha256"}:
            raise ValueError("invalid artifact envelope")
        payload = envelope["payload"]
        if hashlib.sha256(canonical(payload)).hexdigest() != envelope["sha256"]:
            raise ValueError("cell artifact digest mismatch")
        expected = {
            "schema",
            "kind",
            "dimension",
            "hidden",
            "catalog",
            "supports",
            "threshold",
            "acceptance_enabled",
            "calibration",
            "lineage_sources",
            "arrays",
            "training_receipt",
        }
        if set(payload) != expected or payload["schema"] != "hepta.memory.v6.associative-cell.v1":
            raise ValueError("invalid cell schema")
        cell = cls()
        for name in expected - {"schema", "arrays"}:
            setattr(cell, name, payload[name])
        if (
            cell.kind not in {"semantic", "procedure"}
            or type(cell.dimension) is not int
            or type(cell.hidden) is not int
            or not 8 <= cell.dimension <= 1024
            or not 1 <= cell.hidden <= 256
        ):
            raise ValueError("invalid cell dimensions")
        if not 1 <= len(cell.catalog) <= 4096 or len({canonical(v) for v in cell.catalog}) != len(cell.catalog):
            raise ValueError("invalid value catalog")
        if (
            type(cell.acceptance_enabled) is not bool
            or not 0 <= cell.threshold <= 1
            or not 1 <= len(cell.supports) <= 4096
        ):
            raise ValueError("invalid support or threshold")
        for address, ids in cell.supports.items():
            if (
                len(address) != 64
                or any(c not in "0123456789abcdef" for c in address)
                or not ids
                or len(ids) > 128
                or any(not isinstance(item, str) or not 0 < len(item) <= 256 for item in ids)
            ):
                raise ValueError("invalid address/source support")
        if cell.lineage_sources != sorted(set(cell.lineage_sources)) or not {
            item for ids in cell.supports.values() for item in ids
        } <= set(cell.lineage_sources):
            raise ValueError("missing or noncanonical training lineage")
        shapes = {
            "A": (cell.dimension, cell.hidden),
            "a": (cell.hidden,),
            "B": (cell.hidden, len(cell.catalog)),
            "b": (len(cell.catalog),),
        }
        if set(payload["arrays"]) != set(shapes):
            raise ValueError("invalid tensor inventory")
        for name, shape in shapes.items():
            descriptor = payload["arrays"][name]
            data = base64.b64decode(descriptor["data"], validate=True)
            if (
                set(descriptor) != {"data", "shape"}
                or tuple(descriptor["shape"]) != shape
                or len(data) != int(np.prod(shape)) * 4
            ):
                raise ValueError("invalid tensor shape or byte count")
            value = np.frombuffer(data, dtype="<f4").reshape(shape).copy()
            if not np.isfinite(value).all():
                raise ValueError("nonfinite tensor")
            setattr(cell, name, value)
        return cell

    def cost(self):
        return {
            "serialized_bytes": len(self.to_bytes()),
            "parameter_bytes": sum(getattr(self, name).nbytes for name in ("A", "a", "B", "b")),
            "catalog_bytes": len(canonical(self.catalog)),
            "support_bytes": len(canonical(self.supports)),
            "training_steps": self.training_receipt["steps"],
            "training_cpu_seconds": self.training_receipt["cpu_seconds"],
        }
