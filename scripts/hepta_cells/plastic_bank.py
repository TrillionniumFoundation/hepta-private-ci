"""Research-only shared-plastic controls built from the existing LocalHead.

Each task updates one canonical shared first factor or its own private factor.
Candidate production never grants Population or daemon adoption authority.
"""

import copy
import hashlib
import io
import json
import os
from pathlib import Path
import re
import time
import zipfile

import numpy as np

from .semantic import LocalHead, LocalObjective, _digest


ARMS = ("shared_plastic", "frozen_backbone", "independent", "frozen")


class PlasticBank:
    """Task-specific readouts with explicit canonical parameter ownership."""

    def __init__(self, arm, width, rank, task_ids, seed=0):
        if arm not in ARMS or any(type(v) is not int or v < 1 for v in (width, rank)):
            raise ValueError("known arm and positive dimensions required")
        if width > 1024 or rank > 128 or not 1 <= len(task_ids) <= 32:
            raise ValueError("small-study resource bound exceeded")
        if type(seed) is not int or not 0 <= seed < 2**64:
            raise ValueError("unsigned integer seed required")
        if len(set(task_ids)) != len(task_ids) or any(
            not isinstance(t, str) or not 1 <= len(t) <= 128 for t in task_ids
        ):
            raise ValueError("distinct bounded task IDs required")
        self.config = dict(
            arm=arm, width=width, rank=rank, task_ids=list(task_ids), seed=seed
        )
        rng = np.random.default_rng(seed)
        first = rng.normal(0, 1 / np.sqrt(width), (width, rank))
        copies = len(task_ids) if arm == "independent" else 1
        self.first = np.repeat(first[None], copies, axis=0)
        self.second = np.zeros((len(task_ids), rank, 1))
        self.bias = np.zeros((len(task_ids), 1))
        self.steps = np.zeros(len(task_ids), dtype=np.int64)
        self.objective = LocalObjective("mse", 1, "retained-observed-task-success")

    def _index(self, task_id):
        if task_id not in self.config["task_ids"]:
            raise ValueError("unknown route; no implicit task inference")
        return self.config["task_ids"].index(task_id)

    def head(self, task_id):
        task = self._index(task_id)
        owner = task if self.config["arm"] == "independent" else 0
        return LocalHead(self.first[owner], self.bias[task], self.second[task])

    @property
    def digest(self):
        return _digest(
            "hepta.plastic-bank.v1",
            json.dumps(self.config, sort_keys=True),
            *(a.tobytes() for a in (self.first, self.second, self.bias, self.steps)),
        )

    def resources(self):
        arrays = (self.first, self.second, self.bias)
        count = sum(a.size for a in arrays)
        plastic = 0 if self.config["arm"] == "frozen" else count
        if self.config["arm"] == "frozen_backbone":
            plastic -= self.first.size
        return dict(
            total_parameters=count,
            plastic_parameters=plastic,
            parameter_bytes=sum(a.nbytes for a in arrays),
            optimizer_bytes=self.steps.nbytes,
            energy_joules=None,
            peak_resident_bytes=None,
        )

    def propose(self, task_id, features, targets, *, updates=1, learning_rate=0.03):
        """Fit an isolated SGD candidate and retain failed-attempt costs."""
        wall, cpu = time.perf_counter_ns(), time.process_time_ns()
        receipt = dict(
            status="started",
            parent=self.digest,
            task_id=task_id,
            completed_updates=0,
            attempted_updates=0,
            parameter_scalar_updates=0,
            forward_mac=0,
            gradient_mac=0,
            losses=[],
            arithmetic_scope=(
                "attempted dense linear MAC including recomputed xW; "
                "excludes bias, copying, hash, IO and allocation"
            ),
        )
        try:
            task = self._index(task_id)
            if self.config["arm"] == "frozen":
                raise ValueError("frozen arm cannot train")
            if type(updates) is not int or not 1 <= updates <= 1024:
                raise ValueError("updates must be bounded")
            if (
                isinstance(learning_rate, bool)
                or not np.isfinite(learning_rate)
                or learning_rate <= 0
            ):
                raise ValueError("positive finite learning rate required")
            x = np.asarray(features, dtype=np.float64)
            if (
                x.ndim != 2
                or x.shape[1] != self.config["width"]
                or not 1 <= len(x) <= 4096
                or not np.isfinite(x).all()
            ):
                raise ValueError("finite bounded feature batch required")
            y = self.objective.targets(targets, len(x))
            candidate = copy.deepcopy(self)
            owner = task if self.config["arm"] == "independent" else 0
            receipt.update(
                dataset_sha256=_digest(x.tobytes(), y.tobytes()),
                items=len(x),
                learning_rate=learning_rate,
            )
            for _ in range(updates):
                if candidate.steps[task] == np.iinfo(np.int64).max:
                    raise ValueError("training step limit reached")
                head = candidate.head(task_id)
                receipt["attempted_updates"] += 1
                receipt["forward_mac"] += len(x) * (head.first.size + head.second.size)
                loss, gradient = self.objective.loss_and_gradient(head.predict(x), y)
                if not np.isfinite(loss) or not np.isfinite(gradient).all():
                    raise FloatingPointError("nonfinite loss or gradient")
                receipt["forward_mac"] += len(x) * head.first.size
                if self.config["arm"] == "frozen_backbone":
                    receipt["gradient_mac"] += len(x) * head.second.size
                    candidate.second[task] -= (
                        learning_rate * (x @ head.first).T @ gradient
                    )
                    candidate.bias[task] -= learning_rate * gradient.sum(axis=0)
                    touched = head.second.size + head.bias.size
                else:
                    receipt["gradient_mac"] += len(x) * (
                        head.first.size + 2 * head.second.size
                    )
                    new = head.gradient_step(x, gradient, learning_rate)
                    candidate.first[owner] = new.first
                    candidate.second[task] = new.second
                    candidate.bias[task] = new.bias
                    touched = sum(a.size for a in head.arrays)
                if not all(
                    np.isfinite(a).all()
                    for a in (candidate.first, candidate.second, candidate.bias)
                ):
                    raise FloatingPointError("nonfinite candidate")
                candidate.steps[task] += 1
                receipt["completed_updates"] += 1
                receipt["parameter_scalar_updates"] += touched
                receipt["losses"].append(loss)
            receipt.update(
                status="completed_candidate_only",
                candidate=candidate.digest,
                resources=candidate.resources(),
            )
            return candidate, receipt
        except Exception as error:
            receipt.update(status="failed", error=f"{type(error).__name__}: {error}")
            error.receipt = receipt
            raise
        finally:
            receipt.update(
                wall_ns=time.perf_counter_ns() - wall,
                process_cpu_ns=time.process_time_ns() - cpu,
            )

    def checkpoint(self, path, *, cursor, plan_sha256):
        """Save full plain-SGD state and a frozen curriculum cursor."""
        if (
            type(cursor) is not int
            or not 0 <= cursor < 2**63
            or not isinstance(plan_sha256, str)
            or not re.fullmatch(r"[0-9a-f]{64}", plan_sha256)
        ):
            raise ValueError("explicit plan identity and valid cursor required")
        buffer = io.BytesIO()
        np.savez_compressed(
            buffer,
            config=np.asarray(json.dumps(self.config, sort_keys=True)),
            first=self.first,
            second=self.second,
            bias=self.bias,
            steps=self.steps,
            cursor=np.asarray(cursor),
            plan_sha256=np.asarray(plan_sha256),
        )
        raw = buffer.getvalue()
        with Path(path).open("xb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        return hashlib.sha256(raw).hexdigest()

    @classmethod
    def restore(cls, path, *, expected_sha256, plan_sha256):
        with Path(path).open("rb") as stream:
            raw = stream.read(32 * 1024 * 1024 + 1)
        if (
            len(raw) > 32 * 1024 * 1024
            or hashlib.sha256(raw).hexdigest() != expected_sha256
        ):
            raise ValueError("checkpoint identity or size differs")
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            if sum(x.file_size for x in archive.infolist()) > 32 * 1024 * 1024:
                raise ValueError("expanded checkpoint exceeds bound")
        with np.load(io.BytesIO(raw), allow_pickle=False) as data:
            keys = {
                "config",
                "first",
                "second",
                "bias",
                "steps",
                "cursor",
                "plan_sha256",
            }
            if (
                set(data.files) != keys
                or len(data.files) != len(keys)
                or str(data["plan_sha256"]) != plan_sha256
            ):
                raise ValueError("checkpoint schema or plan differs")
            bank = cls(**json.loads(str(data["config"])))
            for name in ("first", "second", "bias", "steps"):
                value, template = data[name], getattr(bank, name)
                if (
                    value.shape != template.shape
                    or value.dtype != template.dtype
                    or not np.isfinite(value).all()
                ):
                    raise ValueError("checkpoint arrays differ")
                if name == "steps" and (value < 0).any():
                    raise ValueError("negative training steps")
                setattr(bank, name, value.copy())
            cursor = data["cursor"]
            if (
                cursor.shape != ()
                or cursor.dtype.kind not in "iu"
                or not 0 <= int(cursor) < 2**63
            ):
                raise ValueError("invalid curriculum cursor")
            return bank, int(cursor)
