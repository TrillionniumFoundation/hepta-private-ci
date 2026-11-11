"""Preregistered synthetic regression data; no Hepta runtime authority."""

from dataclasses import asdict, dataclass
import hashlib
import json

import numpy as np


ARMS = (
    "frozen_incumbent", "continued_parent", "expanded_monolith",
    "fixed_experts", "random_grouping", "demand_specialization",
)
SCENARIOS = ("helpful_specialization", "redundant_specialization")
SOURCE_FILES = (
    "study_data.py", "study_model.py", "study_cost.py",
    "study_evidence.py", "study_gate.py", "run_study.py",
)


def canonical_bytes(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def digest(value):
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


@dataclass(frozen=True)
class Policy:
    persistent_window_mse: float = 0.1
    negative_transfer_mse_increase: float = 0.01
    minimum_mse_gain: float = 0.0005
    maximum_old_task_mse_increase: float = 0.01
    maximum_float_ops_ratio_to_continued: float = 3.0
    maximum_parameter_bytes: int = 4096


@dataclass(frozen=True)
class Plan:
    seeds: tuple = (7, 17, 29, 43, 71)
    scenarios: tuple = SCENARIOS
    arms: tuple = ARMS
    dimensions: int = 4
    pretrain_per_task: int = 256
    train_per_task: int = 128
    validation_per_task: int = 64
    test_per_task: int = 96
    monitoring_windows: int = 3
    monitor_per_task_per_window: int = 32
    training_steps: int = 128
    learning_rate: float = 0.1
    ridge: float = 0.0001
    noise_std: float = 0.05
    policy: Policy = Policy()

    def validate(self):
        if self.arms != ARMS or self.scenarios != SCENARIOS:
            raise ValueError("all preregistered arms and scenarios are required")
        if (not self.seeds or len(set(self.seeds)) != len(self.seeds)
                or any(not isinstance(s, int) or isinstance(s, bool) or s < 0 for s in self.seeds)):
            raise ValueError("seeds must be nonempty, unique nonnegative integers")
        if self.dimensions != 4 or self.monitoring_windows < 3:
            raise ValueError("the reference requires four inputs and three demand windows")
        for count in (self.pretrain_per_task, self.train_per_task, self.validation_per_task,
                      self.test_per_task, self.monitor_per_task_per_window, self.training_steps):
            if not isinstance(count, int) or count < 2:
                raise ValueError("sample and training counts must be positive integers")
        if (not all(np.isfinite(v) for v in (self.learning_rate, self.ridge, self.noise_std))
                or not 0 < self.learning_rate <= 0.1 or self.ridge < 0 or self.noise_std <= 0):
            raise ValueError("invalid optimizer or noise policy")
        if any(not np.isfinite(value) or value < 0 for value in asdict(self.policy).values()):
            raise ValueError("invalid acceptance policy")
        if any(value <= 0 for value in (self.policy.minimum_mse_gain,
                                       self.policy.maximum_float_ops_ratio_to_continued,
                                       self.policy.maximum_parameter_bytes)):
            raise ValueError("strict positive gain and resource budgets are required")


@dataclass(frozen=True)
class Batch:
    split: str
    ids: tuple
    x: np.ndarray
    y: np.ndarray
    task: np.ndarray
    window: np.ndarray

    def __post_init__(self):
        n = len(self.ids)
        if (self.x.shape != (n, 4) or any(a.shape != (n,) for a in (self.y, self.task, self.window))
                or len(set(self.ids)) != n or not n):
            raise ValueError("invalid sample shapes or request identities")
        if not all(np.isfinite(a).all() for a in (self.x, self.y, self.task, self.window)):
            raise ValueError("nonfinite source data")
        if not np.isin(self.task, (0, 1)).all():
            raise ValueError("unknown task partition")
        for array in (self.x, self.y, self.task, self.window):
            array.setflags(write=False)

    def manifest(self):
        h = hashlib.sha256(canonical_bytes({"split": self.split, "ids": self.ids}))
        for array in (self.x, self.y, self.task, self.window):
            h.update(array.dtype.str.encode())
            h.update(array.tobytes())
        return {
            "digest": h.hexdigest(), "requests": len(self.ids), "ids": list(self.ids),
            "windows": self.window.tolist(),
            "target_digest": digest([[i, int(t), float(y)] for i, t, y in
                                     zip(self.ids, self.task, self.y, strict=True)]),
            "data_bytes": sum(a.nbytes for a in (self.x, self.y, self.task, self.window)),
        }


def make_data(plan, seed, scenario):
    if scenario not in SCENARIOS:
        raise ValueError("unknown scenario")
    sizes = {
        "pretrain": plan.pretrain_per_task, "train": plan.train_per_task,
        "monitor": plan.monitoring_windows * plan.monitor_per_task_per_window,
        "validation": plan.validation_per_task, "test": plan.test_per_task,
    }
    old = np.array([1.4, -0.8, 0.4, 0.6], dtype=np.float64)
    new = np.array([-1.4, 0.8, 0.4, -0.6], dtype=np.float64)
    batches = {}
    for split_number, (split, size) in enumerate(sizes.items()):
        xs, ys, tasks, windows, ids = [], [], [], [], []
        for task in (0,) if split == "pretrain" else (0, 1):
            # Paired scenarios reuse inputs/noise; independent streams separate splits/tasks.
            rng = np.random.default_rng(np.random.SeedSequence([seed, split_number, task]))
            x = rng.normal(size=(size, plan.dimensions)).astype(np.float64)
            weights = new if task == 1 and scenario == SCENARIOS[0] else old
            y = x @ weights + 0.1 + rng.normal(scale=plan.noise_std, size=size)
            xs.append(x)
            ys.append(y)
            tasks.extend([task] * size)
            windows.extend([j // plan.monitor_per_task_per_window if split == "monitor" else 0
                            for j in range(size)])
            ids.extend(f"{scenario}/{seed}/{split}/{task}/{j}" for j in range(size))
        batches[split] = Batch(split, tuple(ids), np.vstack(xs), np.concatenate(ys),
                               np.array(tasks, dtype=np.int64), np.array(windows, dtype=np.int64))
    validate_isolation(batches)
    return batches


def validate_isolation(batches):
    seen_ids, seen_rows = set(), set()
    for split, batch in batches.items():
        if batch.split != split:
            raise ValueError("split label does not match the frozen data partition")
        if seen_ids.intersection(batch.ids):
            raise ValueError("request identity leaked across splits")
        rows = set()
        for x, y, task in zip(batch.x, batch.y, batch.task, strict=True):
            # Fresh IDs do not turn copied training samples into held-out samples.
            rows.add(hashlib.sha256(x.tobytes() + np.float64(y).tobytes()
                                   + np.int64(task).tobytes()).digest())
        if seen_rows.intersection(rows):
            raise ValueError("sample contents leaked across splits")
        seen_ids.update(batch.ids)
        seen_rows.update(rows)


@dataclass(frozen=True)
class FrozenRun:
    plan_json: bytes
    source_digest: str
    manifest_json: bytes
    commitment: str

    @classmethod
    def freeze(cls, plan, batches, source_digest):
        plan.validate()
        validate_isolation(batches)
        plan_json = canonical_bytes(asdict(plan))
        manifest_json = canonical_bytes({s: b.manifest() for s, b in batches.items()})
        commitment = digest({"plan": json.loads(plan_json), "source": source_digest,
                             "data": json.loads(manifest_json)})
        return cls(plan_json, source_digest, manifest_json, commitment)

    def authorize_training(self, batch):
        if batch.split not in ("pretrain", "train"):
            raise ValueError("held-out data is not a training input")
        manifest = json.loads(self.manifest_json)
        if batch.manifest() != manifest[batch.split]:
            raise ValueError("training data differs from its preregistered bytes")

    def verify(self, plan):
        if canonical_bytes(asdict(plan)) != self.plan_json:
            raise ValueError("policy or training plan changed after preregistration")
        if self.commitment != digest({"plan": json.loads(self.plan_json), "source": self.source_digest,
                                      "data": json.loads(self.manifest_json)}):
            raise ValueError("invalid preregistration commitment")
