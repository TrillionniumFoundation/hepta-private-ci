"""Exact historical V3 content head over the immutable common cache.

This adapter retains V3's six-emotion/source-binding tasks and frozen weights.
It supplies development replay only: it is not the missing V6 strong head, a
new cohort, semantic sentence binding, or a pretrained multimodal encoder.
"""

from dataclasses import dataclass
import hashlib
from pathlib import Path
import sys

import numpy as np

from experiments.hcsn_v7_support_20261101.content_interface.content_interface import (
    ContractError, CorrectnessValue, Modality, PrefixObservation, StopEvaluation,
)


REPO = Path(__file__).resolve().parents[3]
RECOVERED = REPO / "recovered/v3"
if str(RECOVERED) not in sys.path:
    sys.path.insert(0, str(RECOVERED))
from experiments.hcsn_causal_execution_v3.av_probe import load_encoder, predict_prefix


CHECKPOINTS = {
    "async_av": "2f390a2dda86eef5eb808bad1092e86dbe9cc3fd904bf378890d87deccb7768b",
    "av_binding": "8caeeeb6ebc663c348bd02da7ed77dde26363b42978c42f711e90d0584894fc4",
}
RAW_VERSION = 1.0
ROW_WIDTH = 17  # Source release time for causal ordering, then 16 content values.


def restored_checkpoint(task):
    if task not in CHECKPOINTS:
        raise ContractError("Unknown historical V3 task")
    return RECOVERED / "experiments/hcsn_causal_execution_v3/results/av_probe" / task / "selected_encoder.npz"


def prepared_observation(x, observed, relative_times, *, object_id, modality,
                         prefix_end, completed_at, event_id=None):
    """Copy only the requested modality's available history into one prefix.

The provider may own the full prepared historical recording. The returned
packet contains no future row, source/actor identity feature, or target label.
Raw-media decoding and encoder execution are outside this replay adapter.
"""
    x = np.asarray(x, np.float64)
    observed = np.asarray(observed, bool)
    times = np.asarray(relative_times, np.float64)
    if (x.ndim != 2 or x.shape[1] != 40 or times.shape != (len(x),)
            or observed.shape != times.shape
            or not np.isfinite(times).all() or np.any(times < 0)
            or np.any(np.diff(times) < 0)):
        raise ContractError("Invalid historical causal event history")
    kind = 0 if modality == Modality.AUDIO else 1 if modality == Modality.VIDEO else None
    if kind is None:
        raise ContractError("Unknown modality")
    mask = (observed & ((x[:, 33] > x[:, 32]).astype(int) == kind)
            & (x[:, 34 + kind] > 0) & (times <= prefix_end))
    values = x[mask, :16]
    if not np.isfinite(values).all():
        raise ContractError("Nonfinite content in the requested accepted prefix")
    rows = np.column_stack((times[mask], values))
    raw = (RAW_VERSION, float(len(rows)), *rows.ravel().tolist())
    aligned = values.mean(0) if len(values) else np.zeros(16)
    return PrefixObservation(
        event_id=event_id or f"legacy-{modality.value}-{prefix_end}",
        object_id=object_id, modality=modality, prefix_end=prefix_end,
        available_at=float(prefix_end), completed_at=completed_at,
        raw=raw, aligned=tuple(aligned), alignment_id="legacy-v3-raw-moments-v1",
        aligned_window=(0.0, float(prefix_end)))


def cache_rows(content):
    """Decode and merge visible histories using V3's causal audio/video order."""
    records = []
    for kind, observation in enumerate((content.audio, content.video)):
        if observation is None:
            continue
        raw = observation.raw
        if len(raw) < 2 or raw[0] != RAW_VERSION or not raw[1].is_integer():
            raise ContractError("Invalid historical prefix layout")
        count = int(raw[1])
        if count < 0 or len(raw) != 2 + count * ROW_WIDTH:
            raise ContractError("Historical prefix count disagrees with its payload")
        rows = np.asarray(raw[2:], np.float64).reshape(count, ROW_WIDTH)
        if (np.any(rows[:, 0] < 0) or np.any(rows[:, 0] > observation.prefix_end)
                or np.any(np.diff(rows[:, 0]) < 0)):
            raise ContractError("Historical prefix contains noncausal source rows")
        records.extend((float(row[0]), kind, ordinal, row[1:])
                       for ordinal, row in enumerate(rows))
    records.sort(key=lambda record: record[:3])
    x = np.zeros((len(records), 40), np.float64)
    for index, (_, kind, _, value) in enumerate(records):
        x[index, :16] = value
        x[index, 32 + kind] = 1.0
        x[index, 34 + kind] = 1.0
    return x, np.ones(len(x), bool)


@dataclass(frozen=True)
class BinnedCorrectness:
    """Fit actual zero/one head correctness; never call max-softmax calibrated.

This deliberately simple development calibrator does not itself establish
held-out calibration. Its caller must freeze and report the data role and hash.
"""

    head_id: str
    probabilities: tuple
    counts: tuple
    source_sha256: str
    data_role: str

    @classmethod
    def fit(cls, head_id, class_probabilities, labels, *, source_sha256, data_role):
        p, labels = np.asarray(class_probabilities), np.asarray(labels)
        if (p.ndim != 2 or labels.shape != (len(p),) or not len(p)
                or not np.isfinite(p).all() or not np.allclose(p.sum(1), 1)
                or np.any(p < 0) or not np.issubdtype(labels.dtype, np.integer)
                or np.any(labels < 0) or np.any(labels >= p.shape[1])):
            raise ContractError("Correctness calibration requires actual labeled outcomes")
        correct = (p.argmax(1) == labels).astype(float)
        bins = np.minimum((p.max(1) * 5).astype(int), 4)
        global_rate = (correct.sum() + 1) / (len(p) + 2)
        counts = tuple(int(np.sum(bins == index)) for index in range(5))
        rates = tuple(float((correct[bins == index].sum() + 1) / (counts[index] + 2))
                      if counts[index] else float(global_rate) for index in range(5))
        return cls(head_id, rates, counts, source_sha256, data_role)

    def __call__(self, probabilities, content):
        index = min(int(max(probabilities) * 5), 4)
        return CorrectnessValue(self.probabilities[index], self.head_id)


class LegacyV3Head:
    """Frozen historical predictor, with an explicit correctness-calibration hook."""

    def __init__(self, task, calibrator=None):
        path = restored_checkpoint(task)
        sha = hashlib.sha256(path.read_bytes()).hexdigest()
        if sha != CHECKPOINTS[task]:
            raise ContractError("Historical checkpoint identity mismatch")
        self.model = load_encoder(path)
        for value in self.model.values():
            value.setflags(write=False)
        self.task, self.checkpoint_sha256 = task, sha
        self.head_id = f"legacy-v3-{task}-{sha[:16]}"
        self.calibrator = calibrator

    def classify(self, content):
        x, observed = cache_rows(content)
        return predict_prefix(self.model, x, observed)

    def evaluate(self, content):
        if self.calibrator is None:
            raise ContractError("No empirical correctness calibrator has been supplied")
        probability = tuple(float(x) for x in self.classify(content))
        correctness = self.calibrator(probability, content)
        if correctness.head_id != self.head_id:
            raise ContractError("Correctness calibrator belongs to a different head")
        return StopEvaluation(probability, correctness)

    def storage_accounting(self):
        return {"checkpoint_file_bytes": restored_checkpoint(self.task).stat().st_size,
                "loaded_array_bytes": sum(x.nbytes for x in self.model.values()),
                "scope": "Checkpoint arrays only; cache, Python runtime, workspaces and calibration extra"}
