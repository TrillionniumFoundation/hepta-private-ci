"""Shadow-only shared Hepta latent Stem prototypes and lightweight Cell Heads.

The 150M/300M models are ARCHITECTURES, not trained or qualified weights.
The small CPU smoke proves only Python-level single Encoder invocation/fan-out;
it does not attest kernel-level physical forward count or end-to-end production cost.
"""
from __future__ import annotations

from dataclasses import dataclass
from itertools import islice
import re
from typing import Iterable

import torch
from torch import nn

from feature_bundle import FeatureBundleV1, FeatureIdentityV1

MAX_CELL_FANOUT = 4096
MAX_STEM_BATCH = 8
MAX_CELL_BATCH_ELEMENTS = 2_097_152


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
        if (not isinstance(shared, torch.Tensor) or
                not isinstance(state, torch.Tensor) or shared.ndim != 2 or
                shared.shape[1] != self.width or
                state.shape != (shared.shape[0], self.state_width) or
                shared.dtype != state.dtype or shared.device != state.device or
                not shared.is_floating_point()):
            raise StemContractError("Cell feature/local-state ABI mismatch")
        if not torch.isfinite(shared).all() or not torch.isfinite(state).all():
            raise StemContractError("nonfinite Cell inputs")
        gate = torch.sigmoid(self.gate(torch.cat((shared, state), dim=-1)))
        adapted = shared + gate * self.up(torch.nn.functional.gelu(self.down(shared)))
        result = {
            "task_logits": self.task_head(adapted),
            "action_logits": self.action_head(adapted),
            "value": torch.tanh(self.value_head(adapted)),
            "uncertainty": torch.sigmoid(self.uncertainty_head(adapted)),
            "gate": gate,
        }
        if not all(bool(torch.isfinite(value).all()) for value in result.values()):
            raise StemContractError("nonfinite Cell advisory output")
        return result


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
        if (not isinstance(slots, torch.Tensor) or slots.ndim != 3 or
                slots.shape[-1] != self.width or
                not 1 <= slots.shape[0] <= MAX_STEM_BATCH or
                not 1 <= slots.shape[1] <= 128 or
                not slots.is_floating_point() or not torch.isfinite(slots).all()):
            raise StemContractError("incompatible, nonfinite or over-budget slots")
        prepared = self._prepare_requests(slots, requests)
        # User hooks may mutate arguments; snapshots protect both the source
        # slots and every Cell's local state before the Encoder is invoked.
        frozen_slots = slots.detach().clone()
        with torch.inference_mode():
            tokens = self.encoder(frozen_slots)
            self.owner_forward_calls += 1
            if (not isinstance(tokens, torch.Tensor) or tokens.shape != slots.shape
                    or tokens.device != slots.device or tokens.dtype != slots.dtype
                    or not bool(torch.isfinite(tokens).all())):
                raise StemContractError("invalid shared Encoder output")
            feature = tokens.mean(dim=1)
            results, copies = self._evaluate_heads(feature, prepared)
        copies["source_snapshot_bytes"] = frozen_slots.numel() * frozen_slots.element_size()
        copies["global_summary_bytes"] = feature.numel() * feature.element_size()
        return self._receipt(results, encoder_calls=1, copies=copies)

    def evaluate_bundle(self, bundle: FeatureBundleV1,
                        requests: Iterable[CellRequest], *,
                        expected_identity: FeatureIdentityV1) -> dict:
        """Fan out real precomputed features without a second Encoder call.

        The owner must supply its selected full identity, including processing
        profile and scope. A checkpoint hash alone is insufficient for reuse.
        """
        if (type(bundle) is not FeatureBundleV1
                or type(expected_identity) is not FeatureIdentityV1
                or expected_identity.encoder_sha256 != self.encoder_sha256
                or expected_identity.generation != self.generation):
            raise StemContractError("feature bundle owner identity mismatch")
        bundle.require_identity(expected_identity)
        feature = bundle.read_global()
        if feature.shape[1] != self.width:
            raise StemContractError("feature bundle width mismatch")
        prepared = self._prepare_requests(feature, requests)
        with torch.inference_mode():
            results, copies = self._evaluate_heads(feature, prepared)
        bundle.verify_integrity()
        copies["source_snapshot_bytes"] = feature.numel() * feature.element_size()
        copies["global_summary_bytes"] = 0  # already computed by the source backend
        return {**self._receipt(results, encoder_calls=0, copies=copies),
                "feature_bundle_sha256": bundle.bundle_digest,
                "source_record_digests": list(bundle.source_record_digests),
                "used_precomputed_features": True}

    def _prepare_requests(self, features, requests):
        try:
            requests = list(islice(iter(requests), MAX_CELL_FANOUT + 1))
        except TypeError as exc:
            raise StemContractError("Cell requests must be iterable") from exc
        if not 1 <= len(requests) <= MAX_CELL_FANOUT:
            raise StemContractError("empty or over-budget Cell fan-out")
        ids: set[str] = set()
        prepared = []
        state_elements = output_elements = 0
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
                    or req.local_state.shape != (features.shape[0], req.head.state_width)
                    or req.local_state.device != features.device
                    or req.local_state.dtype != features.dtype
                    or not torch.isfinite(req.local_state).all()):
                raise StemContractError("Cell local state invalid before Stem execution")
            if any(p.device != features.device or p.dtype != features.dtype or
                   not bool(torch.isfinite(p).all()) for p in req.head.parameters()):
                raise StemContractError("Cell Head parameters invalid before Stem execution")
            state_elements += req.local_state.numel()
            output_elements += features.shape[0] * (req.head.task_head.out_features
                                                   + req.head.action_head.out_features + 3)
            if max(state_elements, output_elements) > MAX_CELL_BATCH_ELEMENTS:
                raise StemContractError("combined Cell state/output budget exceeded")
            ids.add(req.cell_id)
            prepared.append((req, req.local_state.detach().clone()))
        return prepared

    def _evaluate_heads(self, feature, prepared):
        results = []
        copies = {"accounting_kind": "tensor-payload-bytes-not-observed-peak",
                  "local_state_snapshot_bytes": 0, "head_input_scratch_bytes": 0,
                  "head_output_snapshot_bytes": 0}
        for req, state in prepared:
            # Sequential scratch copies are short lived; the shared source
            # remains one snapshot even when an individual Head mutates input.
            prediction = req.head(feature.clone(), state.clone())
            state_bytes = state.numel() * state.element_size()
            copies["local_state_snapshot_bytes"] += state_bytes
            copies["head_input_scratch_bytes"] += feature.numel() * feature.element_size() + state_bytes
            widths = {"task_logits": req.head.task_head.out_features,
                      "action_logits": req.head.action_head.out_features,
                      "value": 1, "uncertainty": 1, "gate": 1}
            if (not isinstance(prediction, dict) or set(prediction) != set(widths)
                    or any(not isinstance(prediction[k], torch.Tensor)
                           or prediction[k].shape != (feature.shape[0], width)
                           or prediction[k].dtype != feature.dtype
                           or prediction[k].device != feature.device
                           or not bool(torch.isfinite(prediction[k]).all())
                           for k, width in widths.items())):
                raise StemContractError("invalid Cell advisory after module hooks")
            results.append({"cell_id": req.cell_id,
                            "memory_digest": req.external_memory_digest,
                            "posture": "DENY_ALL",
                            "advisory": {k: v.detach().clone() for k, v in prediction.items()}})
            copies["head_output_snapshot_bytes"] += sum(v.numel() * v.element_size()
                                                          for v in prediction.values())
        return results, copies

    def _receipt(self, results, *, encoder_calls, copies):
        return {
            "mode": "SHADOW_ONLY", "authority": "DENY_ALL",
            "production_activation_allowed": False,
            "encoder_digest": self.encoder_sha256,
            "generation": self.generation,
            "owner_forward_calls_for_this_batch": encoder_calls,
            "physical_backend_forward_calls": None,
            "trained_checkpoint_verified": False,
            "performance_qualified": False,
            "copy_accounting": copies,
            "cell_results": results,
        }
