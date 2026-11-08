"""Expose a temporal kernel through the shared experimental Cell owner.

The bundle binds real recurrent/head parameter digests and the exact model
configuration. Other bundle fields bind caller-supplied immutable artifacts.
Work units charge the actual parameter count once per single-step invocation;
this is a logical admission proxy, not FLOPs or measured energy.
"""

import copy
import time

from .bundle import Bundle
from .lifecycle import CellError, ComponentIdentity, StepResult
from .temporal import TemporalKernel


class TemporalComponent:
    def __init__(self, kernel: TemporalKernel, bundle: Bundle, episode_id: str):
        if not isinstance(kernel, TemporalKernel) or not isinstance(bundle, Bundle):
            raise TypeError("temporal component requires a kernel and complete compatibility bundle")
        self.kernel, self._bundle, self.episode_id = kernel, copy.deepcopy(bundle), episode_id
        self.identity
        self.initial_state()

    @property
    def identity(self):
        expected = {"base": self.kernel.kernel_sha256, "heads": self.kernel.heads_sha256,
                    "composition": self.kernel.config.sha256}
        if any(self._bundle.components.get(name) != value for name, value in expected.items()):
            raise CellError("temporal bundle does not bind this kernel, head and configuration")
        return ComponentIdentity("hepta.temporal.v1", self._bundle.digest())

    def initial_state(self):
        return self.kernel.initial_state(self.episode_id)

    def step(self, payload, state, context):
        if (context.partition.cell_id != self.kernel.cell_id or context.partition.run_id != self.episode_id
                or context.identity != self.identity):
            raise CellError("temporal context differs from bound cell, episode or bundle")
        if not isinstance(payload, dict) or payload.get("operation") not in ("observe", "predict"):
            raise CellError("temporal payload must choose observe or predict")
        observe = payload["operation"] == "observe"
        expected = {"operation", "observation", "cursor"} if observe else {"operation", "action"}
        if set(payload) != expected:
            raise CellError("temporal payload fields differ from the selected operation")
        work = self.kernel.parameter_count
        if work > context.budget.max_work_units:
            raise CellError("temporal operation exceeds the parameter-work reservation")
        wall, cpu = time.perf_counter(), time.process_time()
        if observe:
            state = self.kernel.observe(state, payload["observation"], episode_id=self.episode_id, cursor=payload["cursor"])
            output = {"cursor": state["cursor"]}
        else:
            output = {"logits": self.kernel.predict(state, payload["action"], episode_id=self.episode_id).tolist(),
                      "cursor": state["cursor"]}
        output["cost"] = {"wall_seconds": time.perf_counter() - wall,
                          "process_cpu_seconds": time.process_time() - cpu,
                          "work_unit_kind": "parameter_count_per_single_step", "energy_joules": None}
        return StepResult(output, state, work)
