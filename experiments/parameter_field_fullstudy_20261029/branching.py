"""Versioned full branch records around the unchanged guard48 learning kernel."""

import hashlib
import time

import numpy as np
import torch

from ..multimodal_output_portfolio.field_bridge_v6_gru_adapter_preparation_20261028.adapter import GRUAdapter
from ..multimodal_output_portfolio.field_bridge_v6_gru_adapter_preparation_20261028.contract import strict
from ..multimodal_output_portfolio.field_bridge_v3_20261027 import learning

codec, native = strict.codec, strict.native
BASELINES = {17: 2, 29: 3, 43: 3}
SCHEMA = "hepta.parameter-field.fullstudy.guard48-state.1"


def timed(costs, label, operation):
    wall, cpu = time.perf_counter_ns(), time.process_time_ns()
    try:
        return operation()
    finally:
        costs.add(label + "_wall_ns", time.perf_counter_ns() - wall)
        costs.add(label + "_cpu_ns", time.process_time_ns() - cpu)


class StudyAdapter(GRUAdapter):
    """New cursor/history schema; frozen V6 inspection and tensor setters reused."""

    def __init__(self, context, model, optimizer, binding):
        self.context = context
        self.clock, self.schedule_id, self.path_kind, self.history = 0, 6000, "baseline", []
        panel = {"probe": native(context.probe), "guard": native(context.guard)}
        guard = context.baseline_guard
        super().__init__(
            model, optimizer, binding=binding, architecture={"config": model.config},
            original_generator=context.original, reward_observer=context.observers["reward"],
            context_inputs={"panels_sha256": codec.digest(panel), "seed": context.seed,
                            "corpus_metadata": context.corpus.manifest,
                            "training_protocol": context.protocol},
            guard_baseline={"panel_sha256": codec.digest(panel["guard"]),
                            "source_ids": native(guard["source_ids"]),
                            "output_sha256": guard["output_sha256"],
                            "values": guard["values"]["reward"].copy()},
            named_generators={},
        )

    def capture(self):
        if codec.digest(self._description()) != codec.digest(self.fixed):
            raise ValueError("Immutable scientific context changed")
        tape = learning.schedule(self.context.seed, self.schedule_id, self.clock, 288 - self.clock,
                                 self.context.protocol)
        record = {"schema": SCHEMA, "binding": native(self.binding), "immutable": native(self.fixed),
                  **self._mutable(), "cursor": {
                      "seed": self.context.seed, "schedule_id": self.schedule_id,
                      "path_kind": self.path_kind, "clock": self.clock, "remaining_steps": 288 - self.clock,
                      "total_steps": 288, "guard_grain": 48, "baseline_action": BASELINES[self.context.seed]},
                  "remaining_schedule": tape, "history": native(self.history)}
        self.validate(record)
        return record

    def validate(self, record):
        required = {"schema", "binding", "immutable", "parameters", "buffers", "requires_grad", "optimizer",
                    "optimizer_parameter_names", "gradients", "rng", "cursor", "remaining_schedule", "history"}
        if set(record) != required or record["schema"] != SCHEMA:
            raise ValueError("Incomplete study state inventory")
        if codec.digest({"binding": record["binding"], "immutable": record["immutable"]}) != self.environment_sha256:
            raise ValueError("Branch environment binding mismatch")
        cursor = record["cursor"]
        if set(cursor) != {"seed", "schedule_id", "path_kind", "clock", "remaining_steps", "total_steps", "guard_grain", "baseline_action"}:
            raise ValueError("Unknown cursor field")
        if (cursor["seed"] != self.context.seed or cursor["clock"] not in range(0, 289, 48)
                or cursor["remaining_steps"] != 288 - cursor["clock"] or cursor["guard_grain"] != 48
                or cursor["total_steps"] != 288 or cursor["baseline_action"] != BASELINES[self.context.seed]):
            raise ValueError("Invalid clock, guard or baseline")
        expected = learning.schedule(cursor["seed"], cursor["schedule_id"], cursor["clock"],
                                     cursor["remaining_steps"], self.context.protocol)
        if codec.digest(record["remaining_schedule"]) != codec.digest(expected):
            raise ValueError("Future replay tape changed")
        for section in ("parameters", "buffers"):
            layouts = self.fixed["model_configuration"][section]
            if set(record[section]) != set(layouts):
                raise ValueError("Tensor inventory changed")
            for name, layout in layouts.items():
                value = record[section][name]
                if (not isinstance(value, np.ndarray) or list(value.shape) != layout["shape"]
                        or value.dtype.str != layout["dtype"] or not np.isfinite(value).all()):
                    raise ValueError("Tensor layout or finite-state failure")
        if set(record["gradients"]) != set(record["parameters"]):
            raise ValueError("Incoming gradient inventory changed")
        layouts = self.fixed["model_configuration"]["parameters"]
        if record["requires_grad"] != {name: spec["requires_grad"] for name, spec in layouts.items()}:
            raise ValueError("Trainable inventory changed")
        for name, gradient in record["gradients"].items():
            parameter = record["parameters"][name]
            if gradient is not None and (gradient.shape != parameter.shape or gradient.dtype != parameter.dtype
                                         or not np.isfinite(gradient).all()):
                raise ValueError("Invalid incoming gradient")
        if record["optimizer"]["kind"] != "SGD" or set(record["rng"]) != {"torch_cpu", "python", "numpy", "named"}:
            raise ValueError("Optimizer or RNG inventory changed")
        if record["rng"]["named"] or len(record["history"]) > 6:
            raise ValueError("Unregistered RNG or controller memory")
        mapping = record["optimizer_parameter_names"]
        if set(mapping.values()) != set(record["parameters"]) or len(mapping) != len(record["parameters"]):
            raise ValueError("Optimizer named inventory differs")
        for index, fields in record["optimizer"]["state"].items():
            if index not in mapping or set(fields) != {"momentum_buffer"}:
                raise ValueError("Unknown SGD state")
            momentum, parameter = fields["momentum_buffer"], record["parameters"][mapping[index]]
            if momentum.shape != parameter.shape or momentum.dtype != parameter.dtype or not np.isfinite(momentum).all():
                raise ValueError("Invalid momentum tensor")
        from .heads import history_feature
        if len(record["history"]) > cursor["clock"] // 48:
            raise ValueError("Future controller history")
        if record["history"]:
            # At terminal time validate each row without inventing a seventh slot.
            history_feature(record["history"][:5], [0.] * 12)
            if len(record["history"]) == 6:
                history_feature(record["history"][5:], [0.] * 12)

    def seal(self):
        record = timed(self.context.costs, "state_capture", self.capture)
        raw = timed(self.context.costs, "state_serialize", lambda: codec.dumps(record))
        self.context.costs.add("serialized_branch_bytes", len(raw))
        return raw, hashlib.sha256(raw).hexdigest()

    def restore(self, raw, expected_sha256):
        def perform():
            record = codec.loads(raw, expected_sha256, len(raw))
            self.validate(record)
            if codec.digest(self._description()) != codec.digest(self.fixed):
                raise ValueError("Target immutable context changed")
            prepared = self._prepare(record)
            before = self.capture()
            rollback = self._prepare(before)
            try:
                self._apply(prepared)
                self.clock = record["cursor"]["clock"]
                self.schedule_id = record["cursor"]["schedule_id"]
                self.path_kind = record["cursor"]["path_kind"]
                self.history = native(record["history"])
                if codec.dumps(self.capture()) != raw:
                    raise ValueError("Literal complete-state restore mismatch")
            except BaseException:
                self._apply(rollback)
                self.clock, self.schedule_id = before["cursor"]["clock"], before["cursor"]["schedule_id"]
                self.path_kind, self.history = before["cursor"]["path_kind"], before["history"]
                raise
            return record
        self.context.costs.add("complete_branch_restores")
        return timed(self.context.costs, "state_restore", perform)

    def transition(self, action):
        start = self.clock
        if start >= 288:
            raise ValueError("No remaining transaction")
        receipt = timed(self.context.costs, "guarded_transition", lambda: learning.guarded_block(
            self.context, self.model, self.optimizer, start, action, self.schedule_id))
        self.clock += 48
        receipt["remaining_steps"] = 288 - self.clock
        receipt["logical_clock"] = self.clock
        return receipt


def dynamics_identity(record):
    """Reference-tail physical equivalence; controller history is reported apart."""
    cursor = {k: v for k, v in record["cursor"].items() if k != "path_kind"}
    sections = {k: codec.digest(record[k]) for k in
                ("parameters", "buffers", "optimizer", "gradients", "rng", "immutable", "remaining_schedule")}
    sections["cursor"] = codec.digest(cursor)
    return {"components": sections, "dynamics": codec.digest(sections),
            "controller_history": codec.digest(record["history"])}


def state_difference(left, right):
    identity_left, identity_right = dynamics_identity(left), dynamics_identity(right)
    difference = {}
    for section in ("parameters", "gradients", "buffers"):
        total, maximum, first = 0., 0., None
        for name, value in left[section].items():
            other = right[section][name]
            if value is None or other is None:
                if (value is None) != (other is None):
                    first = first or name
                continue
            delta = value.astype(np.float64) - other.astype(np.float64)
            total += float(np.sum(delta * delta))
            maximum = max(maximum, float(np.max(np.abs(delta))) if delta.size else 0.)
            if np.any(delta):
                first = first or name
        difference[section] = {"l2": total ** .5, "max_abs": maximum, "first_different_tensor": first}
    difference["different_components"] = [k for k, v in identity_left["components"].items()
                                           if v != identity_right["components"][k]]
    squared, maximum, first = 0., 0., None
    for index, name in left["optimizer_parameter_names"].items():
        shape = left["parameters"][name].shape
        a = left["optimizer"]["state"].get(index, {}).get("momentum_buffer", np.zeros(shape))
        b = right["optimizer"]["state"].get(index, {}).get("momentum_buffer", np.zeros(shape))
        delta = a.astype(np.float64) - b.astype(np.float64)
        squared += float(np.sum(delta * delta))
        maximum = max(maximum, float(np.max(np.abs(delta))))
        if np.any(delta):
            first = first or name
    difference["momentum"] = {"l2": squared ** .5, "max_abs": maximum, "first_different_tensor": first}
    difference["reference_tail_state_equal"] = identity_left["dynamics"] == identity_right["dynamics"]
    return difference


def full_current_feature(record, field):
    """All current trainable tensor coordinates; future RNG/tape stay inaccessible."""
    values = [np.asarray(field, dtype=np.float64)]
    names = record["optimizer_parameter_names"]
    by_name = {name: record["optimizer"]["state"].get(index, {}).get("momentum_buffer")
               for index, name in names.items()}
    for name, parameter in record["parameters"].items():
        values.append(parameter.reshape(-1))
        for value in (by_name[name], record["gradients"][name]):
            values.append(np.zeros(parameter.size) if value is None else value.reshape(-1))
            values.append(np.asarray([value is not None], dtype=np.float64))
    values.extend(value.reshape(-1) for value in record["buffers"].values())
    values.append(record["immutable"]["guard_baseline"]["values"])
    cursor = record["cursor"]
    values.append(np.asarray([cursor["clock"], cursor["remaining_steps"], cursor["guard_grain"], cursor["baseline_action"]]))
    for group in record["optimizer"]["param_groups"]:
        values.append(np.asarray([group["lr"], group["momentum"], group["dampening"], group["weight_decay"]]))
    return np.concatenate(values).astype(np.float64, copy=False)
