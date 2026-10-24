"""Explicit action cohorts and complete128KiB lexical controls."""

from dataclasses import dataclass
import hashlib
import time

import numpy as np

from cell_full_text_lexical import FullTextLexical
from cell_learning_baselines import FrozenBaselines
from cell_learning_models import canonical, normalize_features
from operational_head_view import full_normalized_text


def public_rows(rows):
    result = []
    for row in rows:
        if set(row) != {"source_id", "group_id", "text"}:
            raise ValueError("only source_id/group_id/text may enter predictor rows")
        if any(type(row[k]) is not str or not 1 <= len(row[k].encode()) <= 512
               for k in ("source_id", "group_id")):
            raise ValueError("bounded source and bug-group identifiers required")
        full_normalized_text(row["text"])
        result.append(dict(row))
    if len({r["source_id"] for r in result}) != len(result):
        raise ValueError("duplicate source ID")
    return tuple(result)


@dataclass(frozen=True)
class ActionCohort:
    features: np.ndarray
    labels: np.ndarray
    rows: tuple
    split: str

    def __post_init__(self):
        x, y = np.asarray(self.features), np.asarray(self.labels)
        if (x.ndim != 2 or x.dtype != np.float32 or y.shape != (len(x),) or y.dtype.kind not in "iu"
                or np.any((y < 0) | (y > 1)) or len(self.rows) != len(x)
                or self.split not in ("train", "tuning", "calibration", "holdout")):
            raise ValueError("explicit role, FP32 features and binary action labels required")
        normalize_features(x)
        rows = public_rows(self.rows)
        if sum(len(row["text"].encode()) for row in rows) > 128*1024**2:
            raise ValueError("cohort source text exceeds128MiB total bound")
        x, y = x.copy(), y.astype(np.int64, copy=True)
        x.flags.writeable = y.flags.writeable = False
        object.__setattr__(self, "features", x)
        object.__setattr__(self, "labels", y)
        object.__setattr__(self, "rows", rows)

    def digest(self):
        result = hashlib.sha256(canonical([self.split, self.rows]))
        for value in (self.features, self.labels):
            result.update(canonical([value.dtype.str, value.shape]))
            result.update(value.tobytes())
        return result.hexdigest()

    def context(self):
        return {"source_ids": sorted(row["source_id"] for row in self.rows),
            "group_ids": sorted({row["group_id"] for row in self.rows}),
            "predictor_sha256": sorted({hashlib.sha256(full_normalized_text(row["text"]).encode()).hexdigest()
                                        for row in self.rows})}


def validate_action_roles(train, tuning, calibration, holdout=None):
    cohorts = [train, tuning, calibration] + ([] if holdout is None else [holdout])
    if [c.split for c in cohorts] != ["train", "tuning", "calibration", "holdout"][:len(cohorts)]:
        raise ValueError("explicit independent train/tuning/calibration roles required")
    seen = {key: set() for key in ("source_ids", "group_ids", "predictor_sha256")}
    contexts = []
    for cohort in cohorts:
        if cohort.features.shape[1] != train.features.shape[1]:
            raise ValueError("feature widths differ")
        context = cohort.context()
        for key in seen:
            if set(context[key]) & seen[key]:
                raise ValueError("cross-role source/group/full-predictor overlap")
            seen[key].update(context[key])
        contexts.append(context)
    return contexts


def action_training_order(train, seed):
    candidates = [[], []]
    for index, row in enumerate(train.rows):
        candidates[int(train.labels[index])].append((hashlib.sha256(canonical([seed, row["source_id"]])).digest(), index))
    candidates = [sorted(items, reverse=True) for items in candidates]
    selected, groups, texts = [], set(), set()
    while any(candidates):
        for items in candidates:
            while items:
                _, index = items.pop()
                row = train.rows[index]
                text = full_normalized_text(row["text"])
                if row["group_id"] in groups or text in texts:
                    continue
                selected.append(index)
                groups.add(row["group_id"])
                texts.add(text)
                break
    return selected


def _numeric_metadata(rows):
    # The frozen numeric arms do not read text. Their incidental lexical index
    # receives a fixed neutral string; complete text is handled separately.
    return [dict(row, text="numeric feature metadata") for row in rows]


class ActionBaselines:
    def __init__(self, features, labels, rows):
        start, cpu = time.perf_counter_ns(), time.process_time_ns()
        rows = public_rows(rows)
        self.lexical = FullTextLexical(labels, rows)
        self.numeric = FrozenBaselines(features, labels, _numeric_metadata(rows), 2)
        self.fit_cost = {"wall_ns": time.perf_counter_ns()-start, "cpu_ns": time.process_time_ns()-cpu}
        self.memory = {"lexical": self.lexical.memory, "numeric": self.numeric.memory,
            "reachable_state_bytes": self.lexical.memory["reachable_state_bytes"]+self.numeric.memory["reachable_state_bytes"],
            "summed_component_bytes_may_double_count_shared_metadata": True}

    def predict(self, arm, features, rows):
        rows = public_rows(rows)
        if arm in ("exact", "bm25"):
            return self.lexical.predict(arm, rows)
        if arm not in ("dense_nearest", "prototype"):
            raise ValueError("unknown action baseline")
        return self.numeric.predict(arm, features, _numeric_metadata(rows))
