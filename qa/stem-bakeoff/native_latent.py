"""Shadow-only shared Hepta latent Stem prototypes and lightweight Cell Heads.

The 150M/300M models are ARCHITECTURES, not trained or qualified weights.
The small CPU smoke proves only Python-level single Encoder invocation/fan-out;
it does not attest kernel-level physical forward count or end-to-end production cost.
"""
from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Iterable

import torch
from torch import nn


@dataclass(frozen=True)
class StemSpec:
    name: str
    width: int
    layers: int
    heads: int
    ff_multiplier: int = 4


NATIVE_SPECS = {
    "hepta_latent_150m": StemSpec("hepta_latent_150m", 768, 21, 12),
    "hepta_latent_300m": StemSpec("hepta_latent_300m", 1024, 24, 16),
}


class StemContractError(ValueError):
    pass


def build_encoder(spec: StemSpec, *, device: str = "meta",
                  trainable: bool = False) -> nn.Module:
    """Build a frozen bidirectional slot Encoder, with no checkpoint claim.

    The default meta device allows exact parameter counting without allocating
    150M/300M weights; real execution requires actual trained weight provenance.
    """
    if (spec.width <= 0 or spec.heads <= 0 or spec.width % spec.heads != 0 or
            spec.layers <= 0 or spec.ff_multiplier < 2):
        raise StemContractError("invalid latent specification")
    block = nn.TransformerEncoderLayer(
        d_model=spec.width,
        nhead=spec.heads,
        dim_feedforward=spec.ff_multiplier * spec.width,
        dropout=0.0,
        activation="gelu",
        batch_first=True,
        norm_first=True,
        device=device,
    )
    encoder = nn.TransformerEncoder(block, num_layers=spec.layers,
                                    enable_nested_tensor=False)
    if type(trainable) is not bool:
        raise StemContractError("offline trainable must be an explicit boolean")
    encoder.requires_grad_(trainable)
    encoder.train(trainable)
    return encoder


def parameter_count(spec: StemSpec) -> int:
    return sum(p.numel() for p in build_encoder(spec).parameters())


class LightCellHead(nn.Module):
    """One Cell's bounded Gate/low-rank Adapter/Task-Action-Value heads.

    Local State is passed in explicitly. No Encoder, optimizer, durable Memory
    or authorization token is allocated by this class.
    """
    def __init__(self, width: int, *, state_width: int = 8,
                 adapter_rank: int = 4, task_count: int = 3,
                 action_count: int = 4):
        super().__init__()
        if not (0 < adapter_rank <= 16 and 0 < state_width <= 64 and
                0 < task_count <= 256 and 0 < action_count <= 256 and width > 0):
            raise StemContractError("invalid lightweight Cell shape")
        self.width = width
        self.state_width = state_width
        self.gate = nn.Linear(width + state_width, 1)
        self.down = nn.Linear(width, adapter_rank, bias=False)
        self.up = nn.Linear(adapter_rank, width, bias=False)
        nn.init.zeros_(self.up.weight)  # exact zero-delta parity before learning
        self.task_head = nn.Linear(width, task_count)
        self.action_head = nn.Linear(width, action_count)
        self.value_head = nn.Linear(width, 1)
        self.uncertainty_head = nn.Linear(width, 1)

    def forward(self, shared: torch.Tensor, state: torch.Tensor) -> dict:
        if (shared.ndim != 2 or shared.shape[1] != self.width or
                state.shape != (shared.shape[0], self.state_width)):
            raise StemContractError("Cell feature/local-state ABI mismatch")
        if not torch.isfinite(shared).all() or not torch.isfinite(state).all():
            raise StemContractError("nonfinite Cell inputs")
        gate = torch.sigmoid(self.gate(torch.cat((shared, state), dim=-1)))
        adapted = shared + gate * self.up(torch.nn.functional.gelu(self.down(shared)))
        return {
            "task_logits": self.task_head(adapted),
            "action_logits": self.action_head(adapted),
            "value": torch.tanh(self.value_head(adapted)),
            "uncertainty": torch.sigmoid(self.uncertainty_head(adapted)),
            "gate": gate,
        }


@dataclass(frozen=True)
class CellRequest:
    cell_id: str
    generation: int
    head: LightCellHead
    local_state: torch.Tensor
    external_memory_digest: str


class SharedStemServer:
    """Qualification-only one-owner call, N lightweight read-only Cell heads."""
    def __init__(self, encoder: nn.Module, *, generation: int, width: int,
                 encoder_sha256: str):
        if (type(generation) is not int or generation < 1 or width <= 0 or
                re.fullmatch(r"[0-9a-f]{64}", encoder_sha256) is None):
            raise StemContractError("unbound Stem generation or digest")
        if any(p.requires_grad for p in encoder.parameters()):
            raise StemContractError("shared Stem must be frozen")
        self.encoder = encoder.eval()
        self.generation = generation
        self.width = width
        self.encoder_sha256 = encoder_sha256
        self.owner_forward_calls = 0

    def evaluate(self, slots: torch.Tensor,
                 requests: Iterable[CellRequest]) -> dict:
        requests = list(requests)
        if not (requests and slots.ndim == 3 and slots.shape[-1] == self.width):
            raise StemContractError("empty Cell set or incompatible slots")
        if not 1 <= slots.shape[1] <= 128 or not torch.isfinite(slots).all():
            raise StemContractError("bad slot budget/nonfinite input")
        ids: set[str] = set()
        for req in requests:
            if (not isinstance(req, CellRequest) or not isinstance(req.cell_id, str)
                    or not re.fullmatch(r"[a-zA-Z0-9_.:-]{1,128}", req.cell_id)
                    or req.cell_id in ids or req.generation != self.generation
                    or type(req.head) is not LightCellHead
                    or req.head.width != self.width
                    or not isinstance(req.external_memory_digest, str)
                    or re.fullmatch(r"[0-9a-f]{64}", req.external_memory_digest) is None):
                raise StemContractError("Cell id/generation/head/memory binding mismatch")
            if (not isinstance(req.local_state, torch.Tensor)
                    or req.local_state.shape != (slots.shape[0], req.head.state_width)
                    or req.local_state.device != slots.device
                    or not torch.isfinite(req.local_state).all()):
                raise StemContractError("Cell local state invalid before Stem execution")
            ids.add(req.cell_id)
        with torch.inference_mode():
            # Exactly one Python Encoder owner call, regardless of Cell count.
            tokens = self.encoder(slots)
            self.owner_forward_calls += 1
            if tokens.shape != slots.shape or not torch.isfinite(tokens).all():
                raise StemContractError("invalid shared Encoder output")
            feature = tokens.mean(dim=1)
            results = []
            for req in requests:
                prediction = req.head(feature, req.local_state)
                results.append({"cell_id": req.cell_id,
                                "memory_digest": req.external_memory_digest,
                                "posture": "DENY_ALL", "advisory": prediction})
        return {
            "mode": "SHADOW_ONLY", "authority": "DENY_ALL",
            "production_activation_allowed": False,
            "encoder_digest": self.encoder_sha256,
            "generation": self.generation,
            "owner_forward_calls_for_this_batch": 1,
            "physical_backend_forward_calls": None,
            "trained_checkpoint_verified": False,
            "performance_qualified": False,
            "cell_results": results,
        }
