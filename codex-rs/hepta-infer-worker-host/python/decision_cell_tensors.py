"""Shared stateless V2 tensor profile for training and inference.worker consumers.

This library loads advisory tensors, never selects an artifact, owns a checkpoint,
issues a grant or executes a computer action. Temporal/state/parameter heads are
not implemented by this explicit parameterless profile.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import stat
from pathlib import Path
from typing import Any, NamedTuple

import torch
from torch import nn
from safetensors.torch import load as load_tensor_bytes


class TypedHeads(nn.Module):
    def __init__(self, hidden_size: int, width: int = 128) -> None:
        super().__init__()
        self.organ_adapter = nn.Sequential(nn.Linear(hidden_size, width), nn.Tanh())
        self.cell_adapter = nn.Sequential(nn.Linear(width, width), nn.Tanh())
        # Target selection is a pointer over the admitted candidate set.  Each
        # candidate is encoded together with the same frozen state rather than
        # guessed from an arbitrary slot number.  This keeps candidate order
        # non-semantic and matches the runtime DecisionCell contract.
        self.target_score = nn.Linear(width, 1)
        self.action = nn.Linear(width, 6)
        self.disposition = nn.Linear(width, 6)
        self.postcondition = nn.Linear(width, 6)
        self.ood = nn.Linear(width, 2)
        self.value_cost = nn.Linear(width, 2)

    def forward(
        self, value: torch.Tensor, target_pairs: torch.Tensor
    ) -> dict[str, torch.Tensor]:
        if target_pairs.ndim != 3 or target_pairs.shape[:2] != (value.shape[0], 4):
            raise RuntimeError("candidate-aware target embedding shape mismatch")
        hidden = self.cell_adapter(self.organ_adapter(value))
        target_hidden = self.cell_adapter(self.organ_adapter(target_pairs))
        return {
            "action": self.action(hidden),
            "target": self.target_score(target_hidden).squeeze(-1),
            "disposition": self.disposition(hidden),
            "postcondition": self.postcondition(hidden),
            "ood": self.ood(hidden),
            "value_cost": self.value_cost(hidden),
        }



def parameter_group_digests(model: nn.Module) -> dict[str, str]:
    groups = {name: hashlib.sha256(b"hepta.decision-cell-parameter-group.v2\0" + name.encode())
              for name in ("organ_adapter", "cell_adapter", "heads")}
    for name, tensor in sorted(model.state_dict().items()):
        group = name.split(".")[0]
        group = group if group in groups else "heads"
        value = tensor.detach().cpu().contiguous()
        descriptor = (json.dumps({"name": name, "shape": list(value.shape), "dtype": str(value.dtype)},
                                sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n").encode()
        groups[group].update(len(descriptor).to_bytes(8, "big"))
        groups[group].update(descriptor)
        groups[group].update(value.view(torch.uint8).numpy().tobytes())
    return {name: digest.hexdigest() for name, digest in groups.items()}


def checked_bytes(path: Path, expected: str, maximum: int) -> bytes:
    if not isinstance(expected, str) or len(expected) != 64 or any(c not in "0123456789abcdef" for c in expected):
        raise ValueError("invalid expected content digest")
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
    with os.fdopen(os.open(path, flags), "rb") as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or not 0 < info.st_size <= maximum:
            raise ValueError("artifact is not a bounded regular file")
        data = stream.read(maximum + 1)
    if len(data) > maximum or hashlib.sha256(data).hexdigest() != expected:
        raise ValueError("artifact content digest mismatch")
    return data


def strict_json(data: bytes) -> dict[str, Any]:
    def unique(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result = dict(pairs)
        if len(result) != len(pairs):
            raise ValueError("duplicate artifact field")
        return result
    def nonfinite(value: str) -> None:
        raise ValueError("non-finite JSON value: " + value)
    result = json.loads(data, object_pairs_hook=unique, parse_constant=nonfinite)
    if not isinstance(result, dict):
        raise ValueError("artifact manifest is not an object")
    return result


def validate_runtime_profile(profile: dict[str, Any]) -> None:
    """Reject correctly hashed but unsupported semantic interpretations."""
    actions = ["open_path", "navigate", "copy_text", "notify", "request_evidence", "stop"]
    expected = {
        "schema": "hepta.decision-cell-runtime-profile.v2",
        "composition": "shared-base/organ-adapter/cell-adapter/typed-heads",
        "projection_schema": "hepta.decision-cell-text-projection.v1",
        "actions": actions,
        "action_semantic_digests": {
            name: hashlib.sha256(b"hepta.decision-cell-action-label.v1\0" + name.encode()).hexdigest()
            for name in actions
        },
        "dispositions": ["continue", "stop", "abstain", "request_evidence", "slow_path", "success"],
        "target_count": 4,
        "maximum_length": 192,
        "target_pointer_profile": "candidate-pair-shared-scorer.v1",
        "pooling": "attention-mask-mean-v1",
        "parameter_values": "none-v1",
        "postcondition_labels": actions,
        "postcondition_semantic_digests": {
            name: hashlib.sha256(b"hepta.decision-cell-postcondition-label.v1\0" + name.encode()).hexdigest()
            for name in actions
        },
    }
    if set(profile) != {*expected, "head_width"}:
        raise ValueError("unsupported runtime profile fields")
    for name in ("target_count", "maximum_length", "head_width"):
        if type(profile[name]) is not int:
            raise ValueError("runtime profile dimensions must be integers")
    if not 1 <= profile["head_width"] <= 512:
        raise ValueError("unsupported head width")
    if any(profile[name] != value for name, value in expected.items()):
        raise ValueError("unsupported runtime profile semantics")


class HeadSupportRuleV2(NamedTuple):
    """Immutable bound calibration, shared by the tensor and IPC consumers.

    Recomputing from logits establishes arithmetic consistency only. It cannot
    prove encoder execution, statistical calibration trust or effect authority.
    """
    temperatures: tuple[tuple[str, float], ...]
    minimum_confidence: float
    maximum_ood: float

    @classmethod
    def from_calibration(cls, calibration):
        if not isinstance(calibration, dict):
            raise ValueError("missing calibration")
        temperatures = calibration.get("temperatures")
        if not isinstance(temperatures, dict) or set(temperatures) != {"action", "target", "disposition", "postcondition", "ood"}:
            raise ValueError("invalid calibration temperatures")
        values = list(temperatures.values())
        if any(type(v) not in (int, float) or not math.isfinite(v) or v <= 0 for v in values):
            raise ValueError("invalid calibration temperatures")
        for name in ("minimum_confidence", "maximum_ood_probability"):
            v = calibration.get(name)
            if type(v) not in (int, float) or not math.isfinite(v) or not 0 <= v <= 1:
                raise ValueError("invalid calibration threshold")
        return cls(tuple(sorted(temperatures.items())), calibration["minimum_confidence"],
                   calibration["maximum_ood_probability"])

    def apply(self, outputs: dict[str, torch.Tensor]) -> dict[str, torch.Tensor]:
        result = {name: torch.softmax(outputs[name] / temperature, dim=-1)
                  for name, temperature in self.temperatures}
        if any(not torch.isfinite(value).all() for value in result.values()):
            raise ValueError("non-finite calibrated probabilities")
        confidence = result["action"].max(dim=-1).values
        result["supported"] = (confidence >= self.minimum_confidence) & (
            result["ood"][:, 1] < self.maximum_ood)
        return result


def bound_support_rule(manifest_path: Path, expected: dict[str, Any]) -> HeadSupportRuleV2:
    """Read the host-bound manifest before process creation, never a worker path."""
    raw = checked_bytes(manifest_path, expected["head_manifest_sha256"], 256 * 1024)
    manifest = strict_json(raw)
    if (manifest.get("schema") != "hepta.decision-cell-head-artifact.v2" or
            manifest.get("base_model", {}).get("snapshot_digest") != expected["base_snapshot_digest"]):
        raise ValueError("calibration manifest identity mismatch")
    profile = manifest.get("runtime_profile")
    if not isinstance(profile, dict):
        raise ValueError("missing runtime profile")
    validate_runtime_profile(profile)
    profile_bytes = (json.dumps(profile, sort_keys=True, separators=(",", ":"),
                              ensure_ascii=False, allow_nan=False) + "\n").encode()
    if hashlib.sha256(profile_bytes).hexdigest() != expected["runtime_profile_sha256"]:
        raise ValueError("calibration runtime profile mismatch")
    return HeadSupportRuleV2.from_calibration(manifest.get("calibration"))


class HeadTensorBundleV2:
    """Load a caller-bound artifact into the same tensor graph used for training.

    Expected digests/profile must come from the existing artifact owner, not model
    output. Validation supplies integrity, not selection/authority/currentness.
    Features remain caller-supplied: this class does not claim a verified encoder,
    durable state, temporal inference, or authenticated external-effect permission.
    """
    def __init__(self, *, manifest_path: Path, manifest_sha256: str,
                 weights_path: Path, weights_sha256: str,
                 expected_base_snapshot: str, expected_runtime_profile: dict[str, Any]):
        raw = checked_bytes(manifest_path, manifest_sha256, 256 * 1024)
        manifest = strict_json(raw)
        if manifest.get("schema") != "hepta.decision-cell-head-artifact.v2":
            raise ValueError("unsupported head artifact version")
        if manifest.get("weights_sha256") != weights_sha256:
            raise ValueError("head weight binding mismatch")
        if manifest.get("base_model", {}).get("snapshot_digest") != expected_base_snapshot:
            raise ValueError("base snapshot mismatch")
        profile = manifest.get("runtime_profile")
        if profile != expected_runtime_profile or not isinstance(profile, dict):
            raise ValueError("runtime profile substitution")
        validate_runtime_profile(profile)
        width = profile["head_width"]
        weight_bytes = checked_bytes(weights_path, weights_sha256, 16 * 1024 * 1024)
        if len(weight_bytes) != manifest.get("weights_bytes"):
            raise ValueError("head weight size mismatch")
        state = load_tensor_bytes(weight_bytes)
        first = state.get("organ_adapter.0.weight")
        if first is None or first.ndim != 2 or not 1 <= first.shape[1] <= 4096:
            raise ValueError("invalid organ adapter shape")
        if any(t.dtype != torch.float32 or not torch.isfinite(t).all() for t in state.values()):
            raise ValueError("unsupported or non-finite tensor values")
        model = TypedHeads(first.shape[1], width).eval()
        model.load_state_dict(state, strict=True)
        if sum(t.numel() for t in model.parameters()) != manifest.get("head_parameter_count"):
            raise ValueError("head parameter count mismatch")
        if parameter_group_digests(model) != manifest.get("parameter_group_sha256"):
            raise ValueError("organ/cell/head parameter binding mismatch")
        support_rule = HeadSupportRuleV2.from_calibration(manifest.get("calibration"))
        model.requires_grad_(False)
        self._model = model
        self._hidden_size = first.shape[1]
        self._manifest_bytes = raw
        self._support_rule = support_rule
        self.manifest_sha256 = manifest_sha256

    def observe(self, state: torch.Tensor, candidates: torch.Tensor) -> dict[str, torch.Tensor]:
        if state.ndim != 2 or not 1 <= state.shape[0] <= 32 or state.shape[1] != self._hidden_size:
            raise ValueError("invalid state feature shape")
        if tuple(candidates.shape) != (state.shape[0], 4, self._hidden_size):
            raise ValueError("invalid target feature shape")
        if not state.is_floating_point() or not candidates.is_floating_point():
            raise ValueError("model features must use real floating-point tensors")
        # Validate the owned snapshot after conversion, not mutable caller buffers.
        state = state.detach().to(device="cpu", dtype=torch.float32).clone()
        candidates = candidates.detach().to(device="cpu", dtype=torch.float32).clone()
        if not torch.isfinite(state).all() or not torch.isfinite(candidates).all():
            raise ValueError("non-finite model features")
        with torch.inference_mode():
            outputs = self._model(state, candidates)
            if any(not torch.isfinite(value).all() for value in outputs.values()):
                raise ValueError("non-finite head output")
        return {key: value.clone() for key, value in outputs.items()}

    def probabilities(self, state: torch.Tensor, candidates: torch.Tensor) -> dict[str, torch.Tensor]:
        """Apply bound temperatures/thresholds without claiming calibrated trust.

        `supported` is only the recorded statistical rule. Legal-action masking,
        current evidence, authority and terminal observation remain outside it.
        """
        return self.observe_with_probabilities(state, candidates)[1]

    def observe_with_probabilities(self, state: torch.Tensor, candidates: torch.Tensor):
        """Consume adapters/heads once and calibrate that exact tensor result."""
        outputs = self.observe(state, candidates)
        return outputs, self._support_rule.apply(outputs)
