"""Explicit command-conditioned variant validated by the bounded v6 probe.

LayerNorm and learned public-command FiLM are one combined architecture. The
encoder never reads Target, permutes images, or repairs generated captions.
Legacy construction and legacy checkpoint identities remain separate.
"""

from copy import deepcopy
import hashlib
import json

import torch
from torch import nn

from .data import Observation, VOCAB
from .neural import (CONDITIONED_ARCHITECTURE, CONDITIONED_SCHEMA, NeuralPortfolio,
                     NeuralSnapshot, NeuralState, model_from_config, parameter_hash)


class ConditionedPortfolio(NeuralPortfolio):
    """Exact validated visual/fusion normalization and learned command FiLM."""

    def __init__(self, hidden=96, noise_scale=.15, command_gain=.5, layer_norm_eps=1e-5):
        super().__init__(hidden, noise_scale)
        if command_gain != .5 or layer_norm_eps != 1e-5:
            raise ValueError("Registered variant fixes command_gain=.5 and LayerNorm epsilon=1e-5")
        layers = list(self.pixel_encoder.children())
        self.pixel_encoder = nn.Sequential(*layers[:-1], nn.LayerNorm(hidden, eps=layer_norm_eps),
                                           layers[-1])
        self.fuse = nn.Sequential(self.fuse[0], nn.LayerNorm(hidden, eps=layer_norm_eps), nn.Tanh())
        self.command_embedding = nn.Embedding(len(VOCAB), hidden)
        self.command_film = nn.Linear(hidden, 2 * hidden)
        self.command_gain = command_gain
        self.config = {"hidden": hidden, "noise_scale": noise_scale, "command_gain": command_gain,
                       "layer_norm_eps": layer_norm_eps, "architecture": CONDITIONED_ARCHITECTURE}

    def encode(self, observation, noise=None):
        if not isinstance(observation, Observation):
            raise TypeError("Inference encoder accepts Observation only")
        if observation.pixels.ndim != 4 or observation.pixels.shape[1:] != (1, 28, 56):
            raise ValueError("Expected Bx1x28x56 public pixels")
        if observation.mask.shape != observation.pixels.shape:
            raise ValueError("Pixel/missingness shape mismatch")
        if observation.text_tokens.ndim != 2 or observation.text_tokens.shape[1] != 8:
            raise ValueError("Expected eight declared public input tokens")
        visual = self.pixel_encoder(torch.cat((observation.pixels, observation.mask), dim=1))
        _, language = self.text_encoder(self.token_embedding(observation.text_tokens))
        normalized = self.fuse[1](self.fuse[0](torch.cat((visual, language[-1]), dim=1)))
        command = self.command_embedding(observation.text_tokens[:, 1])
        scale, bias = self.command_film(command).chunk(2, dim=1)
        context = self.fuse[2](normalized * (1 + self.command_gain * torch.tanh(scale))
                               + self.command_gain * torch.tanh(bias))
        h = context if noise is None else context + self.noise_scale * noise
        if h.shape != context.shape:
            raise ValueError("Initial latent noise shape mismatch")
        return NeuralState(h, torch.tanh(self.initial_image(h)),
                           torch.tanh(self.initial_text(h)), context)


def _config_digest(config):
    encoded = json.dumps(config, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(encoded.encode()).hexdigest()


class ConditionedSnapshot(NeuralSnapshot):
    """Frozen variant identity binds parameters and complete inference config."""

    def __init__(self, model, metadata=None):
        if type(model) is not ConditionedPortfolio:
            raise TypeError("ConditionedSnapshot requires the registered architecture")
        super().__init__(model, metadata)
        self.parameter_sha256 = self.fingerprint
        self.configuration_sha256 = _config_digest(self.config)
        self.fingerprint = self._bound_digest()

    def _bound_digest(self):
        bound = {"schema": CONDITIONED_SCHEMA, "parameters": self.parameter_sha256,
                 "config_sha256": _config_digest(self.config)}
        return hashlib.sha256(json.dumps(bound, sort_keys=True, separators=(",", ":")).encode()).hexdigest()

    def _assert_configuration(self):
        if (self.config != self._model.config
                or _config_digest(self.config) != self.configuration_sha256
                or self._model.hidden != self.config["hidden"]
                or self._model.noise_scale != self.config["noise_scale"]
                or self._model.command_gain != self.config["command_gain"]
                or self._model.pixel_encoder[6].eps != self.config["layer_norm_eps"]
                or self._model.fuse[1].eps != self.config["layer_norm_eps"]):
            raise RuntimeError("Conditioned inference configuration changed")

    def verify_integrity(self):
        self._assert_configuration()
        if (parameter_hash(self._model) != self.parameter_sha256
                or self.fingerprint != self._bound_digest()):
            raise RuntimeError("Conditioned inference snapshot changed")
        return self.fingerprint

    def _check_state(self, state):
        self._assert_configuration()
        super()._check_state(state)

    def to_record(self):
        self.verify_integrity()
        return {"schema": CONDITIONED_SCHEMA, "config": deepcopy(self.config),
                "config_sha256": self.configuration_sha256,
                "state_dict": self._model.state_dict(), "parameter_sha256": self.parameter_sha256,
                "snapshot_sha256": self.fingerprint, "metadata": self.metadata}

    @classmethod
    def _from_record(cls, record):
        if (record.get("schema") != CONDITIONED_SCHEMA
                or record.get("config", {}).get("architecture") != CONDITIONED_ARCHITECTURE):
            raise ValueError("Unsupported conditioned snapshot architecture/schema")
        model = model_from_config(record["config"])
        model.load_state_dict(record["state_dict"], strict=True)
        snapshot = cls(model, record.get("metadata"))
        if (snapshot.config != record["config"]
                or snapshot.configuration_sha256 != record.get("config_sha256")
                or snapshot.parameter_sha256 != record.get("parameter_sha256")
                or snapshot.fingerprint != record.get("snapshot_sha256")):
            raise ValueError("Conditioned snapshot parameter/configuration hash mismatch")
        return snapshot
