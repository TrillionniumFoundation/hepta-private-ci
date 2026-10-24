"""Config-bound frozen v7 snapshots and explicit full-state identities."""

from copy import deepcopy
from dataclasses import replace
import hashlib
from pathlib import Path

import torch

from ..v6.neural import parameter_hash, read_checkpoint
from .model import ARCHITECTURE, SlotPortfolio, State, observation_digest
from .sources import canonical, digest, is_digest


SCHEMA = "hepta.ndu-v7.slot-snapshot.v1"


class Snapshot:
    initial_plan_cost = 0

    def __init__(self, model, metadata=None):
        if type(model) is not SlotPortfolio:
            raise TypeError("Snapshot requires the registered slot architecture")
        self._model = deepcopy(model).cpu().eval().requires_grad_(False)
        self.config = deepcopy(model.config)
        self.metadata = deepcopy(metadata or {})
        self.parameter_sha256 = parameter_hash(self._model)
        self.configuration_sha256 = digest(self.config)
        self.fingerprint = digest({"schema": SCHEMA, "parameters": self.parameter_sha256,
                                   "configuration": self.configuration_sha256})

    def _check_configuration(self):
        if (self.config != self._model.config or digest(self.config) != self.configuration_sha256
                or self._model.noise_scale != self.config["noise_scale"]
                or self._model.cell_gain != self.config["cell_gain"]
                or self._model.hidden != self.config["hidden"] or self._model.slot != 48
                or self._model.pixel_encoder[8].eps != self.config["layer_norm_eps"]
                or self._model.fuse[1].eps != self.config["layer_norm_eps"]):
            raise RuntimeError("Frozen model configuration changed")

    def verify_integrity(self):
        self._check_configuration()
        if (parameter_hash(self._model) != self.parameter_sha256
                or self.fingerprint != digest({"schema": SCHEMA, "parameters": self.parameter_sha256,
                                                "configuration": self.configuration_sha256})):
            raise RuntimeError("Frozen model parameters/identity changed")
        return self.fingerprint

    def _check_state(self, state):
        self._check_configuration()
        if (not isinstance(state, State) or state.snapshot_digest != self.fingerprint
                or type(state.content_control) is not bool or type(state.step_count) is not int
                or not 0 <= state.step_count <= 4 or not is_digest(state.source_digest)):
            raise ValueError("Foreign or malformed generation state")
        if any(not isinstance(getattr(state, field), torch.Tensor)
               or getattr(state, field).dtype != torch.float32
               or getattr(state, field).shape != state.h.shape or getattr(state, field).ndim != 2
               or getattr(state, field).shape[1] != 96 or not torch.isfinite(getattr(state, field)).all()
               for field in ("h", "image", "text", "context")):
            raise ValueError("Invalid generation tensor profile")

    @torch.inference_mode()
    def encode(self, observation, noise_seed=0, *, content_control=True):
        self.verify_integrity()
        source = observation_digest(observation)
        rng = torch.Generator().manual_seed(int(noise_seed))
        noise = torch.randn((len(observation.pixels), 96), generator=rng)
        state = self._model.encode(observation, noise, content_control=content_control)
        return replace(state, snapshot_digest=self.fingerprint, source_digest=source)

    @torch.inference_mode()
    def step(self, state, action):
        self._check_state(state)
        if state.step_count == 4:
            raise ValueError("Registered total neural horizon exhausted")
        return self._model.step(state, action)

    @torch.inference_mode()
    def decode(self, state):
        self._check_state(state)
        return self._model.decode(state)

    @torch.inference_mode()
    def semantic_probabilities(self, state):
        self._check_state(state)
        return self._model.semantic_probabilities(state)

    @torch.inference_mode()
    def state_features(self, state):
        self._check_state(state)
        return self._model.state_features(state)

    def observation_identity(self, state):
        self._check_state(state)
        return digest({"snapshot": self.fingerprint, "public_observation": state.source_digest})

    def state_key(self, state):
        self._check_state(state)
        value = hashlib.sha256(canonical({"snapshot": self.fingerprint,
                                         "observation": state.source_digest,
                                         "content_control": state.content_control,
                                         "step_count": state.step_count}))
        for field in ("h", "image", "text", "context"):
            tensor = getattr(state, field).detach().cpu().contiguous()
            value.update(str((str(tensor.dtype), tuple(tensor.shape))).encode())
            value.update(tensor.numpy().tobytes())
        return value.hexdigest()

    def to_record(self):
        self.verify_integrity()
        return {"schema": SCHEMA, "config": deepcopy(self.config),
                "config_sha256": self.configuration_sha256, "parameter_sha256": self.parameter_sha256,
                "snapshot_sha256": self.fingerprint, "state_dict": self._model.state_dict(),
                "metadata": deepcopy(self.metadata)}

    def save(self, path):
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(path.suffix + ".tmp")
        torch.save(self.to_record(), temporary)
        temporary.replace(path)
        return hashlib.sha256(path.read_bytes()).hexdigest()

    @classmethod
    def from_record(cls, record):
        if record.get("schema") != SCHEMA or record.get("config", {}).get("architecture") != ARCHITECTURE:
            raise ValueError("Unsupported v7 architecture/checkpoint schema")
        config = dict(record["config"])
        config.pop("architecture")
        model = SlotPortfolio(**config)
        model.load_state_dict(record["state_dict"], strict=True)
        result = cls(model, record.get("metadata"))
        if (result.config != record["config"] or result.configuration_sha256 != record["config_sha256"]
                or result.parameter_sha256 != record["parameter_sha256"]
                or result.fingerprint != record["snapshot_sha256"]):
            raise ValueError("V7 checkpoint parameter/configuration identity mismatch")
        return result

    @classmethod
    def load(cls, path, *, expected_file_sha256=None):
        return cls.from_record(read_checkpoint(path, expected_file_sha256))
