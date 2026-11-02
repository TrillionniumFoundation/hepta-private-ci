"""Historical accepted-prefix inputs; no legacy head, IDs or labels in rows."""

import hashlib
import itertools
import numpy as np
import torch
from experiments.hcsn_v8_execution_20261101.frontend.replay import legacy_data, populated_cache
from experiments.hcsn_v7_support_20261101.content_interface.content_interface import Modality
from experiments.hcsn_causal_execution_v3.av_probe import labels_of


def schedules():
    for positions in itertools.combinations(range(5), 2):
        yield (Modality.AUDIO,) + tuple(Modality.AUDIO if i in positions else Modality.VIDEO for i in range(5))


class Normalization:
    def __init__(self, center, scale):
        self.center, self.scale = np.asarray(center, np.float64), np.asarray(scale, np.float64)
        if (self.center.shape != (55,) or self.scale.shape != (55,) or np.any(self.scale <= 0)
                or not np.isfinite(self.center).all() or not np.isfinite(self.scale).all()):
            raise ValueError("Invalid shared training-only normalization")
        protected = [32, 33, 34, 51, 52, 53, 54]
        if np.any(self.center[protected] != 0) or np.any(self.scale[protected] != 1):
            raise ValueError("Clock, levels and event flags must remain exact")

    @classmethod
    def fit(cls, x):
        values = np.asarray(x).reshape(-1, 55)
        center, scale = np.zeros(55), np.ones(55)
        columns = list(range(32))+list(range(35, 51))
        center[columns] = values[:, columns].mean(0)
        scale[columns] = np.maximum(values[:, columns].std(0), 1e-5)
        return cls(center, scale)

    def apply(self, row):
        if isinstance(row, torch.Tensor):
            return (row-row.new_tensor(self.center))/row.new_tensor(self.scale)
        return (np.asarray(row)-self.center)/self.scale

    def save(self, path):
        np.savez_compressed(path, center=self.center, scale=self.scale)

    @classmethod
    def load(cls, path):
        with np.load(path, allow_pickle=False) as data:
            return cls(data["center"], data["scale"])


def row_from_cache(current, modality, previous_global):
    a, v = (current.level(m) for m in Modality)
    now = max(a, v)
    if previous_global > now:
        raise ValueError("Source clock cannot move backwards")
    obs = current.observation(modality)
    if obs is None:
        raise ValueError("Accepted update lacks its visible observation")
    raw = np.asarray(obs.raw[2:], np.float64).reshape(-1, 17)
    lower = obs.prefix_end-1
    select = raw[:, 0] >= lower if lower == 0 else raw[:, 0] > lower
    values = raw[select, 1:]
    fresh = values.mean(0) if len(values) else np.zeros(16)
    cached = [np.zeros(16) if current.observation(m) is None else np.asarray(current.observation(m).aligned)
              for m in Modality]
    result = np.r_[*cached, a/3, v/3, now-previous_global, fresh,
                   float(modality == Modality.AUDIO), float(modality == Modality.VIDEO),
                   obs.prefix_end/3, float(len(values) > 0)]
    if result.shape != (55,) or not np.isfinite(result).all():
        raise ValueError("Invalid shared accepted-prefix row")
    return result


def dataset(task, split):
    data = legacy_data(task, split)
    labels = np.asarray(labels_of(data), np.int64)
    rows, targets, objects, orders = [], [], [], []
    for index, label in enumerate(labels):
        caches = {(a, v): populated_cache(data, index, a, v) for a in range(4) for v in range(4)}
        for order in schedules():
            a, v, previous, sequence = 0, 0, 0, []
            for modality in order:
                a += modality == Modality.AUDIO
                v += modality == Modality.VIDEO
                current = caches[a, v]
                sequence.append(row_from_cache(current, modality, previous))
                previous = max(a, v)
            rows.append(sequence); targets.append([int(label)]*6)
            objects.append(index); orders.append([m.value for m in order])
    x, y = np.asarray(rows, np.float64), np.asarray(targets, np.int64)
    identity = {"task": task, "split": split, "ids": data["ids"].astype(str).tolist(),
                "objects": len(labels), "sequences": len(rows), "x_shape": list(x.shape),
                "x_sha256": hashlib.sha256(x.tobytes()).hexdigest(),
                "y_sha256": hashlib.sha256(y.tobytes()).hexdigest(),
                "source_array_sha256": data["metadata"]["array_sha256"],
                "scope": "Historical exposed V3 records; no independent confirmation qualification"}
    return torch.from_numpy(x), torch.from_numpy(y), np.asarray(objects), orders, identity
