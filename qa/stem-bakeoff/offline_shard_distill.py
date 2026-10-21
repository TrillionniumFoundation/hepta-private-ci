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

SPLITS = ("train", "calibration", "future_1", "future_2", "ood")
SHA256 = re.compile(r"[0-9a-f]{64}\Z")
SHA40 = re.compile(r"[0-9a-f]{40}\Z")
TEACHERS = frozenset(("embeddinggemma2_740m", "t5gemma2_encoder_270m"))
STUDENTS = frozenset(("hepta_latent_150m", "hepta_latent_300m"))


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
                cohort.expected_source_sha256 in seen_batches or
                not isinstance(cohort.sample_digests, tuple) or
                len(cohort.sample_digests) != slots.shape[0] or
                not all(_sha256(s) for s in cohort.sample_digests) or
                len(set(cohort.sample_digests)) != len(cohort.sample_digests) or
                seen_sources.intersection(cohort.sample_digests)):
            raise OfflineDistillError(f"{name}: missing/overlapping held-out source IDs")
        slot_sha = hashlib.sha256(slots.detach().contiguous().cpu().numpy().tobytes()).hexdigest()
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
        # The teacher shard is detached data. A trainable producer is prohibited.
        if slots.requires_grad or slots.grad_fn is not None:
            raise OfflineDistillError(f"{name}: frozen upstream producer required")
        seen_teacher_features.add(manifest["raw_feature_sha256"])
        pairs[name] = (slots.detach(), targets.detach().to(device=slots.device))
    return pairs


def _loss(student: nn.Module, readout: nn.Module,
          pair: tuple[torch.Tensor, torch.Tensor]) -> torch.Tensor:
    slots, target = pair
    encoded = student(slots)
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
    optimizer_params = [p for group in optimizer.param_groups for p in group["params"]]
    if (not trainable or len({id(p) for p in optimizer_params}) != len(optimizer_params)
            or {id(p) for p in optimizer_params} != {id(p) for p in trainable}
            or any(p.is_meta or not torch.isfinite(p).all() for p in params)):
        raise OfflineDistillError("optimizer must own exactly shared-student/readout trainable parameters")
    pairs = _prepare(cohorts, teacher_candidate=teacher_candidate,
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
        optimizer.step()
        if any(not torch.isfinite(p).all() for p in params):
            raise OfflineDistillError("nonfinite student parameter after optimizer")
    student.eval()
    readout.eval()
    with torch.no_grad():
        after = {name: float(_loss(student, readout, pairs[name])) for name in SPLITS}
    return {
        "schema": "hepta.offline-shared-student-rehearsal.v1",
        "student": student_candidate, "teacher": teacher_candidate,
        "teacher_revision": teacher_revision,
        "checkpoint_inventory_sha256": checkpoint_inventory_sha256,
        "source_split_digests": {key: cohorts[key].expected_source_sha256 for key in SPLITS},
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
