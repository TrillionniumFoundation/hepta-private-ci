"""Bounded full accepted-history reference from byte-attributed v9 source."""

import hashlib
import json
import numpy as np
import torch
from torch import nn
from . import interfaces as base

class HistoryModel(nn.Module):
    def __init__(self):
        super().__init__()
        self.reader = nn.Sequential(nn.Linear(252, 64), nn.Tanh(), nn.Linear(64, 16)).double()

    def forward(self, x):
        triangle = torch.tril(x.new_ones((6, 6)))
        slots = x[:, None] * triangle[None, :, :, None]
        masks = triangle[None].expand(len(x), -1, -1)
        features = torch.cat((slots.flatten(2), masks), -1)
        return self.reader(features)

class AcceptedHistory:
    """A causal bounded log; the learned model has no recurrent hidden state."""

    def __init__(self, head, model_id):
        self.head, self.core_id = head, model_id
        self.events, self.rows, self.current = [], [], None

    def snapshot(self, content):
        encoded = json.dumps([content.fingerprint(), self.rows], separators=(",", ":"), allow_nan=False).encode()
        digest = hashlib.sha256(encoded).digest()
        return base.CoreSnapshot(self.core_id, content.fingerprint(), tuple(float(v) for v in digest))

    def initial(self, content):
        if self.current is not None:
            raise base.ContractError("A history holder belongs to one episode")
        self.current = self.snapshot(content)
        return self.current

    def accept(self, state, updated, observation, global_source_increment):
        if (state != self.current or observation.event_id != updated.accepted_event_ids[-1]
                or len(self.rows) >= 6 or global_source_increment < 0):
            raise base.ContractError("History append has stale identity, capacity or clock")
        row = base.cache_features(updated, self.head, global_source_increment).tolist()
        self.rows.append(row)
        self.current = self.snapshot(updated)
        self.events.append({"event_id": observation.event_id, "content_fingerprint": updated.fingerprint(),
                            "global_source_increment": global_source_increment,
                            "row": row, "digest": list(self.current.values)})
        return self.current

    def features(self, state, content):
        if state != self.current or state.content_fingerprint != content.fingerprint():
            raise base.ContractError("History readout requires the current accepted log")
        slots = np.zeros((6, 41), np.float64)
        slots[:len(self.rows)] = self.rows
        mask = np.arange(6) < len(self.rows)
        return np.r_[slots.ravel(), mask.astype(float)]

class HistoryForecast:
    # CORE here selects the scheduler's accept callback, not a neural core.
    kind = base.BackendKind.CORE

    def __init__(self, model, head, holder, model_id):
        self.model, self.head, self.holder, self.reader_id = model, head, holder, model_id

    def evaluate(self, content, state, plan):
        if not plan.requested_reads:
            return self.head.evaluate(content).calibrated_correctness
        levels = {m: int(content.level(m)) for m in base.Modality}
        for step in plan.steps:
            if hasattr(step, "modality"):
                levels[step.modality] = step.prefix_end
        x = torch.tensor(self.holder.features(state, content))[None]
        with torch.no_grad():
            p = self.model.reader(x).sigmoid()[0, base.LEVELS.index(
                (levels[base.Modality.AUDIO], levels[base.Modality.VIDEO]))].item()
        return base.CorrectnessValue(p, self.head.head_id)
