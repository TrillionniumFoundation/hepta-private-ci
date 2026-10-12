"""Leakage-fenced, equal-budget Organ transfer ablation (research only).

An Organ is a frozen source-task direction; it never accesses future labels.
It is deliberately evaluated against identical Head seeds/updates WITHOUT an
Organ. Transfer must demonstrate future net utility, not embedding ranking.
"""
from __future__ import annotations

import time
from dataclasses import dataclass

import numpy as np

from cell_learning import DynamicCell, LearningContractError, paired_future_score, rust_candidate_digest

ROLES = ("MemoryRead", "Predictor", "Decision", "Value")


@dataclass(frozen=True)
class FrozenOrgan:
    role: str
    direction: np.ndarray
    source_groups: tuple[str, ...]
    source_latest_time: int

    def transform(self, x: np.ndarray, strength: float = 1.0) -> np.ndarray:
        features = np.asarray(x, dtype=np.float64)
        if features.ndim != 2 or features.shape[1] != len(self.direction):
            raise LearningContractError("Organ encoder width mismatch")
        return features + strength * (features @ self.direction)[:, None] * self.direction[None, :]


def fit_frozen_organ(
    role: str, x: np.ndarray, y: np.ndarray, groups: list[str], timestamps: list[int],
) -> FrozenOrgan:
    if role not in ROLES:
        raise LearningContractError("unknown Organ role")
    features = np.asarray(x, dtype=np.float64)
    labels = np.asarray(y, dtype=np.float64)
    if (
        features.ndim != 2 or not 1 <= features.shape[1] <= 512
        or len(features) < 16 or labels.shape != (len(features),)
        or len(groups) != len(features) or len(timestamps) != len(features)
        or not np.isfinite(features).all()
        or not np.isin(labels, [0, 1]).all()
        or len(set(labels.tolist())) != 2
        or any(type(t) is not int or t < 0 for t in timestamps)
    ):
        raise LearningContractError("invalid authorized source history")
    delta = features[labels == 1].mean(axis=0) - features[labels == 0].mean(axis=0)
    norm = float(np.linalg.norm(delta))
    if norm < 1e-9:
        raise LearningContractError("no transferable organ signal")
    delta = delta / norm
    delta.setflags(write=False)
    return FrozenOrgan(role, delta, tuple(sorted(set(groups))), max(timestamps))


def compare_organ(
    organ: FrozenOrgan,
    target_cell: str,
    encoder_digest: str,
    training_x: np.ndarray,
    training_y: np.ndarray,
    training_groups: list[str],
    training_times: list[int],
    future_x: np.ndarray,
    future_y: np.ndarray,
    future_groups: list[str],
    future_times: list[int],
    production_no_change: np.ndarray,
    *,
    seed: int = 7,
    steps: int = 40,
    lr: float = 0.15,
) -> dict:
    """Time-ordered train-only and future-only split, with equal Head capacity."""
    x = np.asarray(training_x, dtype=np.float64)
    y = np.asarray(training_y, dtype=np.float64)
    f = np.asarray(future_x, dtype=np.float64)
    fy = np.asarray(future_y, dtype=np.float64)
    if (
        x.ndim != 2 or f.ndim != 2 or x.shape[1] != f.shape[1]
        or x.shape[1] != len(organ.direction)
        or len(x) < 8 or len(f) < 8
        or y.shape != (len(x),) or fy.shape != (len(f),)
        or len(training_groups) != len(x) or len(training_times) != len(x)
        or len(future_groups) != len(f) or len(future_times) != len(f)
        or any(type(t) is not int or t < 0 for t in training_times + future_times)
        or not np.isfinite(x).all() or not np.isfinite(f).all()
        or not np.isin(y, [0, 1]).all() or not np.isin(fy, [0, 1]).all()
        or len(set(training_groups) & set(future_groups)) > 0
        or len(set(organ.source_groups) & (set(training_groups) | set(future_groups))) > 0
        # Source history must be frozen before the first target update:
        # source < target train < future, not merely source/train < future.
        or organ.source_latest_time >= min(training_times)
        or max(training_times) >= min(future_times)
        or steps <= 0 or steps > 1000
    ):
        raise LearningContractError("leakage, chronology, group or budget violation")
    original = DynamicCell.initialize(target_cell, encoder_digest, x.shape[1],
                                      min(16, x.shape[1]), 8, seed)
    plain = original.clone_frozen()
    with_organ = original.clone_frozen()
    start = time.perf_counter_ns()
    org_x = organ.transform(x)
    org_f = organ.transform(f)
    transform_nanos = time.perf_counter_ns() - start
    if np.abs(org_x).max() > 8 or np.abs(org_f).max() > 8:
        raise LearningContractError("Organ output beyond Q24 admitted range")
    for _ in range(steps):
        plain.learn(x, y, lr)
        with_organ.learn(org_x, y, lr)
    without = paired_future_score(plain, original, f, fy, production_no_change)
    with_transfer = paired_future_score(
        with_organ, original, org_f, fy, production_no_change
    )
    if plain.parameter_count() != with_organ.parameter_count():
        raise LearningContractError("unequal Head parameter budget")
    return {
        "role": organ.role,
        "head_parameters": plain.parameter_count(),
        "organ_shared_parameters": int(len(organ.direction)),
        "organ_transform_nanos": transform_nanos,
        "without_organ": without,
        "with_organ": with_transfer,
        "future_bce_delta": with_transfer["trained_bce"] - without["trained_bce"],
        "negative_transfer": with_transfer["trained_bce"] > without["trained_bce"],
        "trained_without_digest": rust_candidate_digest(plain.export_q24()),
        "trained_with_digest": rust_candidate_digest(with_organ.export_q24()),
        "production_promotion": "DENY_ALL",
        "evidence_type": "offline_shadow_not_signed",
    }
