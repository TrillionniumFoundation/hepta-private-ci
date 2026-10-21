"""Shared differentiable latent slots from scoped frozen-teacher outputs.

Research only. Accepts already-computed features, never downloads weights and
never authenticates model origin from a caller-supplied digest. Modality towers
are shared outside Neuron Cells; no per-Cell model or memory is created here.
"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
import hashlib
import json
import math
import re
from typing import Mapping

import torch
from torch import nn

ALLOWED_MODALITIES = ("text", "image", "audio", "video", "ui_event")
TEMPORAL_MODALITIES = frozenset(("audio", "video", "ui_event"))
SHA256 = re.compile(r"[0-9a-f]{64}\Z")
MAX_BRIDGE_BATCH = 8
MAX_BRIDGE_ELEMENTS = 2_097_152  # bounded in-memory custody before projection


def _tensor_bytes_sha256(value: torch.Tensor) -> str:
    """Digest actual detached bytes, including BF16 without NumPy BF16 casting.

    Caller-supplied source hashes alone cannot bind a changed feature/timestamp
    tensor. This is local byte integrity, NOT independent upstream attestation.
    Shape and dtype are independently included in the canonical manifest.
    """
    payload = value.detach().contiguous().to(device="cpu").view(torch.uint8)
    return hashlib.sha256(payload.numpy().tobytes()).hexdigest()


class LatentBridgeError(ValueError):
    pass


@dataclass(frozen=True)
class LatentSlots:
    slots: torch.Tensor
    global_feature: torch.Tensor
    missing_mask: tuple[bool, ...]
    source_manifest_digest: str
    generation: int
    authority: str = "DENY_ALL"
    production_activation_allowed: bool = False


class MultimodalSlotizer(nn.Module):
    """Trainable shared modality projectors + cross-attention slot bottleneck.

    Pooled teacher vectors [batch,width] are treated as ONE token. This does
    not invent lost visual regions, audio frames or model reasoning tokens.
    """
    def __init__(self, input_widths: Mapping[str, int], *, latent_width: int,
                 slots: int = 16, heads: int = 4, max_tokens: int = 256):
        super().__init__()
        if (not isinstance(input_widths, dict) or not input_widths or
                any(m not in ALLOWED_MODALITIES or type(d) is not int or not 0 < d <= 4096
                    for m, d in input_widths.items()) or
                type(latent_width) is not int or not 8 <= latent_width <= 4096 or
                type(slots) is not int or not 1 <= slots <= 128 or
                type(heads) is not int or heads < 1 or latent_width % heads or
                type(max_tokens) is not int or not 1 <= max_tokens <= 4096):
            raise LatentBridgeError("invalid shared modality registry or slot budget")
        self.input_widths = dict(input_widths)
        self.latent_width = latent_width
        self.slots = slots
        self.max_tokens = max_tokens
        self.projectors = nn.ModuleDict({m: nn.Linear(d, latent_width)
                                         for m, d in self.input_widths.items()})
        self.tags = nn.ParameterDict({m: nn.Parameter(torch.zeros(latent_width))
                                      for m in self.input_widths})
        self.queries = nn.Parameter(torch.randn(slots, latent_width) * 0.02)
        self.cross_attention = nn.MultiheadAttention(latent_width, heads,
                                                       batch_first=True, dropout=0.0)
        self.norm = nn.LayerNorm(latent_width)

    def forward(self, features: Mapping[str, torch.Tensor], *,
                source_digests: Mapping[str, str], generation: int,
                timestamps: Mapping[str, torch.Tensor] | None = None) -> LatentSlots:
        if (not isinstance(features, dict) or not features or
                not isinstance(source_digests, dict) or
                set(source_digests) != set(features) or
                type(generation) is not int or generation < 1 or
                not set(features).issubset(self.input_widths)):
            raise LatentBridgeError("unregistered/cross-generation modality inputs")
        timestamps = {} if timestamps is None else timestamps
        if not isinstance(timestamps, dict) or not set(timestamps).issubset(features):
            raise LatentBridgeError("unbound temporal tags")
        for modality in features:
            if modality in TEMPORAL_MODALITIES and modality not in timestamps:
                raise LatentBridgeError("temporal modality requires ordered timestamps")
            if not isinstance(source_digests[modality], str) or not SHA256.fullmatch(source_digests[modality]):
                raise LatentBridgeError("invalid source digest")
        batch = None
        device = None
        dtype = None
        total_tokens = 0
        total_elements = 0
        # Capture every modality before running any trainable projector hook.
        # A previous projector must not rewrite a later modality's input,
        # timestamp, declared digest or presence metadata.
        snapshots = []
        parts = []
        manifest = []
        present = frozenset(features)
        input_registry = list(self.input_widths.items())
        for modality in ALLOWED_MODALITIES:
            if modality not in features:
                continue
            value = features[modality]
            if not isinstance(value, torch.Tensor):
                raise LatentBridgeError("modality features must be tensors")
            if value.ndim == 2:  # EmbeddingGemma 2 pooled output = single slot
                value = value.unsqueeze(1)
            if (value.ndim != 3 or value.shape[-1] != self.input_widths[modality]
                    or not 1 <= value.shape[0] <= MAX_BRIDGE_BATCH
                    or value.shape[1] < 1 or value.shape[1] > self.max_tokens
                    or not value.is_floating_point() or not torch.isfinite(value).all()):
                raise LatentBridgeError("invalid/nonfinite latent token dimensions")
            if batch is None:
                batch, device, dtype = value.shape[0], value.device, value.dtype
            elif batch != value.shape[0] or device != value.device or dtype != value.dtype:
                raise LatentBridgeError("cross-modal batch/device/dtype mismatch")
            total_tokens += value.shape[1]
            total_elements += value.numel()
            if total_tokens > self.max_tokens or total_elements > MAX_BRIDGE_ELEMENTS:
                raise LatentBridgeError("combined modality token/element budget exceeded")
            t = timestamps.get(modality)
            if t is not None:
                if (not isinstance(t, torch.Tensor) or t.shape != value.shape[:2]
                        or t.device != value.device or not torch.isfinite(t).all()
                        or torch.any(t < 0) or torch.any(t > 1e9)
                        or torch.any(t[:, 1:] < t[:, :-1])):
                    raise LatentBridgeError("invalid unordered temporal spans")
            # One source snapshot feeds BOTH the projector and provenance hash.
            # Detach keeps the teacher frozen; clone breaks caller-owned aliasing.
            # Hash before invoking any projectors/hooks that can mutate upstream
            # caller state. The extra projector clone protects the sealed copy.
            frozen_value = value.detach().clone()
            frozen_t = t.detach().clone() if t is not None else None
            if not torch.isfinite(frozen_value).all():
                raise LatentBridgeError("nonfinite modality snapshot")
            if frozen_t is not None and (
                    not torch.isfinite(frozen_t).all()
                    or torch.any(frozen_t < 0) or torch.any(frozen_t > 1e9)
                    or torch.any(frozen_t[:, 1:] < frozen_t[:, :-1])):
                raise LatentBridgeError("invalid temporal snapshot")
            feature_digest = _tensor_bytes_sha256(frozen_value)
            time_digest = _tensor_bytes_sha256(frozen_t) if frozen_t is not None else None
            snapshots.append((modality, frozen_value, frozen_t,
                              feature_digest, time_digest, source_digests[modality]))
        if not snapshots:
            raise LatentBridgeError("no present modalities")
        # Only now permit trainable/user-hookable forward calls. The projected
        # tensor is a second clone, so a projector cannot alter sealed bytes.
        for modality, frozen_value, frozen_t, feature_digest, time_digest, declared_digest in snapshots:
            projected = self.projectors[modality](frozen_value.clone()) + self.tags[modality]
            if frozen_t is not None:
                # Minimal bounded temporal phase. More expressive time adapters
                # are an independent future bake-off arm.
                projected = projected + 0.01 * torch.sin(
                    frozen_t.to(dtype=projected.dtype).unsqueeze(-1) / 1000.0)
            parts.append(projected)
            manifest.append({
                "modality": modality,
                "declared_source_sha256": declared_digest,
                "shape": list(frozen_value.shape),
                "dtype": str(frozen_value.dtype),
                "feature_bytes_sha256": feature_digest,
                "timestamps": None if frozen_t is None else {
                    "shape": list(frozen_t.shape),
                    "dtype": str(frozen_t.dtype),
                    "bytes_sha256": time_digest,
                },
            })
        tokens = torch.cat(parts, dim=1)
        queries = self.queries.unsqueeze(0).expand(batch, -1, -1)
        attended, _ = self.cross_attention(queries, tokens, tokens, need_weights=False)
        slot_features = self.norm(queries + attended)
        if not torch.isfinite(slot_features).all():
            raise LatentBridgeError("nonfinite shared slots")
        statement = {"schema": "hepta.multimodal-slot-lineage.v2",
                     "generation": generation, "sources": manifest,
                     "registered": input_registry,
                     "missing": [m not in present for m in ALLOWED_MODALITIES]}
        manifest_digest = hashlib.sha256(json.dumps(statement, sort_keys=True,
                                                     separators=(",", ":")).encode()).hexdigest()
        return LatentSlots(slots=slot_features,
                           global_feature=slot_features.mean(dim=1),
                           missing_mask=tuple(m not in present for m in ALLOWED_MODALITIES),
                           source_manifest_digest=manifest_digest,
                           generation=generation)


def _verify_optimizer_storage_isolation(tensors: list[torch.Tensor]) -> None:
    """Reject overlapping physical parameter OR optimizer-state tensor storage.

    Python Parameter identity is not tensor ownership: nn.Parameter(other.detach())
    creates a new ID while sharing bytes. Optimizer momentum/Adam moments may
    likewise alias weights or one another and cause silent finite corruption.
    Conservatively reject any shared allocation, including disjoint views.
    """
    spans = []
    for tensor in tensors:
        if tensor.layout != torch.strided or tensor.numel() == 0:
            raise LatentBridgeError("unsupported offline optimizer tensor storage")
        storage = tensor.untyped_storage()
        address, size = storage.data_ptr(), storage.nbytes()
        if address <= 0 or size <= 0:
            raise LatentBridgeError("unsupported offline optimizer tensor storage")
        spans.append((str(tensor.device), address, address + size))
    spans.sort()
    for (left_device, _, left_end), (right_device, right_start, _) in zip(
            spans, spans[1:]):
        if left_device == right_device and right_start < left_end:
            raise LatentBridgeError("overlapping offline optimizer parameter/storage")


def _verify_optimizer_ownership(student: nn.Module, slotizer: MultimodalSlotizer,
                                optimizer: torch.optim.Optimizer) -> tuple[int, ...]:
    """Prevent an offline Student step from updating another Cell or teacher."""
    if not isinstance(optimizer, torch.optim.Optimizer):
        raise LatentBridgeError("offline distillation requires a torch optimizer")
    student_params = tuple(student.parameters())
    slotizer_params = tuple(slotizer.parameters())
    student_ids = {id(p) for p in student_params}
    slotizer_ids = {id(p) for p in slotizer_params}
    if student_ids.intersection(slotizer_ids):
        raise LatentBridgeError("student and slotizer parameter ownership overlaps")
    owned = {id(p) for p in (*student_params, *slotizer_params) if p.requires_grad}
    parameters = [p for group in optimizer.param_groups for p in group["params"]]
    ids = tuple(id(p) for p in parameters)
    if (not ids or len(set(ids)) != len(ids)
            or any(not isinstance(p, nn.Parameter) or not p.requires_grad
                   or not p.is_floating_point() or id(p) not in owned
                   for p in parameters)):
        raise LatentBridgeError("optimizer contains foreign, frozen or duplicate parameters")
    # An optimizer that silently omits trainable Student weights can return a
    # successful "training" receipt after updating only Slotizer parameters.
    # Frozen weights must opt out explicitly via requires_grad=False.
    if set(ids) != owned:
        raise LatentBridgeError("optimizer omits trainable Student/Slotizer parameters")
    # Parameter object IDs alone do not prove exclusive ownership of bytes.
    # This is rechecked after forward hooks before any physical weight step.
    _verify_optimizer_storage_isolation(parameters)
    return ids


def _verify_optimizer_step_safety(optimizer: torch.optim.Optimizer) -> tuple:
    """Fail closed on unsafe optimizer settings and nonfinite existing state.

    This deliberately supports only stock SGD/AdamW in offline research: an
    arbitrary Optimizer subclass can run uncontrolled step() code. A finite
    backward gradient alone does not make the learning rate or momentum safe.
    """
    if type(optimizer) not in (torch.optim.SGD, torch.optim.AdamW):
        raise LatentBridgeError("unsupported offline optimizer type")

    def checked(name: str, value: object, *, positive: bool = False) -> None:
        if type(value) not in (int, float):
            raise LatentBridgeError("unsafe offline optimizer hyperparameter: " + name)
        try:
            finite = math.isfinite(value)
        except (OverflowError, ValueError):
            finite = False
        if not finite or value < 0 or value > 1 or (positive and value == 0):
            raise LatentBridgeError("unsafe offline optimizer hyperparameter: " + name)

    for group in optimizer.param_groups:
        checked("lr", group.get("lr"), positive=True)
        checked("weight_decay", group.get("weight_decay", 0))
        if (group.get("maximize", False) is not False
                or group.get("differentiable", False) is not False):
            raise LatentBridgeError("unsupported offline optimizer execution flags")
        if type(optimizer) is torch.optim.SGD:
            checked("momentum", group.get("momentum", 0))
            checked("dampening", group.get("dampening", 0))
            if group.get("momentum", 0) >= 1:
                raise LatentBridgeError("unsafe offline optimizer hyperparameter: momentum")
        else:
            betas = group.get("betas")
            if not isinstance(betas, tuple) or len(betas) != 2:
                raise LatentBridgeError("unsafe offline optimizer hyperparameter: betas")
            checked("beta1", betas[0])
            checked("beta2", betas[1])
            if betas[0] >= 1 or betas[1] >= 1:
                raise LatentBridgeError("unsafe offline optimizer hyperparameter: betas")
            checked("eps", group.get("eps"), positive=True)

    owned_ids = {id(p) for group in optimizer.param_groups for p in group["params"]}
    allowed_state = ({"momentum_buffer"} if type(optimizer) is torch.optim.SGD
                     else {"step", "exp_avg", "exp_avg_sq", "max_exp_avg_sq"})
    for parameter, state in optimizer.state.items():
        if id(parameter) not in owned_ids or not isinstance(state, dict):
            raise LatentBridgeError("unowned or malformed offline optimizer state")
        for key, value in state.items():
            if key not in allowed_state:
                raise LatentBridgeError("unsupported offline optimizer state")
            if isinstance(value, torch.Tensor):
                if (value.layout != torch.strided
                        or not bool(torch.isfinite(value).all())):
                    raise LatentBridgeError("nonfinite or unsupported offline optimizer state")
            elif type(value) in (int, float):
                try:
                    finite = math.isfinite(value)
                except (OverflowError, ValueError):
                    finite = False
                if not finite:
                    raise LatentBridgeError("nonfinite offline optimizer state")
            else:
                raise LatentBridgeError("unsupported offline optimizer state value")

    # Finiteness alone cannot prove optimizer-state custody. A finite SGD
    # momentum tensor can alias its weight, silently reversing the update.
    # Also reject malformed moment dimensions and mutually aliased Adam slots.
    owned_tensors = [p for group in optimizer.param_groups for p in group["params"]]
    for parameter, state in optimizer.state.items():
        for key, value in state.items():
            if not isinstance(value, torch.Tensor):
                continue
            if key == "step":
                if value.numel() != 1:
                    raise LatentBridgeError("invalid offline optimizer step state shape")
            elif (value.shape != parameter.shape or value.dtype != parameter.dtype
                  or value.device != parameter.device):
                raise LatentBridgeError("offline optimizer state shape/dtype/device mismatch")
            owned_tensors.append(value)
    _verify_optimizer_storage_isolation(owned_tensors)

    # Snapshot the complete non-parameter group settings: a projector/Student
    # hook must not silently change a finite learning rate or optimizer mode.
    return tuple(tuple((key, repr(value)) for key, value in sorted(group.items())
                       if key != "params") for group in optimizer.param_groups)


def _verify_optimizer_gradients(student: nn.Module,
                                optimizer: torch.optim.Optimizer) -> None:
    """Reject nonfinite backward gradients before *any* optimizer weight update.

    Unused frozen or modality-specific parameters may have no gradients. At
    least one trainable Student parameter must have a finite gradient, so a
    nominal distillation step cannot silently train only the Slotizer.
    """
    student_ids = {id(p) for p in student.parameters() if p.requires_grad}
    saw_student_gradient = False
    for group in optimizer.param_groups:
        for parameter in group["params"]:
            gradient = parameter.grad
            if gradient is None:
                continue
            if gradient.layout == torch.strided:
                values = gradient
            elif gradient.layout == torch.sparse_coo:
                values = gradient._values()
            else:
                raise LatentBridgeError("unsupported offline optimizer gradient layout")
            if not bool(torch.isfinite(values).all()):
                raise LatentBridgeError("nonfinite offline optimizer gradient")
            if id(parameter) in student_ids:
                saw_student_gradient = True
    if not saw_student_gradient:
        raise LatentBridgeError("offline distillation produced no Student gradients")


def _guarded_offline_optimizer_step(optimizer: torch.optim.Optimizer,
                                    expected_ids: tuple[int, ...],
                                    expected_settings: tuple) -> None:
    """Rollback pre-step weights and optimizer state on an unsafe stock step.

    This isolates a research micro-step; it does not roll back forward-hook
    side effects, external I/O, or supply a production training transaction.
    """
    if ("step" in vars(optimizer)
            or optimizer._optimizer_step_pre_hooks
            or optimizer._optimizer_step_post_hooks
            or optimizer._optimizer_state_dict_pre_hooks
            or optimizer._optimizer_state_dict_post_hooks
            or optimizer._optimizer_load_state_dict_pre_hooks
            or optimizer._optimizer_load_state_dict_post_hooks):
        raise LatentBridgeError("instrumented offline optimizer step is unsupported")
    parameters = [p for group in optimizer.param_groups for p in group["params"]]
    if tuple(id(p) for p in parameters) != expected_ids:
        raise LatentBridgeError("offline optimizer ownership changed before step")
    if any(p.layout != torch.strided or not p.is_floating_point()
           or not bool(torch.isfinite(p.detach()).all()) for p in parameters):
        raise LatentBridgeError("nonfinite/unsupported pre-step offline weights")

    # The old optimizer state must be deep-copied: state_dict() alone retains
    # tensor aliases, including AdamW moments that step() overwrites in place.
    parameter_snapshot = [p.detach().clone() for p in parameters]
    state_snapshot = deepcopy(optimizer.state_dict())
    try:
        optimizer.step()
        if tuple(id(p) for group in optimizer.param_groups
                 for p in group["params"]) != expected_ids:
            raise LatentBridgeError("offline optimizer ownership changed after step")
        if any(p.layout != torch.strided or not bool(torch.isfinite(p.detach()).all())
               for p in parameters):
            raise LatentBridgeError("nonfinite post-step offline weights")
        # A finite weight update may still create infinite AdamW moments; check
        # state and scalar configuration AFTER the physical optimizer step.
        if _verify_optimizer_step_safety(optimizer) != expected_settings:
            raise LatentBridgeError("offline optimizer settings changed after step")
    except Exception as error:
        try:
            with torch.no_grad():
                for parameter, before in zip(parameters, parameter_snapshot):
                    parameter.copy_(before)
            optimizer.load_state_dict(state_snapshot)
        except Exception as restore_error:
            raise LatentBridgeError("offline optimizer rollback failed") from restore_error
        if isinstance(error, LatentBridgeError):
            raise
        raise LatentBridgeError("offline optimizer step failed; state restored") from error


def shadow_distill_step(student: nn.Module, slotizer: MultimodalSlotizer,
                        features: dict[str, torch.Tensor], source_digests: dict[str, str],
                        teacher_global: torch.Tensor, optimizer: torch.optim.Optimizer,
                        *, generation: int, timestamps: dict[str, torch.Tensor] | None = None) -> dict:
    """One offline-only MSE/cosine step, never a production Cell update.

    The caller must separately prove that teacher targets, checkpoint and
    held-out data truly originate from approved non-overlapping sources.
    """
    if not any(p.requires_grad for p in student.parameters()):
        raise LatentBridgeError("student must be explicitly trainable offline")
    # Validate optimizer owner identity before a trainable projection or Student
    # call, and recheck it after forward/backward hooks before any weight step.
    optimizer_binding = _verify_optimizer_ownership(student, slotizer, optimizer)
    optimizer_safety_binding = _verify_optimizer_step_safety(optimizer)
    # detach() alone aliases caller-owned teacher storage. Freeze the actual
    # training target before any projector/Student hooks or backward execution.
    if (not isinstance(teacher_global, torch.Tensor)
            or teacher_global.ndim != 2
            or not 1 <= teacher_global.shape[0] <= MAX_BRIDGE_BATCH
            or teacher_global.shape[1] != slotizer.latent_width
            or not teacher_global.is_floating_point()):
        raise LatentBridgeError("invalid teacher target shape or dtype")
    target = teacher_global.detach().clone()
    if not bool(torch.isfinite(target).all()):
        raise LatentBridgeError("nonfinite teacher target snapshot")
    teacher_target_sha256 = _tensor_bytes_sha256(target)
    slots = slotizer(features, source_digests=source_digests,
                     generation=generation, timestamps=timestamps)
    if _verify_optimizer_ownership(student, slotizer, optimizer) != optimizer_binding:
        raise LatentBridgeError("optimizer ownership changed during projection")
    if (target.shape != slots.global_feature.shape
            or target.device != slots.global_feature.device
            or target.dtype != slots.global_feature.dtype):
        raise LatentBridgeError("teacher target incompatible with student")
    # P18 binds source bytes, but a changed Slotizer can yield different training
    # slots with the same source/target receipt. Bind the ACTUAL differentiable
    # Student input bytes and prevent observable input mutation by Student hooks.
    student_input = slots.slots.clone()
    if (student_input.ndim != 3
            or student_input.shape != (target.shape[0], slotizer.slots, target.shape[1])
            or student_input.device != target.device
            or student_input.dtype != target.dtype
            or not bool(torch.isfinite(student_input).all())):
        raise LatentBridgeError("student input slots invalid")
    student_input_sha256 = _tensor_bytes_sha256(student_input)
    # Paired receipt v2 binds both actual input slots and teacher targets. This
    # is LOCAL integrity, not an independently signed model/data attestation.
    paired_distillation_sha256 = hashlib.sha256(json.dumps({
        "schema": "hepta.shadow-distillation-pair.v2",
        "generation": generation,
        "slot_source_manifest_sha256": slots.source_manifest_digest,
        "student_input_sha256": student_input_sha256,
        "student_input_shape": list(student_input.shape),
        "student_input_dtype": str(student_input.dtype),
        "teacher_target_sha256": teacher_target_sha256,
        "teacher_target_shape": list(target.shape),
        "teacher_target_dtype": str(target.dtype),
    }, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    optimizer.zero_grad(set_to_none=True)
    student_tokens = student(student_input)
    if _tensor_bytes_sha256(student_input) != student_input_sha256:
        raise LatentBridgeError("student input mutated after receipt")
    if (not isinstance(student_tokens, torch.Tensor)
            or student_tokens.shape != student_input.shape
            or student_tokens.dtype != target.dtype
            or student_tokens.device != target.device
            or not bool(torch.isfinite(student_tokens).all())):
        raise LatentBridgeError("student output shape/dtype/nonfinite")
    predictions = student_tokens.mean(dim=1)
    mse = torch.nn.functional.mse_loss(predictions, target)
    cosine = 1.0 - torch.nn.functional.cosine_similarity(
        predictions, target, dim=-1, eps=1e-8).mean()
    loss = mse + 0.1 * cosine
    if not torch.isfinite(loss):
        raise LatentBridgeError("nonfinite distillation loss")
    loss.backward()
    if _verify_optimizer_ownership(student, slotizer, optimizer) != optimizer_binding:
        raise LatentBridgeError("optimizer ownership changed before training step")
    # A finite forward/loss does not imply finite custom-autograd gradients.
    # The guard must run after all backward hooks, before optimizer.step().
    _verify_optimizer_gradients(student, optimizer)
    if _verify_optimizer_step_safety(optimizer) != optimizer_safety_binding:
        raise LatentBridgeError("offline optimizer configuration changed before step")
    _guarded_offline_optimizer_step(optimizer, optimizer_binding,
                                    optimizer_safety_binding)
    return {"loss": float(loss.detach()), "mse": float(mse.detach()),
            "cosine_loss": float(cosine.detach()), "generation": generation,
            "source_manifest_digest": slots.source_manifest_digest,
            "teacher_target_sha256": teacher_target_sha256,
            "student_input_sha256": student_input_sha256,
            "paired_distillation_sha256": paired_distillation_sha256,
            "training_posture": "OFFLINE_RESEARCH_ONLY", "authority": "DENY_ALL",
            "evidence_class": "UNVERIFIED_TEACHER_FEATURES",
            "checkpoint_qualified": False, "production_activation_allowed": False}
