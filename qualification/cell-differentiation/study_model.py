"""Actual FP64 learners, request-level observations and instrumented costs."""

from dataclasses import dataclass
import hashlib
import json
import time

import numpy as np

from study_data import canonical_bytes, digest


PHASES = frozenset(("train", "eval", "route", "storage", "migration"))


def charge(ledger, phase, stage, start_ns, *, requests=0, float_ops=0, route_decisions=0,
           parameter_bytes=0, serialized_bytes=0, hash_bytes=0, complete=True, note=""):
    ledger.append({
        "phase": phase, "stage": stage, "requests": int(requests),
        "estimated_float_ops": None if float_ops is None else int(float_ops),
        "route_decisions": None if route_decisions is None else int(route_decisions),
        "parameter_bytes": None if parameter_bytes is None else int(parameter_bytes),
        "serialized_bytes": None if serialized_bytes is None else int(serialized_bytes),
        "hash_input_bytes": None if hash_bytes is None else int(hash_bytes),
        "wall_time_ns": time.perf_counter_ns() - start_ns,
        "complete": complete, "note": note,
    })


def features(batch, mode, rows=None):
    x = batch.x if rows is None else batch.x[rows]
    task = batch.task if rows is None else batch.task[rows]
    base = np.column_stack((np.ones(len(x)), x, task))
    if mode == "shared":
        return base
    if mode == "expanded":
        return np.column_stack((base, x * task[:, None]))
    raise ValueError("unknown feature mode")


@dataclass(frozen=True)
class LinearModel:
    mode: str
    weights: np.ndarray

    def __post_init__(self):
        expected = {"shared": 6, "expanded": 10}.get(self.mode)
        if (self.weights.shape != (expected,) or self.weights.dtype != np.dtype(np.float64)
                or not np.isfinite(self.weights).all()):
            raise ValueError("invalid model parameters")
        self.weights.setflags(write=False)


@dataclass(frozen=True)
class Model:
    router: str
    experts: tuple
    salt: str = ""

    def __post_init__(self):
        if self.router not in ("shared", "task", "random"):
            raise ValueError("unknown router")
        if len(self.experts) != (1 if self.router == "shared" else 2):
            raise ValueError("router/expert cardinality mismatch")
        if not all(isinstance(expert, LinearModel) for expert in self.experts):
            raise ValueError("each expert must have validated FP64 parameters")

    def payload(self):
        return {"router": self.router, "salt": self.salt,
                "experts": [{"mode": m.mode, "weights": m.weights.tolist()} for m in self.experts]}

    def identity(self):
        return digest(self.payload())

    def parameter_bytes(self):
        return sum(m.weights.nbytes for m in self.experts)

    @classmethod
    def restore(cls, payload):
        return cls(payload["router"], tuple(LinearModel(m["mode"], np.array(m["weights"], dtype=np.float64))
                                            for m in payload["experts"]), payload["salt"])


def fit(batch, rows, initial, frozen, plan, ledger, stage):
    started = time.perf_counter_ns()
    frozen.verify(plan)
    frozen.authorize_training(batch)
    phi = features(batch, initial.mode, rows)
    y = batch.y[rows]
    if len(y) < 2:
        raise ValueError("too few training requests in the selected partition")
    weights = initial.weights.copy()
    for _ in range(plan.training_steps):
        residual = phi @ weights - y
        gradient = phi.T @ residual / len(y) + plan.ridge * weights
        weights -= plan.learning_rate * gradient
    model = LinearModel(initial.mode, weights)
    n, d = phi.shape
    # Dense multiply-add=2, including residual, ridge and optimizer arithmetic.
    ops = plan.training_steps * (4 * n * d + n + 5 * d)
    if initial.mode == "expanded":
        ops += 4 * n
    charge(ledger, "train", stage, started, requests=n, float_ops=ops,
           parameter_bytes=weights.nbytes, hash_bytes=batch.manifest()["data_bytes"],
           note="FP64 full-batch gradient descent; operation counts are algorithmic estimates")
    return model


def route(batch, model, ledger, stage):
    started = time.perf_counter_ns()
    hash_bytes = 0
    if model.router == "shared":
        assignments = np.zeros(len(batch.ids), dtype=np.int64)
    elif model.router == "task":
        assignments = batch.task
    else:
        encoded = [(model.salt + "/" + i).encode() for i in batch.ids]
        hash_bytes = sum(map(len, encoded))
        assignments = np.array([hashlib.sha256(i).digest()[0] % 2 for i in encoded])
    charge(ledger, "route", stage, started, requests=len(batch.ids),
           route_decisions=len(batch.ids), hash_bytes=hash_bytes,
           note="one dispatch decision per request; SHA-256 bytes are separate from float operations")
    return assignments


def predict_routed(batch, model, assignments):
    predictions = np.empty(len(batch.ids), dtype=np.float64)
    ops = 0
    for index, expert in enumerate(model.experts):
        rows = assignments == index
        phi = features(batch, expert.mode, rows)
        predictions[rows] = phi @ expert.weights
        ops += 2 * phi.shape[0] * phi.shape[1]
        if expert.mode == "expanded":
            ops += 4 * phi.shape[0]
    return predictions, ops


def summarize(records):
    completed = [r for r in records if r["status"] == "completed"]
    losses = [r["squared_error"] for r in completed]
    return {
        "requested": len(records), "completed": len(completed),
        "failed": sum(r["status"] == "failed" for r in records),
        "incomplete": sum(r["status"] == "incomplete" for r in records),
        "mse": float(np.mean(losses)) if len(completed) == len(records) and records else None,
        "completed_only_mse": float(np.mean(losses)) if completed else None,
    }


def evaluate(batch, model, ledger, stage, phase="eval"):
    started = time.perf_counter_ns()
    try:
        assignments = route(batch, model, ledger, stage)
        started = time.perf_counter_ns()
        values, ops = predict_routed(batch, model, assignments)
        if values.shape != batch.y.shape:
            raise ValueError("prediction/request shape mismatch")
        with np.errstate(over="ignore", invalid="ignore"):
            losses = (values - batch.y) ** 2
        records = []
        for request, task, target, prediction, loss in zip(
                batch.ids, batch.task, batch.y, values, losses, strict=True):
            valid = bool(np.isfinite(prediction) and np.isfinite(loss))
            records.append({"id": request, "task": int(task), "target": float(target),
                            "prediction": float(prediction) if np.isfinite(prediction) else None,
                            "squared_error": float(loss) if valid else None,
                            "status": "completed" if valid else "failed",
                            "reason": None if valid else "nonfinite prediction or loss"})
        charge(ledger, phase, stage, started, requests=len(batch.ids), float_ops=ops + 2 * len(batch.ids),
               complete=all(r["status"] == "completed" for r in records))
    except Exception as exc:
        # Preserve the originally requested population after a whole-batch failure.
        records = [{"id": i, "task": int(t), "target": float(y), "prediction": None,
                    "squared_error": None, "status": "incomplete", "reason": str(exc)}
                   for i, t, y in zip(batch.ids, batch.task, batch.y, strict=True)]
        charge(ledger, phase, stage, started, requests=len(batch.ids), complete=False,
               float_ops=None, parameter_bytes=None, hash_bytes=None,
               note="compute before exception is unknown, never treated as zero-cost success")
    return {"split": batch.split, "summary": summarize(records),
            "old_task": summarize([r for r in records if r["task"] == 0]),
            "new_task": summarize([r for r in records if r["task"] == 1]), "records": records}


def snapshot_and_check(model, validation, original_observation, ledger):
    started = time.perf_counter_ns()
    wire = canonical_bytes(model.payload())
    snapshot_digest = hashlib.sha256(wire).hexdigest()
    charge(ledger, "storage", "candidate_snapshot", started, parameter_bytes=model.parameter_bytes(),
           serialized_bytes=len(wire), hash_bytes=len(wire), note="actual parameter and serialized byte sizes")
    started = time.perf_counter_ns()
    restored = Model.restore(json.loads(wire))
    same_digest = restored.identity() == model.identity()
    charge(ledger, "migration", "deserialize_snapshot", started, parameter_bytes=restored.parameter_bytes(),
           serialized_bytes=len(wire), hash_bytes=2 * len(wire))
    after = evaluate(validation, restored, ledger, "migration_validation", phase="migration")
    planned = len(validation.ids)
    complete = all(observation["summary"]["requested"] == planned
                   and observation["summary"]["completed"] == planned
                   for observation in (original_observation, after))
    matches = complete and after["records"] == original_observation["records"] and same_digest
    return {"parameter_digest": snapshot_digest, "roundtrip_digest": restored.identity(),
            "roundtrip_model": restored.payload(), "after": after,
            "exact_validation_behavior": matches, "requests": len(validation.ids),
            "scope": "in-process parameter serialization only; no runtime owner or external effects"}


def diagnose(parent, batches, frozen, plan, ledger):
    before = evaluate(batches["monitor"], Model("shared", (parent,)), ledger, "demand_monitor")
    window_mse = []
    monitor = batches["monitor"]
    for window in range(plan.monitoring_windows):
        losses = [r["squared_error"] for j, r in enumerate(before["records"])
                  if r["task"] == 1 and monitor.window[j] == window and r["status"] == "completed"]
        window_mse.append(float(np.mean(losses)) if len(losses) == plan.monitor_per_task_per_window else None)
    started = time.perf_counter_ns()
    train = batches["train"]
    frozen.verify(plan)
    frozen.authorize_training(train)
    rows = train.task == 1
    phi = features(train, "shared", rows)
    gradient = phi.T @ (phi @ parent.weights - train.y[rows]) / rows.sum()
    probe = LinearModel("shared", parent.weights - plan.learning_rate * gradient)
    n, d = phi.shape
    charge(ledger, "train", "negative_transfer_one_step_probe", started, requests=n,
           float_ops=4 * n * d + n + 3 * d, parameter_bytes=probe.weights.nbytes,
           hash_bytes=train.manifest()["data_bytes"], note="diagnostic only; never changes incumbent")
    after = evaluate(monitor, Model("shared", (probe,)), ledger, "negative_transfer_monitor")
    old_before, old_after = before["old_task"]["mse"], after["old_task"]["mse"]
    regression = None if old_before is None or old_after is None else old_after - old_before
    persistent = all(m is not None and m >= plan.policy.persistent_window_mse for m in window_mse)
    negative_transfer = regression is not None and regression >= plan.policy.negative_transfer_mse_increase
    return {"window_new_task_mse": window_mse, "window_requests": plan.monitor_per_task_per_window,
            "old_task_probe_mse_increase": regression, "persistent_demand": persistent,
            "negative_transfer_observed": negative_transfer, "propose_child": persistent and negative_transfer,
            "training_evidence_splits": ["pretrain", "train", "monitor"],
            "parent_model": Model("shared", (parent,)).payload(),
            "probe_model": Model("shared", (probe,)).payload(), "before": before, "probe": after}
