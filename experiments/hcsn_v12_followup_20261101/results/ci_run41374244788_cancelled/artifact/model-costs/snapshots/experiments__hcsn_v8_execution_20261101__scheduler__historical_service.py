"""Causal requests against restored historical prepared AV arrays.

The adapter does real array selection/copying, with optional real release waits.
It does not decode media or rerun the historical acoustic/visual feature stage.
The input's complete recording is held by the service, never by the controller.
"""

from dataclasses import replace

from experiments.hcsn_v7_support_20261101.content_interface.content_interface import finite
from experiments.hcsn_v8_execution_20261101.frontend.legacy_v3 import prepared_observation
from .execution import ReadResult


class PreparedPrefixService:
    mode = "historical V3 prepared AV array replay; raw decoding and original feature preparation excluded"

    def __init__(self, x, observed, relative_times, object_id, logical_service_seconds=0.001):
        self._arrays = x, observed, relative_times
        self._object_id = object_id
        self.requested = 0
        self.logical_service_seconds = finite(logical_service_seconds, "logical service seconds", 1e-9, 1)
        self.mode += f"; LogicalClock uses declared simulated service {self.logical_service_seconds:g}s/read"

    def request(self, step, clock):
        self.requested += 1
        completion = (max(clock.now(), step.prefix_end) + self.logical_service_seconds
                      if clock.origin_ns is None else None)
        return PreparedPending(self._arrays, self._object_id,
                               f"prepared-{self.requested}", step, completion)


class PreparedPending:
    def __init__(self, arrays, object_id, event_id, step, logical_completion):
        self._arrays = arrays
        self._object_id = object_id
        self._event_id = event_id
        self._step = step
        self._logical_completion = logical_completion

    def wait_until(self, deadline, clock):
        release = float(self._step.prefix_end)
        completion = release if self._logical_completion is None else self._logical_completion
        clock.wait_until(min(deadline, completion))
        if completion > deadline:
            return None
        # Any real copy time belongs to completion, not to earlier availability.
        # Build once, then stamp the parent-observed end of that computation.
        observation = prepared_observation(
            *self._arrays, object_id=self._object_id, modality=self._step.modality,
            prefix_end=self._step.prefix_end, completed_at=clock.now(), event_id=self._event_id)
        observation = replace(observation, completed_at=clock.now())
        return ReadResult(observation=observation)

    def drain(self, clock):
        # An issued request is completed and charged even after frozen output.
        completion = (float(self._step.prefix_end) if self._logical_completion is None
                      else self._logical_completion)
        self.wait_until(completion, clock)
