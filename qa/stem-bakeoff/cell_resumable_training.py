"""Explicit Adam step boundaries over frozen inputs; no serving publication.

The frozen trainer remains unchanged. This owner reuses its allocation checks
and loss function, preserving microbatch-major order and every Adam equation.
Only a fully completed optimizer step can become a resumable checkpoint.
"""

import hashlib
import json
from pathlib import Path
import threading
import time

import numpy as np

from cell_learning_models import canonical
from cell_microbatch_training import (FrozenTrainingBank, MicrobatchCellTrainer,
                                     frozen, identity, loss_gradients)


CODE_FILES = ("cell_resumable_training.py", "cell_microbatch_training.py",
              "cell_learning_models.py", "cell_learning_metrics.py")
EMPTY_TRAJECTORY = hashlib.sha256(b"hepta.resumable-adam-trajectory.v1").hexdigest()


def serialized(method):
    def call(owner, *args, **kwargs):
        with owner._lock:
            return method(owner, *args, **kwargs)
    return call


def array_sha(array):
    value = np.ascontiguousarray(array)
    result = hashlib.sha256(canonical([list(value.shape), value.dtype.str]))
    result.update(memoryview(value).cast("B"))
    return result.hexdigest()


def source_pins():
    return {name: hashlib.sha256(Path(__file__).with_name(name).read_bytes()).hexdigest()
            for name in CODE_FILES}


class ResumableMicrobatchAdam:
    """Own parameters, moments, a deterministic cursor and immutable input IDs."""

    def __init__(self, heads, cell_ids, task_ids, bank, labels, *, source_record_digests,
                 steps=20, learning_rate=.02, l2=.001, microbatch=8, generation=1,
                 max_parameters=100000, max_tensor_bytes=512*1024**2):
        heads = tuple(heads)
        sources = tuple(source_record_digests)
        if (not 1 <= len(heads) <= 1024 or type(bank) is not FrozenTrainingBank
                or len(sources) != len(bank.source_ids)
                or type(steps) is not int or not 1 <= steps <= 100
                or type(learning_rate) not in (int, float) or not 0 < learning_rate <= 1
                or type(l2) not in (int, float) or not 0 <= l2 <= 1):
            raise ValueError("bounded immutable Adam run required")
        for value in sources:
            identity(value)
        self._core = MicrobatchCellTrainer(heads, cell_ids, task_ids, bank,
            microbatch=microbatch, generation=generation, max_parameters=max_parameters,
            max_tensor_bytes=max_tensor_bytes)
        core = self._core
        y = np.asarray(labels)
        if (y.shape != (len(heads), core.rows) or y.dtype.kind not in "iu"
                or np.any(y < 0) or np.any(y >= core.classes)
                or any(len(np.unique(row)) != core.classes for row in y)
                or core.tensor_bound+len(heads)*8 > max_tensor_bytes):
            raise ValueError("valid class-complete labels and bounded step state required")
        self._labels = frozen(y.astype(np.int64))
        counts = np.stack([np.bincount(row, minlength=core.classes) for row in self._labels])
        weight = 1 / np.take_along_axis(counts, self._labels, axis=1)
        self._weights = frozen(weight / weight.sum(axis=1, keepdims=True))
        inputs = {"role": "train", "feature_identity": bank.feature_identity,
            "generation": generation, "bank_tasks": list(bank.task_ids),
            "source_ids": list(bank.source_ids), "source_record_digests": list(sources),
            "cell_ids": list(core.cell_ids), "cell_tasks": list(core.task_ids),
            "arrays": {name: {"shape": list(value.shape), "sha256": array_sha(value)} for name, value in
                {"raw": bank._raw, "normalized": bank._normalized, "indices": bank._indices,
                 "labels": self._labels}.items()}}
        plan = {"schema": "hepta.resumable-microbatch-adam-plan.v1", "inputs": inputs,
            "input_sha256": hashlib.sha256(canonical(inputs)).hexdigest(),
            "model": {"width": core.width, "classes": core.classes, "mode": core.mode,
                "rank": core.rank, "initial_parameter_digests": list(core.initial_digests)},
            "optimizer": {"name": "adam", "steps": steps, "learning_rate": learning_rate,
                "l2": l2, "beta1": .9, "beta2": .999, "epsilon": 1e-8,
                "clip_norm": 5, "class_weights": "inverse_training_frequency",
                "normalization": "l2_times_sqrt_width"},
            "order": {"schedule": "microbatch_major_then_step", "microbatch": microbatch,
                "rows": "complete_bound_bank_indices_each_step", "sampling": "none", "rng_state": None},
            "limits": {"max_parameters": max_parameters, "max_tensor_bytes": max_tensor_bytes},
            "implementation": {"source_sha256": source_pins(), "numpy_version": np.__version__}}
        self._plan_bytes = canonical(plan)
        self.plan_sha256 = hashlib.sha256(self._plan_bytes).hexdigest()
        self._cursor, self._trajectory, self._failed = 0, EMPTY_TRAJECTORY, False
        self._initial, self._final, self._maximum_norm = (np.zeros(len(heads)) for _ in range(3))
        self._lock = threading.RLock()

    @property
    def plan(self):
        return json.loads(self._plan_bytes)

    @property
    def input_sha256(self):
        return self.plan["input_sha256"]

    @property
    def total_block_steps(self):
        return ((len(self._core.cell_ids)+self._core.microbatch-1)//self._core.microbatch
                * self.plan["optimizer"]["steps"])

    def step_counts(self):
        target = self.plan["optimizer"]["steps"]
        groups = np.arange(len(self._core.cell_ids)) // self._core.microbatch
        return np.clip(self._cursor-groups*target, 0, target).astype(np.int64)

    def _check(self, expected_plan_sha256):
        if (self._failed or identity(expected_plan_sha256) != self.plan_sha256
                or hashlib.sha256(self._plan_bytes).hexdigest() != self.plan_sha256
                or self.plan["implementation"] != {"source_sha256": source_pins(), "numpy_version": np.__version__}):
            raise ValueError("failed, stale or changed optimizer owner")

    @serialized
    def advance(self, block_steps=None, *, expected_plan_sha256):
        """Advance complete private microbatch updates; never reset Adam time."""
        self._check(expected_plan_sha256)
        left = self.total_block_steps-self._cursor
        amount = left if block_steps is None else block_steps
        if type(amount) is not int or not 0 <= amount <= left:
            raise ValueError("advance exceeds the frozen total step plan")
        before = int(self.step_counts().sum())
        began, cpu = time.perf_counter_ns(), time.process_time_ns()
        core, config = self._core, self.plan["optimizer"]
        try:
            for _ in range(amount):
                group, at = divmod(self._cursor, config["steps"])
                begin, step = group*core.microbatch, at+1
                end = min(begin+core.microbatch, len(core.cell_ids))
                indices = [core.bank.task_ids.index(t) for t in core.task_ids[begin:end]]
                x = core.bank._normalized[core.bank._indices[indices]]
                x.flags.writeable = False
                params = {k: v[begin:end] for k, v in core._params.items()}
                loss, gradient = loss_gradients(params, x, self._labels[begin:end],
                    self._weights[begin:end], core.mode, config["l2"])
                norm = np.sqrt(sum(np.square(g).sum(axis=tuple(range(1, g.ndim))) for g in gradient.values()))
                if not np.isfinite(loss).all() or not np.isfinite(norm).all():
                    raise ValueError("nonfinite optimizer loss or gradient")
                if step == 1:
                    self._initial[begin:end] = loss
                self._maximum_norm[begin:end] = np.maximum(self._maximum_norm[begin:end], norm)
                clip = np.minimum(1, 5/np.maximum(norm, 1e-12))
                for name, value in params.items():
                    g = gradient[name]*clip.reshape((-1,)+(1,)*(value.ndim-1))
                    m, v = core._m[name][begin:end], core._v[name][begin:end]
                    m[:] = .9*m+.1*g
                    v[:] = .999*v+.001*g*g
                    value -= config["learning_rate"]*(m/(1-.9**step))/(np.sqrt(v/(1-.999**step))+1e-8)
                if any(not np.isfinite(v).all() for v in (*params.values(),
                        *(v[begin:end] for v in core._m.values()), *(v[begin:end] for v in core._v.values()))):
                    raise ValueError("nonfinite completed optimizer step")
                event = {"begin": begin, "end": end, "step": step, "loss_before": loss.tolist(),
                    "state_sha256": {prefix+name: array_sha(value[begin:end])
                        for prefix, state in (("p_", core._params), ("m_", core._m), ("v_", core._v))
                        for name, value in state.items()}}
                if step == config["steps"]:
                    self._final[begin:end], _ = loss_gradients(params, x, self._labels[begin:end],
                        self._weights[begin:end], core.mode, config["l2"])
                    if not np.isfinite(self._final[begin:end]).all():
                        raise ValueError("nonfinite final loss")
                    event["final_loss"] = self._final[begin:end].tolist()
                self._trajectory = hashlib.sha256(bytes.fromhex(self._trajectory)+canonical(event)).hexdigest()
                self._cursor += 1
        except BaseException:
            self._failed = True
            raise
        return {"block_updates": amount, "private_optimizer_updates": int(self.step_counts().sum())-before,
            "wall_ns": time.perf_counter_ns()-began, "cpu_ns": time.process_time_ns()-cpu,
            "cursor": self._cursor, "trajectory_sha256": self._trajectory}

    @serialized
    def snapshot(self):
        """Copy resumable state at a completed step boundary, never a predictor."""
        self._check(self.plan_sha256)
        core = self._core
        snapshot_bytes = 3*sum(v.nbytes for v in core._params.values())+len(core.cell_ids)*32
        if core.tensor_bound+len(core.cell_ids)*8+snapshot_bytes > core.max_tensor_bytes:
            raise ValueError("checkpoint copy exceeds the admitted tensor reservation")
        arrays = {prefix+name: frozen(value)
            for prefix, state in (("p_", core._params), ("m_", core._m), ("v_", core._v))
            for name, value in state.items()}
        arrays.update(raw=core.bank._raw, normalized=core.bank._normalized, indices=core.bank._indices,
            labels=self._labels, steps=frozen(self.step_counts()), initial_loss=frozen(self._initial),
            final_loss=frozen(self._final), maximum_norm=frozen(self._maximum_norm))
        return {"plan": self.plan, "plan_sha256": self.plan_sha256, "cursor": self._cursor,
                "trajectory_sha256": self._trajectory}, arrays

    @serialized
    def progress(self):
        counts = self.step_counts()
        target = self.plan["optimizer"]["steps"]
        return {"cursor": self._cursor, "total_block_steps": self.total_block_steps,
            "complete": self._cursor == self.total_block_steps, "failed": self._failed,
            "partial_failed_step_work_unknown": self._failed, "steps_per_cell": counts.tolist(),
            "private_optimizer_updates": int(counts.sum()),
            "example_updates": int(counts.sum())*self._core.rows,
            "initial_loss": [float(v) if s else None for v, s in zip(self._initial, counts, strict=True)],
            "final_loss": [float(v) if s == target else None for v, s in zip(self._final, counts, strict=True)],
            "maximum_unclipped_gradient_norm": self._maximum_norm.tolist(),
            "trajectory_sha256": self._trajectory, "authority": "DENY_ALL", "quality_qualified": False,
            "calibration": None, "calibration_status": "unavailable_for_training_state",
            "encoder_updates": 0, "encoder_forwards": 0, "heldout_or_calibration_labels_used": False}
