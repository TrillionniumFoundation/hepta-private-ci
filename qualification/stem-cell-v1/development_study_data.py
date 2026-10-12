"""Strict experimental folds on top of the existing Stem dataset validator.

This is an offline experiment contract, not data permission or a runtime owner.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import hashlib
import json
import math
from pathlib import Path
import unicodedata

from study import load_jsonl, validate_dataset


PHASES = ("base", "adapt", "extra", "calibration", "held_out", "future_1", "future_2", "ood")
ROW_KEYS = {"sample_id", "source_group", "episode_id", "scope", "language", "split",
            "training_phase", "observed_at", "state", "question", "options", "label"}


@dataclass(frozen=True)
class StudyConfig:
    classes: int = 2
    rank: int = 8
    base_steps: int = 200
    adaptation_steps: int = 200
    seed: int = 7347
    minimum_groups: int = 8
    alpha: float = 0.05
    scalar_penalty: float = 0.0
    generation: int = 1
    max_tokens: int = 512
    benchmark_inputs: int = 4
    benchmark_replicas: int = 8
    origin: str = "public_retrospective"

    def validate(self):
        limits = {"classes": (2, 128), "rank": (1, 32), "base_steps": (1, 1000),
                  "adaptation_steps": (1, 1000), "seed": (0, 2**31-1),
                  "minimum_groups": (2, 10000), "generation": (1, 2**31-1),
                  "max_tokens": (1, 8192), "benchmark_inputs": (1, 8),
                  "benchmark_replicas": (1, 32)}
        for name, (low, high) in limits.items():
            if type(getattr(self, name)) is not int or not low <= getattr(self, name) <= high:
                raise ValueError(f"invalid {name}")
        for name, low, high in (("alpha", .001, .2), ("scalar_penalty", 0, 1)):
            value = getattr(self, name)
            if type(value) not in (int, float) or not math.isfinite(value) or not low <= value <= high:
                raise ValueError(f"invalid {name}")
        if self.origin not in {"public_retrospective", "prospective_hepta", "synthetic_fixture"}:
            raise ValueError("undeclared data origin")
        return self


def canonical(value):
    return (json.dumps(value, sort_keys=True, separators=(",", ":"),
                       ensure_ascii=True, allow_nan=False) + "\n").encode()


def digest(value):
    return hashlib.sha256(canonical(value)).hexdigest()


def write_once(path, value):
    """Experimental output only; never replace a selected artifact or old result."""
    payload = canonical(value)
    with Path(path).open("xb") as handle:
        handle.write(payload)
    return hashlib.sha256(payload).hexdigest()


def phase(row):
    return row["training_phase"] if row["split"] == "train" else row["split"]


def public_input(row):
    """Exactly the same label-free question and ordered options for every arm."""
    return {key: row[key] for key in ("state", "question", "options")}


def audit_rows(rows, config):
    config.validate()
    if not isinstance(rows, list) or not 1 <= len(rows) <= 4096:
        raise ValueError("bounded nonempty dataset required")
    if any(type(row) is not dict or set(row) != ROW_KEYS for row in rows):
        raise ValueError("unknown or missing experiment dataset fields")
    # Extend rather than weaken the canonical source/episode/split validator.
    validate_dataset(rows)
    groups, episodes, contents, times, scoped, options = {}, {}, {}, {}, set(), set()
    for row in rows:
        if set(row) != ROW_KEYS:
            raise ValueError("unknown or missing experiment dataset fields")
        split = phase(row)
        if (split not in PHASES or (row["split"] == "train" and split not in PHASES[:3])
                or (row["split"] != "train" and row["training_phase"] is not None)):
            raise ValueError("invalid explicit training phase")
        for name in ("sample_id", "source_group", "episode_id", "scope"):
            if type(row[name]) is not str or not 0 < len(row[name].encode()) <= 256:
                raise ValueError("unbounded dataset identity")
        if (type(row["label"]) is not int or not 0 <= row["label"] < config.classes
                or type(row["options"]) is not list or len(row["options"]) != config.classes
                or any(type(x) is not str or not 0 < len(x.encode()) <= 2048 for x in row["options"])
                or len(set(row["options"])) != config.classes):
            raise ValueError("invalid fixed action/label schema")
        for name in ("state", "question"):
            if type(row[name]) is not str or not 0 < len(row[name].encode()) <= 16384:
                raise ValueError("invalid bounded source input")
        if type(row["observed_at"]) is not str:
            raise ValueError("explicit timezone-aware observation time required")
        timestamp = datetime.fromisoformat(row["observed_at"])
        if timestamp.tzinfo is None or timestamp.utcoffset() is None:
            raise ValueError("observation time requires timezone")
        times.setdefault(split, []).append(timestamp)
        scoped.add(row["scope"])
        options.add(tuple(row["options"]))
        state = " ".join(unicodedata.normalize("NFC", row["state"]).split())
        if len(canonical(public_input(row))) > 65536:
            raise ValueError("joint input exceeds the existing Encoder byte envelope")
        if not state:
            raise ValueError("empty normalized source")
        # Even a changed question/options/ID must not hide repeated source text.
        for table, key in ((groups, row["source_group"]), (episodes, row["episode_id"]),
                           (contents, digest(state)), (contents, digest(public_input(row)))):
            if key in table and table[key] != split:
                raise ValueError("source/episode/content leakage across phases")
            table[key] = split
    if len(scoped) != 1 or len(options) != 1:
        raise ValueError("mixed scope or reordered action schema")
    if not set(PHASES[:5]) <= set(times):
        raise ValueError("base/adapt/extra/calibration/held_out are mandatory")
    # OOD is not assigned an invented chronology; optional future folds are.
    ordered = [p for p in PHASES[:-1] if p in times]
    if any(max(times[a]) >= min(times[b]) for a, b in zip(ordered, ordered[1:])):
        raise ValueError("overlapping or reversed observation windows")
    for split in PHASES[:3]:
        labels = {r["label"] for r in rows if phase(r) == split}
        if labels != set(range(config.classes)):
            raise ValueError("each training phase requires the full fixed label schema")
    return sorted(rows, key=lambda r: (PHASES.index(phase(r)), r["sample_id"]))


def read_dataset(path, expected_digest, config):
    path = Path(path)
    if (not path.is_file() or path.is_symlink() or path.stat().st_size > 16_777_216
            or type(expected_digest) is not str or len(expected_digest) != 64):
        raise ValueError("invalid bounded dataset source")
    actual = hashlib.sha256(path.read_bytes()).hexdigest()
    if actual != expected_digest:
        raise ValueError("dataset bytes differ from registered digest")
    rows = audit_rows(list(load_jsonl(path)), config)
    if hashlib.sha256(path.read_bytes()).hexdigest() != actual:
        raise ValueError("dataset changed during read")
    return rows
