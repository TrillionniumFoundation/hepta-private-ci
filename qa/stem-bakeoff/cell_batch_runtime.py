"""Batched private readouts over version-bound, precomputed shared features.

This local research runtime owns no Encoder. Task IDs are declared lineage,
not a claim that each resident copy learned a distinct task.
"""

from collections import OrderedDict
import hashlib
import re
import time

import numpy as np

from cell_learning_models import normalize_features


class BatchRuntimeError(ValueError):
    pass


def _digest(value):
    if type(value) is not str or not re.fullmatch(r"[0-9a-f]{64}", value):
        raise BatchRuntimeError("exact SHA256 identity required")
    return value


def _integer(value, low, high):
    if type(value) is not int or not low <= value <= high:
        raise BatchRuntimeError("integer outside bounded runtime range")
    return value


def _frozen(value):
    array = np.asarray(value, dtype=np.float64, order="C")
    if not np.isfinite(array).all():
        raise BatchRuntimeError("nonfinite feature or private parameter")
    return np.frombuffer(array.tobytes(), dtype=np.float64).reshape(array.shape)


class GlobalFeatureCache:
    """LRU cache with an exact tensor-byte budget and immutable returned views."""

    def __init__(self, capacity_bytes, capacity_entries=4096):
        self.capacity_bytes = _integer(capacity_bytes, 0, 2**30)
        self.capacity_entries = _integer(capacity_entries, 1, 65536)
        self.bytes = self.hits = self.misses = self.evictions = 0
        self._rows = OrderedDict()

    def put(self, key, row):
        value = _frozen(row)
        if value.ndim != 1 or not 1 <= value.size <= 4096:
            raise BatchRuntimeError("one bounded global feature required")
        previous = self._rows.get(key)
        if previous is not None:
            if not np.array_equal(previous, value):
                raise BatchRuntimeError("source identity reused for different features")
            self._rows.move_to_end(key)
            return
        if value.nbytes > self.capacity_bytes:
            return
        while (self.bytes + value.nbytes > self.capacity_bytes
               or len(self._rows) >= self.capacity_entries):
            _, removed = self._rows.popitem(last=False)
            self.bytes -= removed.nbytes
            self.evictions += 1
        self._rows[key] = value
        self.bytes += value.nbytes

    def get(self, key):
        value = self._rows.get(key)
        if value is None:
            self.misses += 1
            return None
        self.hits += 1
        self._rows.move_to_end(key)
        return value


class BatchedCellRuntime:
    """Vectorize a homogeneous cohort of frozen NumpyCellHead parameters."""

    def __init__(self, heads, cell_ids, task_ids, feature_identity, *,
                 generation=1, cache_bytes=0, router_keys=None):
        count = _integer(len(heads), 1, 4096)
        self.generation = _integer(generation, 1, 2**63 - 1)
        self.feature_identity = _digest(feature_identity)
        self.cell_ids, self.task_ids = tuple(cell_ids), tuple(task_ids)
        if (len(self.cell_ids) != count or len(self.task_ids) != count
                or len(set(self.cell_ids)) != count
                or any(type(v) is not str or not 1 <= len(v) <= 256
                       for v in (*self.cell_ids, *self.task_ids))):
            raise BatchRuntimeError("bounded unique Cell IDs and task lineage required")
        first = heads[0]
        self.mode, self.width, self.classes = first.mode, first.width, first.classes
        self.rank = first.rank
        _integer(self.width, 1, 4096)
        _integer(self.classes, 2, 256)
        _integer(self.rank, 1, 64)
        shapes = {"W": (self.width, self.classes), "b": (self.classes,)}
        if self.mode in ("gated", "residual"):
            shapes.update(a=(self.width,), g=(self.width,))
        if self.mode == "residual":
            shapes.update(V=(self.width, self.rank), U=(self.rank, self.width))
        if self.mode not in ("linear", "gated", "residual"):
            raise BatchRuntimeError("unsupported private Head mode")
        if count * sum(np.prod(shape) for shape in shapes.values()) * 8 > 2**30:
            raise BatchRuntimeError("private cohort exceeds one GiB tensor budget")
        for head in heads:
            if getattr(head, "feature_identity", None) not in (None, self.feature_identity):
                raise BatchRuntimeError("private Head artifact belongs to a different feature identity")
            if ((head.mode, head.width, head.classes, head.rank)
                    != (self.mode, self.width, self.classes, self.rank)
                    or set(head.params) != set(shapes)
                    or any(np.asarray(head.params[k]).shape != shape for k, shape in shapes.items())):
                raise BatchRuntimeError("mixed or malformed private Head cohort")
        self.bound_head_count = sum(getattr(h, "feature_identity", None) == self.feature_identity for h in heads)
        self._params = {k: _frozen(np.stack([h.params[k] for h in heads])) for k in shapes}
        self.parameter_bytes = sum(v.nbytes for v in self._params.values())
        self.parameter_digests = tuple(hashlib.sha256(b"".join(
            self._params[k][i].tobytes() for k in sorted(shapes))).hexdigest() for i in range(count))
        self.cache = GlobalFeatureCache(cache_bytes)
        self._router = None
        if router_keys is not None:
            keys = _frozen(router_keys)
            if keys.shape != (count, self.width):
                raise BatchRuntimeError("router prototype shape differs from cohort")
            self._router = _frozen(normalize_features(keys))
        self.dispatch_calls = self.head_evaluations = self.array_batches = 0

    def _guard(self, feature_identity, generation):
        if (_digest(feature_identity) != self.feature_identity
                or _integer(generation, 1, 2**63 - 1) != self.generation):
            raise BatchRuntimeError("stale Encoder/preprocessor/feature generation")

    def predict(self, features, *, source_digests, feature_identity, generation,
                top_k=None, router_scores=None):
        started = time.perf_counter_ns()
        self._guard(feature_identity, generation)
        x = np.asarray(features)
        if x.ndim != 2 or not 1 <= len(x) <= 64 or x.shape[1] != self.width:
            raise BatchRuntimeError("expected one to 64 global feature rows")
        x = _frozen(x)
        sources = tuple(source_digests)
        if len(sources) != len(x):
            raise BatchRuntimeError("source rows do not match feature rows")
        for source in sources:
            _digest(source)
        count = len(self.cell_ids)
        k = count if top_k is None else _integer(top_k, 1, count)
        cached_at = time.perf_counter_ns()
        for source, row in zip(sources, x, strict=True):
            self.cache.put((self.feature_identity, generation, source), row)
        cache_ns = time.perf_counter_ns() - cached_at
        normalized = normalize_features(x)
        routed_at = time.perf_counter_ns()
        if router_scores is not None:
            scores = _frozen(router_scores)
            route_mode = "provided_scores"
        elif k < count and self._router is not None:
            scores = normalized @ self._router.T
            route_mode = "shared_prototype_dot"
        elif k < count:
            raise BatchRuntimeError("selective dispatch requires explicit routing scores or prototypes")
        else:
            scores = np.zeros((len(x), count))
            route_mode = "all_cells"
        if scores.shape != (len(x), count):
            raise BatchRuntimeError("router scores do not bind every input and Cell")
        selected = np.argsort(-scores, axis=1, kind="stable")[:, :k]
        router_ns = time.perf_counter_ns() - routed_at
        logits = np.empty((len(x), k, self.classes), dtype=np.float64)
        head_at = time.perf_counter_ns()
        p = self._params
        for row, indices in enumerate(selected):
            z = np.broadcast_to(normalized[row], (k, self.width))
            if self.mode != "linear":
                gate = np.clip(z * p["a"][indices] + p["g"][indices], -40, 40)
                z = z / (1 + np.exp(-gate))
            if self.mode == "residual":
                hidden = np.tanh(np.einsum("d,ndr->nr", normalized[row], p["V"][indices]))
                z = z + np.einsum("nr,nrd->nd", hidden, p["U"][indices])
            logits[row] = np.einsum("nd,ndc->nc", z, p["W"][indices]) + p["b"][indices]
        head_ns = time.perf_counter_ns() - head_at
        if not np.isfinite(logits).all():
            raise BatchRuntimeError("nonfinite batched private prediction")
        self.dispatch_calls += 1
        self.head_evaluations += len(x) * k
        self.array_batches += len(x)
        return {"logits": logits, "selected_indices": selected,
                "selected_cell_ids": [[self.cell_ids[i] for i in ids] for ids in selected],
                "source_digests": sources, "feature_identity": self.feature_identity,
                "generation": generation, "route_mode": route_mode,
                "activated_cell_fraction": k / count,
                "head_evaluations": len(x) * k, "head_array_batches": len(x),
                "encoder_invocations_by_runtime": 0, "cache_tensor_bytes": self.cache.bytes,
                "cache_ns": cache_ns, "router_ns": router_ns, "head_ns": head_ns,
                "elapsed_ns": time.perf_counter_ns() - started}

    def predict_cached(self, source_digests, *, feature_identity, generation, **options):
        self._guard(feature_identity, generation)
        source_digests = tuple(source_digests)
        _integer(len(source_digests), 1, 64)
        values = [self.cache.get((self.feature_identity, generation, _digest(s))) for s in source_digests]
        if not values or any(value is None for value in values):
            raise BatchRuntimeError("cache miss requires explicit source re-encoding")
        return self.predict(np.stack(values), source_digests=source_digests,
                            feature_identity=feature_identity, generation=generation, **options)

    def predict_feature_batch(self, batch, **options):
        batch.verify_integrity()
        return self.predict(batch.read_global().detach().cpu().double().numpy(),
                            source_digests=batch.source_record_digests,
                            feature_identity=batch.feature_identity_digest,
                            generation=batch.identity.generation, **options)

    def accounting(self):
        return {"resident_cells": len(self.cell_ids),
                "declared_task_ids": sorted(set(self.task_ids)),
                "declared_task_count": len(set(self.task_ids)),
                "unique_parameter_states": len(set(self.parameter_digests)),
                "artifact_identity_bound_head_count": self.bound_head_count,
                "unbound_in_memory_head_count": len(self.cell_ids) - self.bound_head_count,
                "private_parameter_tensor_bytes": self.parameter_bytes,
                "router_tensor_bytes": 0 if self._router is None else self._router.nbytes,
                "cache_tensor_bytes": self.cache.bytes,
                "cache_entry_count": len(self.cache._rows), "cache_entry_capacity": self.cache.capacity_entries,
                "cache_metadata_bytes_measured": False,
                "dispatch_calls": self.dispatch_calls, "head_evaluations": self.head_evaluations,
                "head_array_batches": self.array_batches,
                "encoder_instances_owned": 0, "optimizer_instances_owned": 0}
