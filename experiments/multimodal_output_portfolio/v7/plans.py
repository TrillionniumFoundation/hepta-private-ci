"""Inference-only internal content-plan gate with complete initial state trace."""

from copy import deepcopy
from dataclasses import dataclass, replace
import hashlib
from pathlib import Path

import torch
from torch import nn

from ..v6.neural import parameter_hash, read_checkpoint
from .snapshot import Snapshot
from .sources import digest, is_digest


PLANS = (("refine_semantic", "couple"), ("couple", "refine_image"),
         ("couple", "refine_text"), ("refine_image", "refine_text"))
ALLOCATION_PLAN = ("refine_image", "refine_text")
SCHEMA = "hepta.ndu-v7.controlled-snapshot.v1"


class PlanHead(nn.Module):
    def __init__(self, hidden=32):
        super().__init__()
        if hidden != 32:
            raise ValueError("Unregistered plan-head width")
        self.config = {"hidden": hidden}
        self.net = nn.Sequential(nn.Linear(96, hidden), nn.Tanh(), nn.Linear(hidden, len(PLANS)))

    def forward(self, context):
        return self.net(context)


@dataclass(frozen=True)
class ControlledState:
    neural: object
    plan_indices: tuple[int, ...]
    initial_state_keys: tuple[str, ...]
    initial_tensor_bits: tuple[tuple[tuple[int, ...], ...], ...]
    snapshot_digest: str

    @property
    def plan_index(self):
        return self.plan_indices[0] if len(self.plan_indices) == 1 else self.plan_indices

    @property
    def initial_actions(self):
        actions = tuple(ALLOCATION_PLAN if index == -1 else PLANS[index] for index in self.plan_indices)
        return actions[0] if len(actions) == 1 else actions

    @property
    def step_count(self):
        return self.neural.step_count

    @property
    def content_control(self):
        return self.neural.content_control

    @property
    def source_digest(self):
        return self.neural.source_digest


class ControlledSnapshot:
    initial_plan_cost = 2

    def __init__(self, base, gate, metadata=None):
        self._base = base
        self._gate = deepcopy(gate).cpu().eval().requires_grad_(False)
        self.config = deepcopy(base.config)
        self.metadata = {**deepcopy(base.metadata), **deepcopy(metadata or {})}
        self._gate_sha256 = parameter_hash(self._gate)
        self.fingerprint = self._combined_digest()

    def _combined_digest(self):
        return digest({"schema": SCHEMA, "base": self._base.fingerprint,
                       "gate": self._gate_sha256, "gate_config": self._gate.config,
                       "plans": PLANS, "allocation_plan": ALLOCATION_PLAN,
                       "selection": "argmax", "initial_plan_cost": self.initial_plan_cost})

    def verify_integrity(self):
        self._base.verify_integrity()
        if (parameter_hash(self._gate) != self._gate_sha256 or self._combined_digest() != self.fingerprint
                or self.config != self._base.config):
            raise RuntimeError("Controlled snapshot configuration/parameters changed")
        return self.fingerprint

    def _check_state(self, state):
        if (not isinstance(state, ControlledState) or state.snapshot_digest != self.fingerprint
                or len(state.plan_indices) != len(state.neural.h) or state.step_count < 2
                or len(state.initial_state_keys) != 3 or any(not is_digest(key) for key in state.initial_state_keys)
                or len(state.initial_tensor_bits) != 3 or any(len(blocks) != 4 for blocks in state.initial_tensor_bits)
                or any(len(block) != 96 * len(state.neural.h) for blocks in state.initial_tensor_bits for block in blocks)
                or any(index not in {-1, *range(len(PLANS))} for index in state.plan_indices)
                or any((index != -1) != state.content_control for index in state.plan_indices)):
            raise ValueError("Foreign or malformed controlled state")
        self._base._check_state(state.neural)

    @torch.inference_mode()
    def encode(self, observation, noise_seed=0, *, content_control=True):
        self.verify_integrity()
        state = self._base.encode(observation, noise_seed, content_control=content_control)
        choices = (self._gate(state.context).argmax(1) if content_control else
                   torch.full((len(state.h),), -1, dtype=torch.long))
        traces = [self._base.state_key(state)]
        raw_traces = [tuple(tuple(getattr(state, name).contiguous().numpy().view("uint32").reshape(-1).tolist())
                            for name in ("h", "image", "text", "context"))]
        for depth in range(2):
            groups, positions = [], []
            for index, plan in (*enumerate(PLANS), (-1, ALLOCATION_PLAN)):
                ids = (choices == index).nonzero().flatten()
                if not len(ids):
                    continue
                group = replace(state, **{name: getattr(state, name)[ids]
                                          for name in ("h", "image", "text", "context")})
                groups.append(self._base.step(group, plan[depth]))
                positions.append(ids)
            order = torch.cat(positions).argsort()
            state = replace(state, **{name: torch.cat([getattr(group, name) for group in groups])[order]
                                       for name in ("h", "image", "text")}, step_count=state.step_count + 1)
            traces.append(self._base.state_key(state))
            raw_traces.append(tuple(tuple(getattr(state, name).contiguous().numpy().view("uint32").reshape(-1).tolist())
                                    for name in ("h", "image", "text", "context")))
        return ControlledState(state, tuple(choices.tolist()), tuple(traces), tuple(raw_traces), self.fingerprint)

    def step(self, state, action):
        self._check_state(state)
        return replace(state, neural=self._base.step(state.neural, action))

    def decode(self, state):
        self._check_state(state)
        return self._base.decode(state.neural)

    def semantic_probabilities(self, state):
        self._check_state(state)
        return self._base.semantic_probabilities(state.neural)

    def state_features(self, state):
        self._check_state(state)
        return self._base.state_features(state.neural)

    def observation_identity(self, state):
        self._check_state(state)
        return digest({"snapshot": self.fingerprint,
                       "public_observation": self._base.observation_identity(state.neural)})

    def state_key(self, state):
        self._check_state(state)
        return digest({"snapshot": self.fingerprint, "state": self._base.state_key(state.neural),
                       "plans": state.plan_indices, "initial_trace": state.initial_state_keys,
                       "initial_tensor_bits": state.initial_tensor_bits})

    def save(self, path):
        self.verify_integrity()
        record = {"schema": SCHEMA, "base": self._base.to_record(), "gate_config": self._gate.config,
                  "gate_state_dict": self._gate.state_dict(), "gate_sha256": self._gate_sha256,
                  "plans": PLANS, "metadata": self.metadata, "snapshot_sha256": self.fingerprint}
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(path.suffix + ".tmp")
        torch.save(record, temporary)
        temporary.replace(path)
        return hashlib.sha256(path.read_bytes()).hexdigest()

    @classmethod
    def load(cls, path, *, expected_file_sha256=None):
        record = read_checkpoint(path, expected_file_sha256)
        if record.get("schema") != SCHEMA or record.get("plans") != PLANS:
            raise ValueError("Unsupported controlled v7 checkpoint")
        base = Snapshot.from_record(record["base"])
        gate = PlanHead(**record["gate_config"])
        gate.load_state_dict(record["gate_state_dict"], strict=True)
        result = cls(base, gate, record.get("metadata"))
        if result.fingerprint != record["snapshot_sha256"] or result._gate_sha256 != record["gate_sha256"]:
            raise ValueError("Controlled checkpoint identity mismatch")
        return result


def load_snapshot(path, *, expected_file_sha256=None):
    record = read_checkpoint(path, expected_file_sha256)
    if record.get("schema") == SCHEMA:
        return ControlledSnapshot.load(path, expected_file_sha256=expected_file_sha256)
    return Snapshot.from_record(record)
