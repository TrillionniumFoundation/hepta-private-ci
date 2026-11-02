"""Byte-attributed historical AV interface, extracted from the other v9 archive.

All objects are previously exposed historical recordings. This is not v6.
"""

import hashlib
import itertools
from pathlib import Path
import numpy as np
import torch
from experiments.hcsn_v7_support_20261101.content_interface.content_interface import BackendKind, CacheBudget, ContractError, CoreSnapshot, CorrectnessValue, Modality
from experiments.hcsn_v8_execution_20261101.frontend.replay import episode_arrays, legacy_data, populated_cache
from experiments.hcsn_v8_execution_20261101.scheduler.execution import LogicalClock, run_episode
from experiments.hcsn_v8_execution_20261101.scheduler.historical_probe import FixedServiceModel, fit_development_adapters, fixed_plans
from experiments.hcsn_v8_execution_20261101.scheduler.historical_service import PreparedPrefixService
from experiments.hcsn_causal_execution_v3.av_probe import labels_of

LEVELS = tuple(itertools.product(range(4), repeat=2))

def cache_features(content, head, increment):
    """Current common-cache content, never future data, object IDs or labels."""
    vectors = [np.zeros(16) if content.observation(m) is None
               else np.asarray(content.observation(m).aligned) for m in Modality]
    p = np.zeros(6)
    current = head.classify(content)
    p[:len(current)] = current
    return np.r_[*vectors, p, content.level(Modality.AUDIO) / 3,
                 content.level(Modality.VIDEO) / 3, increment].astype(np.float64)

class PersistentCore:
    def __init__(self, model, head, model_id):
        self.model, self.head, self.core_id = model, head, model_id
        self.updates = []

    def initial(self, content):
        return CoreSnapshot(self.core_id, content.fingerprint(), (0.0,) * 32)

    def accept(self, state, updated, observation, global_source_increment):
        if state.core_id != self.core_id or observation.event_id != updated.accepted_event_ids[-1]:
            raise ContractError("Core update identity mismatch")
        x = torch.tensor(cache_features(updated, self.head, global_source_increment))[None]
        previous = torch.tensor(state.values, dtype=torch.float64)[None]
        with torch.no_grad():
            value = self.model.step(x, previous)[0].numpy()
        self.updates.append({"event": observation.event_id, "global_source_increment": global_source_increment,
                             "before": list(state.values), "after": value.tolist(),
                             "content_fingerprint": updated.fingerprint()})
        return CoreSnapshot(self.core_id, updated.fingerprint(), tuple(value))

class Forecast:
    def __init__(self, model, head, model_id):
        self.model, self.head = model, head
        self.kind = BackendKind.DIRECT_HISTORY if model.family == "direct" else BackendKind.CORE
        self.reader_id = model_id

    def evaluate(self, content, state, plan):
        if not plan.requested_reads:
            return self.head.evaluate(content).calibrated_correctness
        if self.kind == BackendKind.CORE and (state.core_id != self.reader_id
                or state.content_fingerprint != content.fingerprint()):
            raise ContractError("Forecast state is stale or belongs to another model")
        levels = {m: int(content.level(m)) for m in Modality}
        for step in plan.steps:
            if hasattr(step, "modality"):
                levels[step.modality] = step.prefix_end
        # dt is used in observation assimilation only. Current cache readout is
        # time-independent, like the common head, and future features are unseen.
        x = torch.tensor(cache_features(content, self.head, 0.0))[None]
        h = torch.zeros((1, 32), dtype=torch.float64) if state is None else torch.tensor(
            state.values, dtype=torch.float64)[None]
        with torch.no_grad():
            p = self.model.predict(x, h).sigmoid()[0, LEVELS.index(
                (levels[Modality.AUDIO], levels[Modality.VIDEO]))].item()
        return CorrectnessValue(p, self.head.head_id)

def schedules():
    result = []
    for audio_positions in itertools.combinations(range(5), 2):
        result.append((Modality.AUDIO,) + tuple(Modality.AUDIO if i in audio_positions
                                              else Modality.VIDEO for i in range(5)))
    return result

def dataset(task, split, head):
    """Every legal full schedule after mandatory A1; rows cluster by recording."""
    data = legacy_data(task, split)
    labels = labels_of(data)
    xs, ys, masks = [], [], []
    for index, label in enumerate(labels):
        caches = {level: populated_cache(data, index, *level) for level in LEVELS}
        correct = np.array([head.classify(caches[level]).argmax() == label for level in LEVELS], float)
        for schedule in schedules():
            a, v, previous = 0, 0, 0
            seq, mask = [], []
            for modality in schedule:
                a += modality == Modality.AUDIO
                v += modality == Modality.VIDEO
                level = max(a, v)
                seq.append(cache_features(caches[a, v], head, float(level - previous)))
                mask.append([ga >= a and gv >= v and (ga, gv) != (a, v) for ga, gv in LEVELS])
                previous = level
            xs.append(seq)
            ys.append(np.tile(correct, (6, 1)))
            masks.append(mask)
    return (torch.tensor(np.asarray(xs)), torch.tensor(np.asarray(ys)),
            torch.tensor(np.asarray(masks), dtype=torch.float64), data)

def data_identity(data):
    return {"array_sha256": data["metadata"]["array_sha256"],
            "source_ids": data["ids"].astype(str).tolist(),
            "content_sha256": hashlib.sha256(np.ascontiguousarray(data["x"]).tobytes()).hexdigest()}
