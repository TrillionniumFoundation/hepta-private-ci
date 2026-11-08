"""Shared frozen feature providers and independently trainable semantic Cell heads.

Providers must return one independent, synchronous feature row per input. A real
LLM/VLM can supply ``encode_batch`` and its verified, frozen weight fingerprint;
no model is constructed or cloned by this module. Fingerprints are provider
attestations, not proof that arbitrary injected Python code is side-effect free.
"""

import copy
import hashlib
import math
import re
import threading
import time
from itertools import islice
from dataclasses import dataclass, replace

import numpy as np


def _digest(*parts):
    result = hashlib.sha256()
    for part in parts:
        value = part if isinstance(part, bytes) else str(part).encode()
        result.update(len(value).to_bytes(8, "big"))
        result.update(value)
    return result.hexdigest()


def _frozen(value):
    array = np.asarray(value, dtype=np.float64)
    if not np.isfinite(array).all():
        raise ValueError("parameters and features must be finite")
    # A bytes owner prevents callers from re-enabling ndarray writeability.
    return np.frombuffer(array.tobytes(), dtype=np.float64).reshape(array.shape)


@dataclass(frozen=True)
class SemanticBinding:
    base: str
    model: str
    encoder: str
    tokenizer: str
    numeric_profile: str
    domain: str | None = None

    def __post_init__(self):
        for value in self.backend_key + (() if self.domain is None else (self.domain,)):
            if not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{64}", value) or value == "0" * 64:
                raise ValueError("bindings require nonzero lowercase SHA-256 identities")

    @property
    def backend_key(self):
        return (self.base, self.model, self.encoder, self.tokenizer, self.numeric_profile)

    @property
    def batch_key(self):
        return self.backend_key + (self.domain,)


class CallableFeatureBackend:
    """An injected encoder, with optional actual host arrays for memory accounting."""

    def __init__(self, binding, feature_dim, encode_batch, fingerprint, resident_arrays=()):
        if binding.domain is not None or type(feature_dim) is not int or feature_dim < 1:
            raise ValueError("the shared backend requires base binding and positive feature_dim")
        if not callable(encode_batch) or not callable(fingerprint):
            raise ValueError("encoder and frozen-weight fingerprint callbacks are required")
        self.binding, self.feature_dim = binding, feature_dim
        self._encode, self._fingerprint = encode_batch, fingerprint
        self.resident_arrays = tuple(resident_arrays)
        if any(not isinstance(array, np.ndarray) for array in self.resident_arrays):
            raise TypeError("resident_arrays must be actual NumPy arrays, not estimates")
        self.assert_frozen()

    def assert_frozen(self):
        if self._fingerprint() != self.binding.base:
            raise ValueError("shared base fingerprint differs from the bound artifact")

    def encode(self, inputs):
        self.assert_frozen()
        try:
            result = _frozen(self._encode(tuple(inputs)))
        finally:
            self.assert_frozen()
        if result.shape != (len(inputs), self.feature_dim):
            raise ValueError("encoder returned an incompatible feature shape")
        return result


@dataclass(frozen=True, init=False, eq=False)
class FrozenDomainAdapter:
    """An optional shared, frozen feature projection tied to an exact backend."""

    def __init__(self, binding, matrix):
        if binding.domain is not None:
            raise ValueError("domain adapters attach directly to a base binding")
        object.__setattr__(self, "backend_key", binding.backend_key)
        object.__setattr__(self, "matrix", _frozen(matrix))
        if self.matrix.ndim != 2 or min(self.matrix.shape) < 1:
            raise ValueError("domain adapter requires a nonempty matrix")
        object.__setattr__(self, "digest", _digest("frozen-domain-v1", self.backend_key,
                                                self.matrix.shape, self.matrix.tobytes()))


@dataclass(frozen=True)
class LocalObjective:
    kind: str
    output_dim: int
    target_name: str

    def __post_init__(self):
        if self.kind not in ("mse", "cross_entropy") or type(self.output_dim) is not int or self.output_dim < 1:
            raise ValueError("unsupported local objective or output dimension")
        if not isinstance(self.target_name, str) or not self.target_name.strip():
            raise ValueError("a named local learning target is required")

    def targets(self, targets, rows):
        values = np.asarray(targets)
        if self.kind == "mse":
            values = _frozen(values)
            if values.shape != (rows, self.output_dim):
                raise ValueError("MSE targets must match (input rows, output_dim)")
        elif values.shape != (rows,) or values.dtype.kind not in "iu" or np.any(values < 0) or np.any(values >= self.output_dim):
            raise ValueError("cross-entropy targets must be valid integer class labels")
        return values.copy()

    def loss_and_gradient(self, logits, targets):
        if self.kind == "mse":
            error = logits - targets
            return float(np.mean(error * error)), 2 * error / error.size
        shifted = logits - np.max(logits, axis=1, keepdims=True)
        exp = np.exp(shifted)
        total = np.sum(exp, axis=1, keepdims=True)
        loss = np.mean(np.log(total[:, 0]) - shifted[np.arange(len(targets)), targets])
        grad = exp / total
        grad[np.arange(len(targets)), targets] -= 1
        return float(loss), grad / len(targets)


@dataclass(frozen=True)
class LocalHead:
    """A private linear head or a trainable low-rank factorization plus bias."""

    first: np.ndarray
    bias: np.ndarray
    second: np.ndarray | None = None

    def __post_init__(self):
        object.__setattr__(self, "first", _frozen(self.first))
        object.__setattr__(self, "bias", _frozen(self.bias))
        if self.second is not None:
            object.__setattr__(self, "second", _frozen(self.second))
        if self.first.ndim != 2 or self.bias.ndim != 1 or min(self.first.shape) < 1:
            raise ValueError("invalid local head shape")
        width = self.first.shape[1]
        if self.second is not None:
            if self.second.ndim != 2 or self.second.shape[0] != width:
                raise ValueError("low-rank factor dimensions differ")
            width = self.second.shape[1]
        if self.bias.shape != (width,) or width < 1:
            raise ValueError("local head bias shape differs")

    @classmethod
    def initialize(cls, feature_dim, output_dim, rank=None, seed=0):
        if rank is None:
            return cls(np.zeros((feature_dim, output_dim)), np.zeros(output_dim))
        if type(rank) is not int or not 1 <= rank <= min(feature_dim, output_dim):
            raise ValueError("rank must fit both feature and output dimensions")
        left = np.random.default_rng(seed).normal(0, .05, (feature_dim, rank))
        return cls(left, np.zeros(output_dim), np.zeros((rank, output_dim)))

    @property
    def arrays(self):
        return (self.first, self.bias) + (() if self.second is None else (self.second,))

    @property
    def digest(self):
        return _digest("local-head-v1", *(_digest(a.dtype.str, a.shape, a.tobytes()) for a in self.arrays))

    def predict(self, features):
        hidden = features @ self.first
        return (hidden if self.second is None else hidden @ self.second) + self.bias

    def gradient_step(self, features, gradient, rate):
        if self.second is None:
            return LocalHead(self.first - rate * features.T @ gradient, self.bias - rate * gradient.sum(axis=0))
        hidden = features @ self.first
        return LocalHead(self.first - rate * features.T @ (gradient @ self.second.T),
                         self.bias - rate * gradient.sum(axis=0),
                         self.second - rate * hidden.T @ gradient)


@dataclass(frozen=True)
class SemanticBudget:
    """Input/update limits and a local array estimate, not an external-server RAM cap."""

    max_items: int = 256
    max_input_bytes: int = 1048576
    max_working_bytes: int = 16777216
    max_train_steps: int = 128
    max_total_items: int = 100000

    def __post_init__(self):
        ceilings = (4096, 8 * 1048576, 256 * 1048576, 1024, 10**9)
        if any(type(value) is not int or not 0 <= value <= ceiling
               for value, ceiling in zip(vars(self).values(), ceilings)):
            raise ValueError("budgets require bounded nonnegative integer limits")


class SemanticCell:
    """Cell-local parameters, state, retrieval view and charged feature budget."""

    def __init__(self, cell_id, binding, head, objective, budget=None, state=None, retrieval_view=()):
        if not isinstance(cell_id, str) or not cell_id or head.bias.shape != (objective.output_dim,):
            raise ValueError("cell identity and objective must match the local head")
        self.cell_id, self.binding, self.objective = cell_id, binding, objective
        self.head = LocalHead(head.first, head.bias, head.second)
        self.budget = budget if budget is not None else SemanticBudget()
        self._state = copy.deepcopy({} if state is None else state)
        self._retrieval_view = tuple(copy.deepcopy(retrieval_view))
        self._used_items = 0

    @property
    def state(self):
        return copy.deepcopy(self._state)

    def set_state(self, state):
        self._state = copy.deepcopy(state)

    @property
    def retrieval_view(self):
        return copy.deepcopy(self._retrieval_view)

    @property
    def used_items(self):
        return self._used_items

    @property
    def digest(self):
        return _digest("semantic-cell-v1", self.cell_id, self.binding.batch_key, self.head.digest,
                       self.objective.kind, self.objective.output_dim, self.objective.target_name)


@dataclass(frozen=True)
class SemanticCandidate:
    cell_id: str
    source_digest: str
    binding: SemanticBinding
    objective: LocalObjective
    head: LocalHead
    dataset_digest: str
    steps: int
    loss_before: float
    loss_after: float
    training_receipt: dict


class SemanticTrainingError(ValueError):
    """A failed attempt with measured costs that callers must retain."""

    def __init__(self, message, receipt):
        super().__init__(message)
        self.receipt = receipt


class SharedSemanticPool:
    """Reuse providers by complete compatibility; never install trained candidates."""

    def __init__(self, max_batch_cells=64, max_batch_items=4096,
                 max_batch_input_bytes=8 * 1048576, max_batch_working_bytes=256 * 1048576):
        values = (max_batch_cells, max_batch_items, max_batch_input_bytes, max_batch_working_bytes)
        ceilings = (64, 4096, 8 * 1048576, 256 * 1048576)
        if any(type(v) is not int or not 1 <= v <= cap for v, cap in zip(values, ceilings)):
            raise ValueError("shared batch bounds exceed the host array envelope")
        self.batch_limits = values
        self._backends, self._domains = {}, {}
        self._lock = threading.RLock()

    def register_backend(self, backend):
        with self._lock:
            key = backend.binding.backend_key
            if key in self._backends and self._backends[key] is not backend:
                raise ValueError("a different backend already owns this binding")
            backend.assert_frozen()
            self._backends[key] = backend
        return backend.binding

    def register_domain(self, adapter):
        with self._lock:
            backend = self._backends.get(adapter.backend_key)
            if backend is None or adapter.matrix.shape[0] != backend.feature_dim:
                raise ValueError("domain adapter backend binding or shape differs")
            self._domains[adapter.digest] = adapter
        return replace(backend.binding, domain=adapter.digest)

    def _resolve(self, cell):
        backend = self._backends.get(cell.binding.backend_key)
        if backend is None or backend.binding.backend_key != cell.binding.backend_key:
            raise ValueError("unregistered base/model/encoder/tokenizer/numeric binding")
        domain = self._domains.get(cell.binding.domain) if cell.binding.domain else None
        if cell.binding.domain is not None and (domain is None or domain.backend_key != backend.binding.backend_key):
            raise ValueError("unregistered or incompatible domain binding")
        dim = backend.feature_dim if domain is None else domain.matrix.shape[1]
        if cell.head.first.shape[0] != dim:
            raise ValueError("head feature dimension differs from bound encoder/domain")
        return backend, domain, dim

    def _prepare(self, cell, inputs, steps=0):
        backend, domain, dim = self._resolve(cell)
        items = tuple(islice(inputs, cell.budget.max_items + 1))
        if not items or len(items) > cell.budget.max_items or cell.used_items + len(items) > cell.budget.max_total_items:
            raise ValueError("cell item budget exceeded or empty batch")
        sizes = []
        for value in items:
            if isinstance(value, str):
                sizes.append(len(value.encode()))
            elif isinstance(value, bytes):
                sizes.append(len(value))
            elif isinstance(value, np.ndarray) and value.dtype.kind in "biuf":
                sizes.append(value.nbytes)
            else:
                raise ValueError("inputs must be text, bytes or numeric image/feature arrays")
        working = 2 * sum(sizes) + len(items) * (backend.feature_dim + 3 * dim + 4 * cell.objective.output_dim) * 8
        working += sum(a.nbytes for a in cell.head.arrays) * (5 if steps else 1)
        if sum(sizes) > cell.budget.max_input_bytes or working > cell.budget.max_working_bytes or steps > cell.budget.max_train_steps:
            raise ValueError("cell input/working-memory/training budget exceeded")
        return backend, domain, items, sum(sizes), working

    def predict_batch(self, requests):
        """Return output arrays in request order and measured host-only batch costs."""
        with self._lock:
            requests = list(islice(requests, self.batch_limits[0] + 1))
            if not requests or len(requests) > self.batch_limits[0]:
                raise ValueError("shared batch cell-count bound exceeded or empty batch")
            # One cell per request avoids aggregate budget bypass via duplicate rows.
            if len({id(cell) for cell, _ in requests}) != len(requests):
                raise ValueError("combine each cell's inputs into a single request")
            prepared = [self._prepare(cell, inputs) for cell, inputs in requests]
            totals = (sum(len(p[2]) for p in prepared), sum(p[3] for p in prepared), sum(p[4] for p in prepared))
            if any(total > limit for total, limit in zip(totals, self.batch_limits[1:])):
                raise ValueError("shared batch total items/input/array-working bound exceeded")
            groups, outputs, measurements = {}, [None] * len(requests), []
            for index, ((cell, _), (backend, domain, items, _, _)) in enumerate(zip(requests, prepared)):
                groups.setdefault(cell.binding.batch_key, []).append((index, cell, backend, domain, items))
            for _, cell, _, _, items in (entry for group in groups.values() for entry in group):
                cell._used_items += len(items)  # Attempted work remains charged on provider failure.
            for key, group in groups.items():
                items = tuple(value.copy() if isinstance(value, np.ndarray) else value
                              for entry in group for value in entry[4])
                start = time.perf_counter_ns()
                features = group[0][2].encode(items)
                if group[0][3] is not None:
                    features = features @ group[0][3].matrix
                offset = 0
                for index, cell, _, _, inputs in group:
                    outputs[index] = _frozen(cell.head.predict(features[offset:offset + len(inputs)]))
                    offset += len(inputs)
                measurements.append({"binding": key, "items": len(items), "feature_array_bytes": int(features.nbytes),
                                     "host_wall_ns": time.perf_counter_ns() - start, "gpu_memory_measured": False})
            return outputs, measurements

    def train_candidate(self, cell, inputs, targets, *, steps=1, learning_rate=.01):
        wall, cpu = time.perf_counter(), time.process_time()
        receipt = {"schema": "hepta.cell.semantic-training.v1", "status": "started",
                   "cell_id": cell.cell_id, "source_digest": cell.digest,
                   "requested_steps": steps if type(steps) is int else repr(steps)[:80], "completed_steps": 0,
                   "learning_rate": learning_rate if type(learning_rate) in (int, float) and math.isfinite(learning_rate)
                   else repr(learning_rate)[:80],
                   "objective": cell.objective.kind, "target_name": cell.objective.target_name,
                   "energy_joules": None, "peak_ram_bytes": None, "peak_vram_bytes": None,
                   "measurement_scope": "host wall/CPU and local array estimate; external encoder residency unmeasured"}
        try:
            with self._lock:
                if type(steps) is not int or steps < 1 or not math.isfinite(learning_rate) or learning_rate <= 0:
                    raise ValueError("training requires positive finite learning rate and integer steps")
                backend, domain, items, input_bytes, working = self._prepare(cell, inputs, steps)
                target = cell.objective.targets(targets, len(items))
                source_digest = cell.digest
                receipt.update(items=len(items), input_bytes=input_bytes, estimated_local_array_working_bytes=working)
                cell._used_items += len(items)
                copied = tuple(value.copy() if isinstance(value, np.ndarray) else value for value in items)
                features = backend.encode(copied)
                if domain is not None:
                    features = features @ domain.matrix
                head = cell.head
                before, _ = cell.objective.loss_and_gradient(head.predict(features), target)
                for _ in range(steps):
                    _, gradient = cell.objective.loss_and_gradient(head.predict(features), target)
                    head = head.gradient_step(features, gradient, learning_rate)
                    receipt["completed_steps"] += 1
                after, _ = cell.objective.loss_and_gradient(head.predict(features), target)
                if not math.isfinite(after):
                    raise ValueError("training produced nonfinite loss")
                encoded = tuple(_digest("array", value.dtype.str, value.shape, value.tobytes())
                                if isinstance(value, np.ndarray) else _digest(type(value).__name__, value) for value in copied)
                dataset = _digest("semantic-dataset-v1", *encoded, target.shape, target.dtype.str, target.tobytes())
                receipt.update(status="completed", loss_before=before, loss_after=after,
                               feature_array_bytes=int(features.nbytes), dataset_digest=dataset)
        except Exception as error:
            receipt.update(status="failed", error_type=type(error).__name__, error=str(error))
            raise SemanticTrainingError(str(error), receipt) from error
        finally:
            receipt.update(host_wall_seconds=time.perf_counter() - wall, process_cpu_seconds=time.process_time() - cpu)
        return SemanticCandidate(cell.cell_id, source_digest, cell.binding, cell.objective, head,
                                 dataset, steps, before, after, receipt)

    def memory_report(self, cells):
        """Count observed host array storage once; no RSS, VRAM or serving claim."""
        with self._lock:
            cells = list(cells)
            backends, domains, storages = {}, {}, {}
            for cell in cells:
                backend, domain, _ = self._resolve(cell)
                backends[id(backend)] = backend
                if domain is not None:
                    domains[domain.digest] = domain
            for array in [a for backend in backends.values() for a in backend.resident_arrays] + [a.matrix for a in domains.values()]:
                root = array
                while isinstance(root.base, np.ndarray):
                    root = root.base
                storages[(root.__array_interface__["data"][0], root.nbytes)] = root.nbytes
            private = sum(a.nbytes for cell in {id(c): c for c in cells}.values() for a in cell.head.arrays)
            return {"measurement_kind": "observed_host_array_storage_bytes", "shared_array_bytes": sum(storages.values()),
                    "private_head_array_bytes": private, "backend_count": len(backends), "domain_count": len(domains),
                    "unmeasured_backend_count": sum(not b.resident_arrays for b in backends.values()),
                    "gpu_memory_measured": False, "includes_python_overhead": False}
