"""New joint content models in the frozen causal READ/WAIT/STOP executor.

Only the prepared service holds unread arrays. The head and forecast consume
accepted rows, actual model state, and public plans. Logical time is development
service time, not a measured live-media latency or independent confirmation.
"""

import hashlib
import json
from pathlib import Path

import numpy as np
import torch
from torch import nn

from experiments.hcsn_v7_support_20261101.content_interface.content_interface import (
    BackendKind, CacheBudget, ContractError, CoreSnapshot, CorrectnessValue,
    Modality, StopEvaluation,
)
from experiments.hcsn_v8_execution_20261101.scheduler.execution import LogicalClock, run_episode
from experiments.hcsn_v8_execution_20261101.scheduler.historical_service import PreparedPrefixService
from experiments.hcsn_v8_execution_20261101.scheduler.planning import Plan, Read, ServiceEstimate
from ..joint_core.data import row_from_cache


ROW, STEPS, MAX_CLASSES, READ_SLOTS = 55, 6, 6, 2
VALUE_WIDTH = ROW * STEPS + STEPS + MAX_CLASSES + READ_SLOTS * 6


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def feature(rows, probabilities, plan):
    """Order-sensitive future READs; WAIT has no time-independent content effect."""
    padded = np.zeros((STEPS, ROW))
    if rows:
        padded[:len(rows)] = np.asarray(rows)
    p = np.zeros(MAX_CLASSES); p[:len(probabilities)] = probabilities
    encoded = np.zeros((READ_SLOTS, 6))
    reads = [step for step in plan.steps if type(step) is Read]
    if len(reads) > READ_SLOTS:
        raise ContractError("The new value reader was fitted for at most two READs")
    for index, step in enumerate(reads):
        column = (0 if step.modality == Modality.AUDIO else 3) + step.prefix_end - 1
        encoded[index, column] = 1
    return np.r_[padded.ravel(), np.arange(STEPS) < len(rows), p, encoded.ravel()]


class ValueNet(nn.Module):
    def __init__(self):
        super().__init__()
        self.layers = nn.Sequential(nn.Linear(VALUE_WIDTH, 32), nn.Tanh(), nn.Linear(32, 1))
        self.double()

    def forward(self, x):
        return self.layers(x).squeeze(-1)


def planned_outcome(plan, now, deadline):
    """Only public release/latency. Late issued work is charged, not accepted."""
    t, requests, accepted = now, 0, []
    for step in plan.steps:
        if t >= deadline:
            break
        if type(step) is Read:
            requests += 1
            completion = max(t, step.prefix_end) + .001
            if completion > deadline:
                t = deadline
                break
            t = completion
            accepted.append(step)
        else:
            t = min(deadline, t + step.seconds)
    return tuple(accepted), t - now, requests


class ServiceModel:
    def estimate(self, content, plan, now, deadline):
        _, duration, requests = planned_outcome(plan, now, deadline)
        return ServiceEstimate(duration, 0., requests)


def bin_probability(value, calibration):
    return float(calibration["rates"][min(int(float(value) * 5), 4)])


class Holder:
    def __init__(self, model, normalization, head_id, prior):
        self.model, self.normalization, self.core_id = model, normalization, head_id
        self.prior = tuple(prior)
        self.rows, self.events, self.current = [], [], None
        self.state = model.initial(torch.zeros((1, ROW), dtype=torch.float64))
        self.probabilities = self.prior

    def snapshot(self, content):
        payload = [content.fingerprint(), self.rows, [x.tolist() for x in self.state], self.probabilities]
        digest = hashlib.sha256(json.dumps(payload, separators=(",", ":"), allow_nan=False).encode()).digest()
        return CoreSnapshot(self.core_id, content.fingerprint(), tuple(float(x) for x in digest))

    def initial(self, content):
        if self.current is not None:
            raise ContractError("Joint holder is single episode")
        self.content, self.current = content, self.snapshot(content)
        return self.current

    def accept(self, state, updated, observation, increment):
        if state != self.current or len(self.rows) >= STEPS:
            raise ContractError("Stale or oversized joint history")
        current_global = max(updated.level(m) for m in Modality)
        raw = row_from_cache(updated, observation.modality, current_global - increment)
        row = np.asarray(self.normalization.apply(raw), dtype=np.float64)
        tensor = torch.as_tensor(row[None], dtype=torch.float64)
        with torch.no_grad():
            self.state, event = self.model.step(tensor, self.state)
            self.rows.append(row.tolist())
            history = [torch.as_tensor(np.asarray(x)[None], dtype=torch.float64) for x in self.rows]
            logits = self.model.classify(history, self.state)
            self.probabilities = tuple(torch.softmax(logits, -1)[0].tolist())
        self.content, self.current = updated, self.snapshot(updated)
        self.events.append({"event_id": observation.event_id, "source_time": observation.prefix_end,
            "global_source_increment": increment, "raw_row": np.asarray(raw).tolist(), "model_row": row.tolist(),
            "state": [x.tolist() for x in self.state], "event": {k: v.tolist() for k, v in event.items()},
            "probabilities": self.probabilities, "content_fingerprint": updated.fingerprint(),
            "digest": self.current.values})
        return self.current


class Head:
    def __init__(self, holder, calibration):
        self.holder, self.calibration, self.head_id = holder, calibration, holder.core_id

    def evaluate(self, content):
        if self.holder.current.content_fingerprint != content.fingerprint():
            raise ContractError("Head requires this actual accepted cache")
        p = self.holder.probabilities
        return StopEvaluation(p, CorrectnessValue(bin_probability(max(p), self.calibration), self.head_id))


class Forecast:
    kind = BackendKind.CORE

    def __init__(self, holder, head, value_model, mean, scale, calibration, clock, deadline):
        self.holder, self.head, self.value_model = holder, head, value_model
        self.mean, self.scale, self.calibration = mean, scale, calibration
        self.clock, self.deadline = clock, deadline
        self.reader_id = holder.core_id + "-value"

    def evaluate(self, content, state, plan):
        h = self.holder
        if state != h.current or state.content_fingerprint != content.fingerprint():
            raise ContractError("Future reader requires this actual accepted state")
        accepted, _, _ = planned_outcome(plan, self.clock.now(), self.deadline)
        if not accepted:
            return self.head.evaluate(content).calibrated_correctness
        x = (feature(h.rows, h.probabilities, Plan(accepted)) - self.mean) / self.scale
        with torch.no_grad():
            p = float(torch.sigmoid(self.value_model(torch.as_tensor(x[None], dtype=torch.float64)))[0])
        return CorrectnessValue(bin_probability(p, self.calibration), self.head.head_id)


class LightPlans:
    """Fixed public threshold, then the earliest next source prefix; no forecasts."""
    def __init__(self, holder, head, threshold=.8):
        self.holder, self.head, self.threshold = holder, head, threshold

    def __iter__(self):
        return self

    def __next__(self):
        if bin_probability(max(self.holder.probabilities), self.head.calibration) >= self.threshold:
            return None
        levels = {Modality.AUDIO: 0, Modality.VIDEO: 0}
        for event in self.holder.events:
            row = event["raw_row"]
            levels[Modality.AUDIO], levels[Modality.VIDEO] = round(row[32]*3), round(row[33]*3)
        candidates = [Read(m, levels[m]+1) for m in Modality if levels[m] < 3]
        if not candidates:
            return None
        return Plan((min(candidates, key=lambda x: (x.prefix_end, x.modality.value)),))


def episode(candidate, data, index, policy, service_factory=PreparedPrefixService):
    model, normalization, value, metadata = candidate
    object_id = "v13-" + metadata["head_id"] + "-" + str(index) + "-" + policy
    holder = Holder(model, normalization, metadata["head_id"], metadata["train_prior"])
    head = Head(holder, metadata["stop_calibration"])
    clock, deadline = LogicalClock(), 4.
    forecast = Forecast(holder, head, value, np.asarray(metadata["value_mean"]),
                        np.asarray(metadata["value_scale"]), metadata["future_calibration"], clock, deadline)
    valid = data["valid"][index]
    arrays = data["x"][index, valid], data["observed"][index, valid], data["relative_times"][index, valid]
    fixed = None
    if policy == "fixed":
        fixed = iter((Plan(tuple(Read(m, p) for m, p in ((Modality.VIDEO, 1), (Modality.AUDIO, 2),
            (Modality.VIDEO, 2), (Modality.AUDIO, 3), (Modality.VIDEO, 3)))),))
    elif policy == "light":
        fixed = LightPlans(holder, head)
    elif policy != "value":
        raise ValueError("Unknown declared policy")
    result = run_episode(object_id, CacheBudget(65536), head, forecast, ServiceModel(),
        service_factory(*arrays, object_id), lambda _: None, clock=clock, core=holder, deadline=deadline,
        horizon=6 if policy == "fixed" else 2, wait_seconds=(.25,), fixed_plans=fixed)
    return result, holder.events
