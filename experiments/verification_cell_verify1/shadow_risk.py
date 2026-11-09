"""Prospective, horizon-bound risk observations; forecasts never grant authority.

This small frequency model is a transparent train-only baseline, not a calibrated
neural verifier. Labels name the same terminal event and continuation policy;
reject/interrupt/UNKNOWN are dispositions, never substitutes for outcome truth.
Digests bind records but do not authenticate independent label collection.
"""

from dataclasses import asdict, dataclass
import hashlib
import json
import math
import re


DISPOSITIONS = ("accept", "reject", "interrupted", "unknown")
MAX_ROWS = 100000


def _require(condition, message):
    if not condition:
        raise ValueError(message)


def _text(value):
    _require(type(value) is str and 0 < len(value) <= 256
             and value == value.strip() and value.isprintable(), "invalid identity")


def _sha(value):
    _require(type(value) is str and re.fullmatch("[0-9a-f]{64}", value) is not None,
             "invalid SHA256")


def _digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                    allow_nan=False).encode()).hexdigest()


def _rows(value):
    _require(type(value) in (tuple, list) and len(value) <= MAX_ROWS,
             "expected bounded record array")
    return tuple(value)


@dataclass(frozen=True)
class Target:
    domain: str
    event: str
    horizon_end: int
    continuation_policy_sha256: str

    def __post_init__(self):
        _text(self.domain)
        _text(self.event)
        _sha(self.continuation_policy_sha256)
        _require(type(self.horizon_end) is int and 0 < self.horizon_end <= 1000000,
                 "invalid terminal horizon")


@dataclass(frozen=True)
class Snapshot:
    trajectory_id: str
    source_group: str
    subject_sha256: str
    target: Target
    observed_step: int
    features: tuple[float, ...]

    def __post_init__(self):
        _text(self.trajectory_id)
        _text(self.source_group)
        _sha(self.subject_sha256)
        _require(type(self.target) is Target, "invalid target")
        _require(type(self.observed_step) is int
                 and 0 <= self.observed_step < self.target.horizon_end,
                 "forecast must precede the fixed terminal horizon")
        _require(type(self.features) in (tuple, list) and len(self.features) <= 32,
                 "invalid feature vector")
        _require(all(type(x) in (int, float) and -1e6 <= x <= 1e6
                     for x in self.features), "nonfinite or invalid feature")
        object.__setattr__(self, "features", tuple(float(x) for x in self.features))


@dataclass(frozen=True)
class TerminalLabel:
    trajectory_id: str
    source_group: str
    subject_sha256: str
    target: Target
    disposition: str
    error: bool | None
    observed_step: int
    evidence_sha256: str | None
    missing_reason: str | None

    def __post_init__(self):
        _text(self.trajectory_id)
        _text(self.source_group)
        _sha(self.subject_sha256)
        _require(type(self.target) is Target, "invalid target")
        _require(self.disposition in DISPOSITIONS, "invalid disposition")
        _require(type(self.observed_step) is int and self.observed_step >= 0,
                 "invalid label frontier")
        _require(self.error is None or type(self.error) is bool, "invalid label truth")
        if self.error is None:
            _require(self.evidence_sha256 is None, "missing label cannot claim evidence")
            _text(self.missing_reason)
        else:
            _sha(self.evidence_sha256)
            _require(self.missing_reason is None, "known label has missing reason")
            _require(self.observed_step >= self.target.horizon_end,
                     "early readback does not establish the terminal target")


@dataclass(frozen=True)
class Prediction:
    snapshot: Snapshot
    probability: float | None
    model_sha256: str

    def __post_init__(self):
        _require(type(self.snapshot) is Snapshot, "invalid prediction snapshot")
        _sha(self.model_sha256)
        if self.probability is not None:
            _require(type(self.probability) in (int, float)
                     and 0 <= self.probability <= 1, "invalid risk probability")


def _bindings(snapshots, labels):
    labels = _rows(labels)
    _require(all(type(row) is TerminalLabel for row in labels), "invalid label record")
    index = {row.trajectory_id: row for row in labels}
    _require(len(index) == len(labels), "duplicate terminal label")
    seen = set()
    for row in _rows(snapshots):
        _require(type(row) is Snapshot, "invalid snapshot record")
        key = row.trajectory_id, row.observed_step
        _require(key not in seen, "duplicate trajectory frontier")
        seen.add(key)
        label = index.get(row.trajectory_id)
        _require(label is not None, "missing terminal label record; retain explicit missing truth")
        _require((row.source_group, row.subject_sha256, row.target)
                 == (label.source_group, label.subject_sha256, label.target),
                 "snapshot and terminal target binding mismatch")
    return index


@dataclass(frozen=True)
class RiskTable:
    target: Target
    training_groups: tuple[str, ...]
    evaluation_groups: tuple[str, ...]
    cells: tuple[tuple[int, tuple[float, ...], int, int], ...]
    training_label_count: int
    missing_training_labels: int
    data_sha256: str
    model_sha256: str

    def predict(self, snapshot):
        _require(type(snapshot) is Snapshot and snapshot.target == self.target,
                 "target/domain/horizon/policy changed")
        _require(snapshot.source_group in self.evaluation_groups
                 and snapshot.source_group not in self.training_groups,
                 "prediction group is not a frozen evaluation group")
        probability = None
        for step, features, errors, count in self.cells:
            if (step, features) == (snapshot.observed_step, snapshot.features):
                probability = (errors + 1) / (count + 2)
                break
        return Prediction(snapshot, probability, self.model_sha256)


def fit_risk_table(snapshots, labels, target, training_groups, evaluation_groups):
    """Fit Beta(1,1)-smoothed bins; each trajectory contributes once per frontier."""
    snapshots, labels = _rows(snapshots), _rows(labels)
    groups = []
    for values in (training_groups, evaluation_groups):
        values = _rows(values)
        _require(bool(values) and len(set(values)) == len(values), "invalid split groups")
        for value in values:
            _text(value)
        groups.append(tuple(sorted(values)))
    train, evaluation = groups
    _require(not set(train).intersection(evaluation), "training/evaluation group leakage")
    index = _bindings(snapshots, labels)
    _require(bool(snapshots) and type(target) is Target, "training data/target required")
    _require(set(index) == {row.trajectory_id for row in snapshots}, "training roster mismatch")
    _require({row.source_group for row in labels} == set(train), "training groups mismatch")
    _require(all(row.target == target for row in labels), "training target mismatch")
    cells = {}
    for row in snapshots:
        label = index[row.trajectory_id]
        if label.error is None:
            continue
        counts = cells.setdefault((row.observed_step, row.features), [0, 0])
        counts[0] += int(label.error)
        counts[1] += 1
    _require(bool(cells), "no known training labels")
    cells = tuple((step, features, *counts) for (step, features), counts in sorted(cells.items()))
    data = {"snapshots": [asdict(row) for row in snapshots],
            "labels": [asdict(row) for row in labels]}
    identity = {"version": "verify-shadow-frequency-v1", "target": asdict(target),
                "training_groups": train, "evaluation_groups": evaluation,
                "cells": cells, "prior": [1, 1], "data_sha256": _digest(data)}
    known = sum(row.error is not None for row in labels)
    return RiskTable(target, train, evaluation, cells, known, len(labels) - known,
                     identity["data_sha256"], _digest(identity))


def evaluate_shadow(predictions, labels):
    """Finite-data summaries only; repeated frontiers are not independent trials.

All planned trajectories need one label record, including missing labels and
attempts with no predictions. Callers must supply that independently frozen roster.
"""
    predictions, labels = _rows(predictions), _rows(labels)
    _require(all(type(row) is Prediction for row in predictions), "invalid prediction")
    _require(len({row.model_sha256 for row in predictions}) <= 1,
             "evaluate frozen models separately")
    index = _bindings(tuple(row.snapshot for row in predictions), labels)
    targets = {row.target for row in labels}
    _require(len(targets) <= 1, "mixed terminal targets in one evaluation")
    metrics, by_step = {}, {}
    for row in predictions:
        by_step.setdefault(row.snapshot.observed_step, []).append(row)
    for step, rows in sorted(by_step.items()):
        scored = [(row.probability, index[row.snapshot.trajectory_id].error)
                  for row in rows if row.probability is not None
                  and index[row.snapshot.trajectory_id].error is not None]
        infinite = sum((p == 0 and y) or (p == 1 and not y) for p, y in scored)
        loss = [-(math.log(p) if y else math.log1p(-p)) for p, y in scored
                if not ((p == 0 and y) or (p == 1 and not y))]
        metrics[str(step)] = {
            "predictions": len(rows), "scored": len(scored),
            "unsupported": sum(row.probability is None for row in rows),
            "missing_labels": sum(index[row.snapshot.trajectory_id].error is None for row in rows),
            "brier": sum((p - y) ** 2 for p, y in scored) / len(scored) if scored else None,
            "log_loss": math.fsum(loss) / len(scored) if scored and not infinite else None,
            "infinite_log_loss_count": infinite,
        }
    accepted = [row for row in labels if row.disposition == "accept"]
    errors = sum(row.error is True for row in accepted)
    missing = sum(row.error is None for row in accepted)
    counts = {}
    for disposition in DISPOSITIONS:
        rows = [row for row in labels if row.disposition == disposition]
        known = sum(row.error is not None for row in rows)
        reasons = {}
        for row in rows:
            if row.error is None:
                reasons[row.missing_reason] = reasons.get(row.missing_reason, 0) + 1
        counts[disposition] = {"trajectories": len(rows), "known_labels": known,
                               "label_acquisition_rate": known / len(rows) if rows else None,
                               "missing_reasons": reasons}
    return {
        "version": "verify-shadow-metrics-v1", "trajectories": len(labels),
        "trajectories_with_predictions": len({row.snapshot.trajectory_id for row in predictions}),
        "prediction_count": len(predictions), "known_labels": sum(row.error is not None for row in labels),
        "by_step": metrics, "by_disposition": counts,
        "acceptance_coverage": len(accepted) / len(labels) if labels else None,
        "accepted_error_missing_label_bounds": [errors / len(accepted), (errors + missing) / len(accepted)] if accepted else None,
        "all_trajectory_false_accept_missing_label_bounds": [errors / len(labels), (errors + missing) / len(labels)] if labels else None,
        "bounds_kind": "finite_dataset_missing_labels_not_confidence_intervals",
        "independent_sampling_established": False, "production_authority": "NONE",
    }
