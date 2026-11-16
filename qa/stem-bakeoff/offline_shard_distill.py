"""Offline, non-authorizing teacher-shard -> shared latent-student rehearsal.

Consumes *paired*, precomputed model-ready slots and P5 teacher features. A
caller-provided hash is a local integrity assertion, NOT an independent witness.
No network/model download, Cell adaptation, external Memory write, or promotion.
All five split checks finish before any optimizer update; only train is optimized.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
from pathlib import Path
import re
from typing import Mapping

import torch
from torch import nn
from torch.nn import functional as F

from feature_shard import read_shard, FeatureShardError
from multimodal_bridge import (
    LatentBridgeError, _guarded_offline_optimizer_step,
    _verify_optimizer_gradients, _verify_optimizer_lifecycle,
    _verify_optimizer_step_safety, _verify_optimizer_storage_isolation,
)

SPLITS = ("train", "calibration", "future_1", "future_2", "ood")
SHA256 = re.compile(r"[0-9a-f]{64}\Z")
SHA40 = re.compile(r"[0-9a-f]{40}\Z")
TEACHERS = frozenset(("embeddinggemma2_740m", "t5gemma2_encoder_270m"))
STUDENTS = frozenset(("hepta_latent_150m", "hepta_latent_300m", "hepta_shared_tiny64_v1"))


class OfflineDistillError(ValueError):
    pass


@dataclass(frozen=True)
class PairedCohort:
    """One ordered shard batch and an independent producer's slots.

    sample_digests MUST name each original source item in the same order as
    the teacher shard. The digest equality checks cannot prove this mapping;
    separate externally held input/source evidence is still required.
    """
    slots: torch.Tensor  # float32, [batch, K, student_width]
    teacher_shard: str | Path
    expected_source_sha256: str
    expected_npy_sha256: str
    expected_slot_sha256: str
    sample_digests: tuple[str, ...]


def _sha256(value: object) -> bool:
    return type(value) is str and SHA256.fullmatch(value) is not None


def _finite_tensor(value: object, dims: int) -> bool:
    return (isinstance(value, torch.Tensor) and value.ndim == dims
            and value.dtype == torch.float32 and bool(torch.isfinite(value).all()))


def _prepare(cohorts: Mapping[str, PairedCohort], *, teacher_candidate: str,
             teacher_revision: str, checkpoint_inventory_sha256: str,
             student_width: int, target_width: int):
    if (not isinstance(cohorts, dict) or set(cohorts) != set(SPLITS)
            or teacher_candidate not in TEACHERS
            or type(teacher_revision) is not str or SHA40.fullmatch(teacher_revision) is None
            or not _sha256(checkpoint_inventory_sha256)
            or type(student_width) is not int or not 8 <= student_width <= 4096
            or type(target_width) is not int or not 1 <= target_width <= 4096):
        raise OfflineDistillError("missing split, model or independently pinned input declaration")
    pairs = {}
    paired_receipts = {}
    seen_sources: set[str] = set()
    seen_batches: set[str] = set()
    seen_teacher_features: set[str] = set()
    seen_slot_bytes: set[str] = set()
    for name in SPLITS:
        cohort = cohorts[name]
        if not isinstance(cohort, PairedCohort):
            raise OfflineDistillError(f"{name}: expected a paired cohort")
        slots = cohort.slots
        if (not _finite_tensor(slots, 3) or not 1 <= slots.shape[0] <= 8
                or not 1 <= slots.shape[1] <= 128 or slots.shape[2] != student_width):
            raise OfflineDistillError(f"{name}: missing, nonfinite or unbounded input slots")
        if (not _sha256(cohort.expected_source_sha256) or
                not _sha256(cohort.expected_npy_sha256) or
                not _sha256(cohort.expected_slot_sha256) or
                cohort.expected_source_sha256 in seen_batches or
                not isinstance(cohort.sample_digests, tuple) or
                len(cohort.sample_digests) != slots.shape[0] or
                not all(_sha256(s) for s in cohort.sample_digests) or
                len(set(cohort.sample_digests)) != len(cohort.sample_digests) or
                seen_sources.intersection(cohort.sample_digests)):
            raise OfflineDistillError(f"{name}: missing/overlapping held-out source IDs")
        # Validate the bytes actually used by the model. detach() alone aliases
        # the caller's mutable tensor, so snapshot before computing its digest.
        if slots.requires_grad or slots.grad_fn is not None:
            raise OfflineDistillError(f"{name}: frozen upstream producer required")
        frozen_slots = slots.detach().clone()
        slot_sha = hashlib.sha256(
            frozen_slots.contiguous().cpu().numpy().tobytes()
        ).hexdigest()
        if slot_sha != cohort.expected_slot_sha256:
            raise OfflineDistillError(f"{name}: student source-slot digest mismatch")
        if slot_sha in seen_slot_bytes:
            raise OfflineDistillError(f"{name}: held-out slot data duplicates another split")
        seen_slot_bytes.add(slot_sha)
        seen_sources.update(cohort.sample_digests)
        seen_batches.add(cohort.expected_source_sha256)
        try:
            targets, manifest = read_shard(cohort.teacher_shard)
        except (FeatureShardError, OSError, ValueError) as exc:
            raise OfflineDistillError(f"{name}: missing or invalid teacher shard") from exc
        if (manifest.get("candidate") != teacher_candidate or
                manifest.get("revision") != teacher_revision or
                manifest.get("checkpoint_inventory_sha256") != checkpoint_inventory_sha256 or
                manifest.get("ordered_source_manifest_sha256") != cohort.expected_source_sha256 or
                manifest.get("npy_sha256") != cohort.expected_npy_sha256 or
                manifest.get("raw_feature_sha256") in seen_teacher_features or
                not _finite_tensor(targets, 2) or
                targets.shape != (slots.shape[0], target_width) or
                targets.requires_grad):
            raise OfflineDistillError(f"{name}: teacher/checkpoint/source/row binding mismatch")
        # Keep the verified cohort independent of caller-owned tensors and
        # temporary shard buffers throughout training and held-out evaluation.
        seen_teacher_features.add(manifest["raw_feature_sha256"])
        frozen_target = targets.detach().to(device=frozen_slots.device).clone()
        pairs[name] = (frozen_slots, frozen_target)
        # All measurements below refer to the same post-validation, isolated
        # snapshots used in train, calibration, future_1/future_2 and OOD.
        # These byte pins are local integrity evidence, NOT data attestation.
        paired_receipts[name] = {
            "source_manifest_sha256": manifest["ordered_source_manifest_sha256"],
            "student_slot_sha256": slot_sha,
            "teacher_feature_sha256": manifest["raw_feature_sha256"],
            "teacher_npy_sha256": manifest["npy_sha256"],
            "source_row_count": frozen_slots.shape[0],
            "student_slot_shape": list(frozen_slots.shape),
            "teacher_feature_shape": list(frozen_target.shape),
        }
    return pairs, paired_receipts


def _loss(student: nn.Module, readout: nn.Module,
          pair: tuple[torch.Tensor, torch.Tensor]) -> torch.Tensor:
    slots, target = pair
    # Some legitimate student modules mutate their input in-place. Never
    # expose the frozen verified batch to the model's forward method.
    encoded = student(slots.clone())
    if (not _finite_tensor(encoded, 3) or encoded.shape != slots.shape):
        raise OfflineDistillError("student produced incompatible/nonfinite latent slots")
    prediction = readout(encoded.mean(dim=1))
    if not _finite_tensor(prediction, 2) or prediction.shape != target.shape:
        raise OfflineDistillError("readout produced incompatible/nonfinite teacher projection")
    mse = F.mse_loss(prediction, target)
    cosine = 1 - F.cosine_similarity(prediction, target, dim=-1, eps=1e-8).mean()
    result = mse + 0.1 * cosine
    if not torch.isfinite(result):
        raise OfflineDistillError("nonfinite distillation objective")
    return result


def _check_optimizer_custody(optimizer: torch.optim.Optimizer,
                             expected_ids: tuple[int, ...],
                             expected_settings: tuple,
                             trainable: list[nn.Parameter]) -> None:
    """Revalidate ownership, physical backing and lifecycle after model hooks.

    The same research-only stock optimizer policy is used by the direct
    multimodal Slotizer path. Neither entry point may bypass that boundary.
    """
    try:
        _verify_optimizer_lifecycle(optimizer)
        observed_ids = tuple(id(p) for group in optimizer.param_groups
                             for p in group["params"])
        if observed_ids != expected_ids:
            raise OfflineDistillError("offline optimizer parameter custody changed")
        _verify_optimizer_storage_isolation(trainable)
        if _verify_optimizer_step_safety(optimizer) != expected_settings:
            raise OfflineDistillError("offline optimizer settings/state changed")
    except LatentBridgeError as exc:
        raise OfflineDistillError("unsafe offline optimizer custody") from exc


def run_offline_distillation(*, student: nn.Module, readout: nn.Module,
                             optimizer: torch.optim.Optimizer,
                             cohorts: Mapping[str, PairedCohort],
                             student_candidate: str, teacher_candidate: str,
                             teacher_revision: str, checkpoint_inventory_sha256: str,
                             student_width: int, target_width: int,
                             steps: int = 1) -> dict:
    """Execute actual detached-teacher gradient steps with five held-out guards.

    Works with tiny CPU modules or the untrained native 150M/300M blueprint,
    but does NOT qualify either blueprint, pretrained teacher, or hardware.
    """
    if student_candidate not in STUDENTS or type(steps) is not int or not 1 <= steps <= 100:
        raise OfflineDistillError("unregistered student or unbounded offline train steps")
    if (not isinstance(student, nn.Module) or not isinstance(readout, nn.Module)
            or not isinstance(optimizer, torch.optim.Optimizer)):
        raise OfflineDistillError("student and shared readout must be modules")
    params = list(student.parameters()) + list(readout.parameters())
    trainable = [p for p in params if p.requires_grad]
    student_trainable = [p for p in student.parameters() if p.requires_grad]
    optimizer_params = [p for group in optimizer.param_groups for p in group["params"]]
    if (not student_trainable or not trainable or
            len({id(p) for p in optimizer_params}) != len(optimizer_params)
            or {id(p) for p in optimizer_params} != {id(p) for p in trainable}
            or any(p.is_meta or not torch.isfinite(p).all() for p in params)):
        raise OfflineDistillError("optimizer must own exactly shared-student/readout trainable parameters")
    # Original P6 checked only parameter object IDs; a custom Optimizer or
    # process-global hook could execute foreign writes with those IDs intact.
    expected_ids = tuple(id(p) for p in optimizer_params)
    try:
        _verify_optimizer_lifecycle(optimizer)
        _verify_optimizer_storage_isolation(optimizer_params)
        expected_settings = _verify_optimizer_step_safety(optimizer)
    except LatentBridgeError as exc:
        raise OfflineDistillError("unsafe offline optimizer custody") from exc
    pairs, paired_receipts = _prepare(cohorts, teacher_candidate=teacher_candidate,
                     teacher_revision=teacher_revision,
                     checkpoint_inventory_sha256=checkpoint_inventory_sha256,
                     student_width=student_width, target_width=target_width)
    # Entire evidence preflight + forward shape check runs before ANY update.
    # Evaluation on held-out splits is never used to calculate gradients.
    student.eval()
    readout.eval()
    with torch.no_grad():
        before = {name: float(_loss(student, readout, pairs[name])) for name in SPLITS}
    student.train()
    readout.train()
    for _ in range(steps):
        # First boundary is BEFORE zero_grad; the next one precedes the
        # physical step after arbitrary Student/Readout forward hooks.
        _check_optimizer_custody(optimizer, expected_ids,
                                 expected_settings, trainable)
        optimizer.zero_grad(set_to_none=True)
        value = _loss(student, readout, pairs["train"])
        value.backward()
        try:
            norm = torch.nn.utils.clip_grad_norm_(trainable, max_norm=1.0,
                                                  error_if_nonfinite=True)
        except RuntimeError as exc:
            raise OfflineDistillError("nonfinite shared-student gradient") from exc
        if not torch.isfinite(norm):
            raise OfflineDistillError("nonfinite shared-student gradient norm")
        _check_optimizer_custody(optimizer, expected_ids,
                                 expected_settings, trainable)
        try:
            _verify_optimizer_gradients(student, optimizer)
            _guarded_offline_optimizer_step(optimizer, expected_ids,
                                            expected_settings)
        except LatentBridgeError as exc:
            raise OfflineDistillError("unsafe offline optimizer step") from exc
    student.eval()
    readout.eval()
    with torch.no_grad():
        after = {name: float(_loss(student, readout, pairs[name])) for name in SPLITS}
    return {
        "schema": "hepta.offline-shared-student-rehearsal.v1",
        "student": student_candidate, "teacher": teacher_candidate,
        "teacher_revision": teacher_revision,
        "checkpoint_inventory_sha256": checkpoint_inventory_sha256,
        # Read the verified preflight snapshot, not the caller-owned cohort map:
        # optimizer hooks may replace a cohort object after all five checks.
        "source_split_digests": {
            key: paired_receipts[key]["source_manifest_sha256"] for key in SPLITS
        },
        # Report the actual byte-bound snapshots rather than only the caller's
        # declarations, so each before/after loss has a matching feature pair.
        "paired_split_receipts": paired_receipts,
        "loss_before": before, "loss_after": after,
        "optimizer_steps_train_only": steps, "optimizer_steps_heldout": 0,
        "teacher_model_executed_in_this_step": False,
        "pretrained_weights_independently_attested": False,
        "heldout_sources_independently_attested": False,
        "performance_qualified": False, "student_checkpoint_qualified": False,
        "real_target_hardware_attested": False,
        "mode": "SHADOW_ONLY", "authority": "DENY_ALL",
        "release": "HOLD_NO_GO", "production_activation_allowed": False,
    }
