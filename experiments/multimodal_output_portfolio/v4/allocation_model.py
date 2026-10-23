"""Four separate latent states, frozen learned kernels, and actual Linear work."""

from copy import deepcopy
from dataclasses import dataclass, field
import hashlib
from pathlib import Path

import numpy as np
import torch
from torch import nn

from feedback_model import FeedbackOutputModel, weight_hashes
from model import MODALITIES, OutputModel, encode


INIT_COST, REFINE_COST, EMIT_COST, BUDGET = 3584, 8704, 330240, 351232
DECODER_COSTS = (6656, 69632, 53248, 200704)
ACTIONS = ("EMIT", *("REFINE_" + name for name in MODALITIES))


def tensor_hash(value):
    return hashlib.sha256(value.detach().cpu().contiguous().numpy().tobytes()).hexdigest()


def joint_hash(hashes, kind="latents"):
    if kind not in ("latents", "outputs") or len(hashes) != 4:
        raise ValueError("four ordered digests and a registered domain required")
    payloads = [bytes.fromhex(value) for value in hashes]
    if any(len(value) != 32 for value in payloads):
        raise ValueError("SHA256 digests required")
    domain = ("hepta.modality-portfolio." + kind + ".v1\0").encode()
    return hashlib.sha256(domain + b"".join(payloads)).hexdigest()


@dataclass
class _Ledger:
    spent: int = INIT_COST
    version: int = 0
    counts: list = field(default_factory=lambda: [0, 0, 0, 0])
    feedback_version: int = -1
    feedback_events: int = 0
    sealed: bool = False


@dataclass(frozen=True, eq=False)
class AllocationState:
    _q: torch.Tensor = field(repr=False)
    _anchor: torch.Tensor = field(repr=False)
    _latents: torch.Tensor = field(repr=False)
    _last_update: torch.Tensor = field(repr=False)
    _owner: object = field(repr=False)
    _ledger: _Ledger = field(repr=False)
    version: int = 0

    @property
    def receipt(self):
        ledger = self._ledger
        return {"spent_macs": ledger.spent, "budget_macs": BUDGET,
                "remaining_macs": BUDGET - ledger.spent, "version": ledger.version,
                "refinement_counts": list(ledger.counts), "sealed": ledger.sealed,
                "feedback_events": ledger.feedback_events,
                "allocated_macs": [(d if ledger.sealed else 0) + r * REFINE_COST
                                   for d, r in zip(DECODER_COSTS, ledger.counts)],
                "reserved_emit_macs": 0 if ledger.sealed else EMIT_COST,
                "shared_init_macs": INIT_COST}


class AllocationModel:
    """The current modality owner changes state; shared weights remain fixed."""

    def __init__(self, checkpoint, expected_sha256):
        path = Path(checkpoint)
        self.checkpoint_sha256 = hashlib.sha256(path.read_bytes()).hexdigest()
        if self.checkpoint_sha256 != expected_sha256:
            raise ValueError("frozen source checkpoint hash mismatch")
        saved = torch.load(path, map_location="cpu", weights_only=True)
        with torch.random.fork_rng(devices=[]):
            torch.manual_seed(0)
            self.source = FeedbackOutputModel(OutputModel(saved["dimensions"]), max_refinements=2)
        self.source.load_state_dict(saved["state_dict"], strict=True)
        self.source.eval().requires_grad_(False)
        if weight_hashes(self.source) != saved["weight_sha256"]:
            raise ValueError("learned tensor state differs from source receipt")
        self.weight_sha256 = saved["weight_sha256"]["all"]
        self.owner = object()
        self.reset_work()
        self._hooks = [layer.register_forward_hook(self._meter(name))
                       for name, layer in self.source.named_modules() if isinstance(layer, nn.Linear)]
        profile = self.source.cost_profile()
        if (profile["anchor"] != 512 or profile["refinement"] != REFINE_COST
                or tuple(profile["decoder"][m] for m in MODALITIES) != DECODER_COSTS):
            raise ValueError("registered dense Linear cost profile mismatch")

    def _meter(self, name):
        def hook(layer, inputs, output):
            rows = inputs[0].numel() // layer.in_features
            self._work["linear_macs"] += rows * layer.in_features * layer.out_features
            counts = self._work["linear_layer_examples"]
            counts[name] = counts.get(name, 0) + rows
        return hook

    def reset_work(self):
        self._work = {"linear_macs": 0, "linear_layer_examples": {}}

    def work_receipt(self):
        return deepcopy(self._work)

    @staticmethod
    def _tensor(value, shape):
        if isinstance(value, np.ndarray) and not value.flags.writeable:
            value = value.copy()
        tensor = torch.as_tensor(value)
        if tensor.dtype == torch.bool or tensor.is_complex():
            raise ValueError("real numeric tensor required")
        tensor = tensor.to(dtype=torch.float32, device="cpu")
        if tuple(tensor.shape) != tuple(shape) or not bool(torch.isfinite(tensor).all()):
            raise ValueError("finite tensor with the registered shape required")
        return tensor.clone()

    def anchor_tensor(self, q):
        return self.source.anchor_tensor(q)

    def refine_tensor(self, q, latents, modality, innovation, anchor):
        if type(modality) is not int or not 0 <= modality < 4:
            raise ValueError("one registered modality index required")
        current = self._tensor(latents, (len(q), 4, 64))
        current[:, modality] = self.source.refine_tensor(
            q, current[:, modality], innovation, anchor=anchor)
        return current

    def decode_tensor(self, latents):
        current = self._tensor(latents, (len(latents), 4, 64))
        outputs = {}
        for index, name in enumerate(MODALITIES):
            outputs.update(self.source.decode_tensor(current[:, index], (name,)))
        return outputs

    @torch.inference_mode()
    def initialize(self, raw_text, initial_noise):
        if len(raw_text) != 1:
            raise ValueError("one causal stream per initialization required")
        noise = self._tensor(initial_noise, (1, 4, 64))
        before = self._work["linear_macs"]
        condition = int(encode(self.source.base, "text", raw_text)[0][0])
        q = torch.eye(8)[[condition]]
        anchor = self.anchor_tensor(q)
        latents = anchor[:, None, :] + noise
        if self._work["linear_macs"] - before != INIT_COST:
            raise AssertionError("actual encoder and anchor work differs from INIT charge")
        return AllocationState(q, anchor, latents, noise, self.owner, _Ledger())

    def _check(self, state, require_feedback=False):
        if not isinstance(state, AllocationState) or state._owner is not self.owner:
            raise ValueError("state belongs to another generator")
        if state._ledger.sealed or state.version != state._ledger.version:
            raise ValueError("sealed or stale generation snapshot")
        if require_feedback and state._ledger.feedback_version != state.version:
            raise ValueError("current feedback must precede an action")

    def feedback(self, state):
        self._check(state)
        state._ledger.feedback_version = state.version
        state._ledger.feedback_events += 1
        latents = state._latents.clone()
        hashes = [tensor_hash(latents[:, index]) for index in range(4)]
        return {"q": state._q.clone(), "condition": int(state._q.argmax(1)[0]),
                "latents": latents, "latent_hashes": hashes, "joint_hash": joint_hash(hashes),
                "q_hash": tensor_hash(state._q), "depth": sum(state._ledger.counts),
                "residual_rms": (latents - state._anchor[:, None]).square().mean(2).sqrt(),
                "last_update_rms": state._last_update.square().mean(2).sqrt(),
                **state.receipt}

    @torch.inference_mode()
    def refine_step(self, state, modality, innovation):
        self._check(state, require_feedback=True)
        if type(modality) is not int or not 0 <= modality < 4:
            raise ValueError("registered modality required")
        if sum(state._ledger.counts) >= 2 or state._ledger.spent + REFINE_COST + EMIT_COST > BUDGET:
            raise ValueError("refinement exceeds horizon or reserved emission budget")
        noise = self._tensor(innovation, (1, 64))
        before = self._work["linear_macs"]
        new = self.refine_tensor(state._q, state._latents, modality, noise, state._anchor)
        if self._work["linear_macs"] - before != REFINE_COST:
            raise AssertionError("actual refinement work differs from charge")
        state._ledger.spent += REFINE_COST
        state._ledger.counts[modality] += 1
        state._ledger.version += 1
        return AllocationState(state._q, state._anchor, new, new - state._latents,
                               self.owner, state._ledger, state._ledger.version)

    @torch.inference_mode()
    def emit(self, state):
        self._check(state, require_feedback=True)
        if state._ledger.spent + EMIT_COST > BUDGET:
            raise ValueError("complete emission is infeasible")
        before = self._work["linear_macs"]
        outputs = self.decode_tensor(state._latents)
        if self._work["linear_macs"] - before != EMIT_COST:
            raise AssertionError("actual four-decoder work differs from emission charge")
        state._ledger.spent += EMIT_COST
        state._ledger.version += 1
        state._ledger.sealed = True
        return outputs
