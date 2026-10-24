"""Bounded private Adam updates over a shared, immutable training feature bank.

This engineering trainer implements the same loss, clipping and optimizer as
NumpyCellHead.train. Every Cell owns separate weights and Adam moments. It never
updates an encoder, uses heldout labels, or merges independent learning states.
"""

from dataclasses import dataclass
import hashlib
import re
import time

import numpy as np

from cell_learning_models import NumpyCellHead, canonical, normalize_features


def frozen(array):
    value = np.ascontiguousarray(array)
    return np.frombuffer(value.tobytes(), dtype=value.dtype).reshape(value.shape)


def identity(value):
    if type(value) is not str or re.fullmatch(r"[a-f0-9]{64}", value) is None:
        raise ValueError("full feature identity digest required")
    return value


@dataclass(frozen=True)
class FrozenTrainingBank:
    feature_identity: str
    task_ids: tuple
    source_ids: tuple
    _raw: np.ndarray
    _normalized: np.ndarray
    _indices: np.ndarray

    def __post_init__(self):
        identity(self.feature_identity)
        if (type(self.task_ids) is not tuple or type(self.source_ids) is not tuple
                or not 1 <= len(self.task_ids) <= 64 or not 1 <= len(self.source_ids) <= 16384
                or any(type(t) is not str or not 1 <= len(t.encode()) <= 256 for t in self.task_ids)
                or any(type(s) is not str or not 1 <= len(s.encode()) <= 512 for s in self.source_ids)):
            raise ValueError("immutable bounded task/source identities required")
        for array in (self._raw, self._normalized, self._indices):
            base = array
            while isinstance(base, np.ndarray): base = base.base
            if not isinstance(base, bytes) or array.flags.writeable:
                raise ValueError("cached training tensors must own immutable byte storage")
        if (self._raw.dtype != np.float64 or self._normalized.dtype != np.float64
                or self._indices.dtype != np.int64 or self._indices.ndim != 2
                or len(self.task_ids) != len(self._indices) or len(set(self.task_ids)) != len(self.task_ids)
                or len(self.source_ids) != len(self._raw) or len(set(self.source_ids)) != len(self.source_ids)
                or self._normalized.shape != self._raw.shape
                or not np.array_equal(self._normalized, normalize_features(self._raw))
                or np.any(self._indices < 0) or np.any(self._indices >= len(self._raw))):
            raise ValueError("cached source mapping or normalization differs")

    @classmethod
    def build(cls, features, source_ids, feature_identity, *, max_tensor_bytes=64 * 1024**2):
        identity(feature_identity)
        if (not isinstance(features, dict) or not 1 <= len(features) <= 64 or set(features) != set(source_ids)
                or type(max_tensor_bytes) is not int or not 4096 <= max_tensor_bytes <= 256 * 1024**2):
            raise ValueError("bounded named training banks and tensor budget required")
        tasks = tuple(sorted(features))
        shapes = [np.shape(features[t]) for t in tasks]
        if (any(type(t) is not str or not 1 <= len(t) <= 256 for t in tasks)
                or any(s != shapes[0] for s in shapes) or len(shapes[0]) != 2
                or not 1 <= shapes[0][0] <= 256 or not 1 <= shapes[0][1] <= 4096
                or sum(int(np.prod(s)) * 16 + s[0]*8 for s in shapes) > max_tensor_bytes):
            raise ValueError("compatible bounded source matrices exceed feature bank budget")
        lookup, vectors, sources, indices = {}, [], [], []
        for task in tasks:
            matrix, rows = np.asarray(features[task], dtype=np.float64), []
            if not np.isfinite(matrix).all() or len(source_ids[task]) != len(matrix):
                raise ValueError("finite source-bound training features required")
            for source, vector in zip(source_ids[task], matrix, strict=True):
                if type(source) is not str or not 1 <= len(source.encode()) <= 512:
                    raise ValueError("bounded source IDs required")
                if source in lookup:
                    at = lookup[source]
                    if vector.tobytes() != vectors[at].tobytes():
                        raise ValueError("same source has conflicting cached feature values")
                else:
                    at = lookup[source] = len(vectors)
                    sources.append(source)
                    vectors.append(vector.copy())
                rows.append(at)
            if len(set(rows)) != len(rows):
                raise ValueError("a training bank cannot repeat a source")
            indices.append(rows)
        raw = frozen(np.stack(vectors))
        return cls(feature_identity, tasks, tuple(sources), raw,
                   frozen(normalize_features(raw)), frozen(np.array(indices, dtype=np.int64)))

    def raw_rows(self, task):
        return frozen(self._raw[self._indices[self.task_ids.index(task)]])

    @property
    def tensor_bytes(self):
        return self._raw.nbytes + self._normalized.nbytes + self._indices.nbytes


def loss_gradients(params, x, y, weight, mode, l2):
    """All reductions keep the leading private Cell axis independent."""
    u, gate, hidden = x, None, None
    if mode != "linear":
        gate = 1 / (1 + np.exp(-np.clip(x * params["a"][:, None, :] + params["g"][:, None, :], -40, 40)))
        u = x * gate
    if mode == "residual":
        hidden = np.tanh(x @ params["V"])
        u = u + hidden @ params["U"]
    logits = u @ params["W"] + params["b"][:, None, :]
    exp = np.exp(logits - logits.max(axis=2, keepdims=True))
    p = exp / exp.sum(axis=2, keepdims=True)
    cells, rows = np.arange(len(x))[:, None], np.arange(x.shape[1])[None, :]
    loss = -(weight * np.log(np.clip(p[cells, rows, y], 1e-15, 1))).sum(axis=1)
    delta = p.copy()
    delta[cells, rows, y] -= 1
    delta *= weight[:, :, None]
    gradients = {"W": u.transpose(0, 2, 1) @ delta, "b": delta.sum(axis=1)}
    du = delta @ params["W"].transpose(0, 2, 1)
    if gate is not None:
        dg = du * x * gate * (1 - gate)
        dg *= np.abs(x * params["a"][:, None, :] + params["g"][:, None, :]) < 40
        gradients.update(a=(dg * x).sum(axis=1), g=dg.sum(axis=1))
    if hidden is not None:
        gradients.update(U=hidden.transpose(0, 2, 1) @ du,
            V=x.transpose(0, 2, 1) @ ((du @ params["U"].transpose(0, 2, 1)) * (1-hidden**2)))
    for name, value in params.items():
        if name not in ("b", "g"):
            loss += .5 * l2 * np.square(value).sum(axis=tuple(range(1, value.ndim)))
            gradients[name] += l2 * value
    return loss, gradients


class MicrobatchCellTrainer:
    def __init__(self, heads, cell_ids, task_ids, bank, *, microbatch=32, generation=1,
                 max_parameters=100000, max_tensor_bytes=128 * 1024**2):
        heads, self.cell_ids, self.task_ids = tuple(heads), tuple(cell_ids), tuple(task_ids)
        if (type(bank) is not FrozenTrainingBank or not 1 <= len(heads) <= 4096
                or len(heads) != len(self.cell_ids) or len(heads) != len(self.task_ids)
                or len(set(self.cell_ids)) != len(heads)
                or any(type(v) is not str or not 1 <= len(v) <= 256 for v in self.cell_ids)
                or any(t not in bank.task_ids for t in self.task_ids)
                or type(microbatch) is not int or not 1 <= microbatch <= 64
                or type(generation) is not int or generation < 1
                or type(max_parameters) is not int or not 1 <= max_parameters <= 1000000
                or type(max_tensor_bytes) is not int or not 4096 <= max_tensor_bytes <= 512 * 1024**2):
            raise ValueError("bounded compatible private Cell pool required")
        first = heads[0]
        if any(type(h) is not NumpyCellHead for h in heads):
            raise ValueError("native NumPy private heads required")
        self.width, self.classes, self.mode, self.rank = first.width, first.classes, first.mode, first.rank
        shapes = {k: v.shape for k, v in first.params.items()}
        expected = {"W": (self.width, self.classes), "b": (self.classes,)}
        if self.mode != "linear": expected.update(a=(self.width,), g=(self.width,))
        if self.mode == "residual": expected.update(V=(self.width, self.rank), U=(self.rank, self.width))
        if shapes != expected:
            raise ValueError("private tensor schema differs from the native head")
        for head in heads:
            if ((head.width, head.classes, head.mode, head.rank) != (self.width, self.classes, self.mode, self.rank)
                    or head.feature_identity != bank.feature_identity or head.parameter_count > max_parameters
                    or {k: v.shape for k, v in head.params.items()} != shapes
                    or any(v.dtype != np.float64 or not np.isfinite(v).all() or np.max(np.abs(v)) > 1e6
                           for v in head.params.values())):
                raise ValueError("stale identity, incompatible parameters or private parameter cap")
        if self.width != bank._raw.shape[1]:
            raise ValueError("feature bank and private Head widths differ")
        self.bank, self.microbatch, self.generation = bank, microbatch, generation
        self.feature_identity, self.max_parameters = bank.feature_identity, max_parameters
        self.rows = bank._indices.shape[1]
        self.parameter_count = first.parameter_count
        parameter_bytes = len(heads) * first.tensor_bytes
        active = min(len(heads), microbatch)
        self.workspace_bound = active * 8 * (32*self.rows*self.width + 16*self.rows*self.classes
            + 8*self.rows*self.rank + 20*self.parameter_count + 128)
        self.tensor_bound = (3*parameter_bytes + bank.tensor_bytes + len(heads)*(self.rows*16 + self.classes*8 + 24)
                             + self.workspace_bound)
        if self.tensor_bound > max_tensor_bytes:
            raise ValueError("private state and microbatch workspace exceed tensor memory bound")
        self.max_tensor_bytes = max_tensor_bytes
        self._params = {k: np.stack([h.params[k] for h in heads]) for k in first.params}
        self._m, self._v = ({k: np.zeros_like(v) for k, v in self._params.items()} for _ in range(2))
        self.initial_digests = tuple(h.digest() for h in heads)
        self.optimizer_steps, self.report, self.trajectory, self._started = 0, None, {}, False

    def state_digest(self, index):
        result = hashlib.sha256(canonical([self.width, self.classes, self.mode, self.rank]))
        for name, array in sorted(self._params.items()):
            value = array[index]
            result.update(canonical([name, list(value.shape), value.dtype.str]))
            result.update(value.tobytes())
        return result.hexdigest()

    def parameters(self):
        if self._started and self.report is None:
            raise ValueError("failed or incomplete private training state cannot be published")
        return {name: frozen(value) for name, value in self._params.items()}

    def train(self, labels, *, feature_identity, generation, steps=20, learning_rate=.02,
              l2=.001, trace_steps=()):
        identity(feature_identity)
        if (feature_identity != self.feature_identity or type(generation) is not int
                or generation != self.generation):
            raise ValueError("stale feature identity or generation before private update")
        if (self._started or type(steps) is not int or not 1 <= steps <= 100
                or type(learning_rate) not in (int, float) or not 0 < learning_rate <= 1
                or type(l2) not in (int, float) or not 0 <= l2 <= 1
                or tuple(sorted(set(trace_steps))) != tuple(trace_steps)
                or any(type(s) is not int or not 1 <= s <= steps for s in trace_steps)):
            raise ValueError("one bounded private Adam run per published input snapshot required")
        y = np.asarray(labels)
        if (y.shape != (len(self.cell_ids), self.rows) or y.dtype.kind not in "iu"
                or np.any(y < 0) or np.any(y >= self.classes)
                or any(len(np.unique(row)) != self.classes for row in y)):
            raise ValueError("each private Cell needs its own valid labels with every class")
        y = frozen(y.astype(np.int64))
        trace_bytes = len(trace_steps) * sum(p.nbytes for p in self._params.values())
        if self.tensor_bound + 2*trace_bytes > self.max_tensor_bytes:
            raise ValueError("requested private trajectory exceeds tensor memory bound")
        # A partial failed attempt is terminal; its moments cannot restart at t=1.
        self._started = True
        began, cpu = time.perf_counter_ns(), time.process_time_ns()
        counts = np.stack([np.bincount(row, minlength=self.classes) for row in y])
        weights = 1 / np.take_along_axis(counts, y, axis=1)
        weights /= weights.sum(axis=1, keepdims=True)
        trace = {s: {k: np.empty_like(v) for k, v in self._params.items()} for s in trace_steps}
        initial, final = np.empty(len(y)), np.empty(len(y))
        maximum_norm = np.zeros(len(y))
        for begin in range(0, len(y), self.microbatch):
            end = min(begin + self.microbatch, len(y))
            task_indices = [self.bank.task_ids.index(t) for t in self.task_ids[begin:end]]
            x = self.bank._normalized[self.bank._indices[task_indices]]
            x.flags.writeable = False
            params = {k: v[begin:end] for k, v in self._params.items()}
            for step in range(1, steps + 1):
                loss, gradient = loss_gradients(params, x, y[begin:end], weights[begin:end], self.mode, l2)
                if step == 1: initial[begin:end] = loss
                norm = np.sqrt(sum(np.square(g).sum(axis=tuple(range(1, g.ndim))) for g in gradient.values()))
                if not np.isfinite(loss).all() or not np.isfinite(norm).all():
                    raise ValueError("nonfinite private loss or gradient")
                maximum_norm[begin:end] = np.maximum(maximum_norm[begin:end], norm)
                clip = np.minimum(1, 5 / np.maximum(norm, 1e-12))
                for name, value in params.items():
                    g = gradient[name] * clip.reshape((-1,) + (1,) * (value.ndim - 1))
                    m, v = self._m[name][begin:end], self._v[name][begin:end]
                    m[:] = .9*m + .1*g
                    v[:] = .999*v + .001*g*g
                    value -= learning_rate * (m/(1-.9**step)) / (np.sqrt(v/(1-.999**step)) + 1e-8)
                    if step in trace: trace[step][name][begin:end] = value
            final[begin:end], _ = loss_gradients(params, x, y[begin:end], weights[begin:end], self.mode, l2)
        if not np.isfinite(final).all() or any(not np.isfinite(v).all() for v in self._params.values()):
            raise ValueError("private optimizer produced nonfinite state")
        self.optimizer_steps = steps
        self.trajectory = {s: {k: frozen(v) for k, v in state.items()} for s, state in trace.items()}
        self.report = {"schema": "hepta.microbatch-private-adam.v1", "mode": self.mode,
            "cells": len(y), "declared_tasks": len(set(self.task_ids)), "microbatch": self.microbatch,
            "optimizer_steps_per_cell": steps, "private_optimizer_updates": len(y)*steps,
            "example_updates": len(y)*self.rows*steps, "initial_loss": initial.tolist(), "final_loss": final.tolist(),
            "maximum_unclipped_gradient_norm": maximum_norm.tolist(), "learning_rate": learning_rate, "l2": l2,
            "wall_ns": time.perf_counter_ns()-began, "cpu_ns": time.process_time_ns()-cpu,
            "parameter_bytes": sum(p.nbytes for p in self._params.values()),
            "optimizer_state_bytes": sum(p.nbytes for p in (*self._m.values(), *self._v.values())),
            "cached_feature_tensor_bytes": self.bank.tensor_bytes, "transient_tensor_upper_bound_bytes": self.workspace_bound,
            "total_tensor_upper_bound_bytes": self.tensor_bound + 2*trace_bytes, "trace_tensor_bytes": trace_bytes,
            "memory_bound_scope": "conservative NumPy tensor bound; caller heads, Python objects, allocator and BLAS buffers excluded",
            "initial_parameter_digests": self.initial_digests,
            "trained_parameter_digests": [self.state_digest(i) for i in range(len(y))],
            "feature_identity": self.feature_identity, "generation": self.generation,
            "encoder_forwards": 0, "encoder_updates": 0, "heldout_or_calibration_labels_used": False,
            "authority": "DENY_ALL", "quality_qualified": False}
        return dict(self.report)
