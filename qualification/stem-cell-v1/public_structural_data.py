"""Fixed CLINC publisher partitions, never invented observation dates.

This eight-intent diagnostic is not the complete CLINC150 benchmark, prospective
Hepta data, independent source-family evidence, or production no-change.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import unicodedata

from development_study_data import StudyConfig, audit_rows, canonical, phase, write_once
from study import reject_duplicate_evidence_fields, reject_nonstandard_evidence_number

DATA_REVISION = "828f8093932c8fe6ca7936c3d2e52903b1c523de"
DATA_GIT_BLOB = "7a7b26c5f2dfbbf213f3e67d2dd0727e1af545aa"
DATA_BYTES = 2_495_390
INTENTS = ("alarm", "calendar", "date", "reminder", "time", "timer", "todo_list", "weather")
PARTITIONS = {"train": 100, "val": 20, "test": 30}
STRICT_PARTITIONS = "publisher_strict_v1"
GROUPED_PARTITIONS = "protected_content_groups_v2"
PARTITION_POLICIES = (STRICT_PARTITIONS, GROUPED_PARTITIONS)
QUESTION = "Which of the listed intentions does this utterance express?"


def text_key(text):
    return hashlib.sha256(" ".join(unicodedata.normalize("NFC", text).split()).encode()).hexdigest()


def protect_content_groups(rows):
    """Keep every row/label but move complete content groups only forward.

    Assignment uses text identity and the original stage, never labels/scores.
    Conflicting labels are retained and reported, not resolved by majority vote.
    This is an explicit derived diagnostic, NOT the official publisher split.
    """
    order = ("base", "adapt", "extra", "calibration", "held_out")
    groups = defaultdict(list)
    for row in rows:
        groups[text_key(row["state"])].append(row)
    assigned, changes, conflicts = {}, [], []
    for key, members in sorted(groups.items()):
        target = max((phase(row) for row in members), key=order.index)
        assigned[key] = target
        if len({row["label"] for row in members}) > 1:
            conflicts.append({"content_sha256": key, "sample_ids": sorted(row["sample_id"] for row in members),
                              "labels_preserved": sorted({row["label"] for row in members})})
        for row in members:
            if phase(row) != target:
                changes.append({"sample_id": row["sample_id"], "from_phase": phase(row),
                                "to_phase": target, "content_sha256": key})
    result = []
    for original in rows:
        row = dict(original)
        target = assigned[text_key(row["state"])]
        row["split"] = "train" if target in order[:3] else target
        row["training_phase"] = target if target in order[:3] else None
        result.append(row)
    return result, {"policy": GROUPED_PARTITIONS, "retained_rows": len(result),
                    "content_groups": len(groups), "moved_rows": sorted(changes, key=lambda row: row["sample_id"]),
                    "conflicting_label_groups": conflicts,
                    "phase_counts": dict(sorted(Counter(phase(row) for row in result).items())),
                    "official_publisher_partitions_unchanged": False,
                    "original_labels_unchanged": True, "dropped_rows": 0}


def publisher_rows(data, *, partition_policy=STRICT_PARTITIONS):
    """Keep every selected source row; leakage rejects rather than filtering it.

    The fixed 40/30/30 subdivision only uses original training text order by
    content hash. Strict mode leaves official validation/test assignments intact;
    the explicit grouped mode records every derived phase change separately.
    Content IDs detect exact reuse; they do NOT identify independent speakers.
    """
    if partition_policy not in PARTITION_POLICIES:
        raise ValueError("unknown explicit partition policy")
    if type(data) is not dict or not set(PARTITIONS) <= set(data):
        raise ValueError("missing publisher partitions")
    rows, lineage = [], []
    for split, required in PARTITIONS.items():
        source = data[split]
        if type(source) is not list or not 1 <= len(source) <= 20_000:
            raise ValueError("invalid publisher partition size")
        by_label = {label: [] for label in INTENTS}
        for index, row in enumerate(source):
            if (type(row) is not list or len(row) != 2 or type(row[0]) is not str
                    or not 0 < len(row[0].encode()) <= 16_384 or type(row[1]) is not str):
                raise ValueError("invalid publisher row")
            if row[1] in by_label:
                by_label[row[1]].append((index, row[0]))
        for label, entries in by_label.items():
            if len(entries) != required:
                raise ValueError("fixed class/partition census differs from publisher")
            for ordinal, (index, text) in enumerate(sorted(entries, key=lambda x: (text_key(x[1]), x[0]))):
                p = (("base" if ordinal < 40 else "adapt" if ordinal < 70 else "extra")
                     if split == "train" else "calibration" if split == "val" else "held_out")
                sid = f"clinc:{split}:{index}"
                # No random IDs or artificial dates are appended to Encoder inputs.
                rows.append({"sample_id": sid, "source_group": f"content:{text_key(text)}",
                    "episode_id": sid, "scope": "public-clinc-eight-intent-research",
                    "language": "en", "split": "train" if split == "train" else p,
                    "training_phase": p if split == "train" else None, "observed_at": None,
                    "state": text, "question": QUESTION, "options": list(INTENTS),
                    "label": INTENTS.index(label)})
                lineage.append({"sample_id": sid, "publisher_partition": split,
                    "publisher_index": index, "source_revision": DATA_REVISION,
                    "source_text_sha256": hashlib.sha256(text.encode()).hexdigest()})
    partition_report = {"policy": STRICT_PARTITIONS, "official_publisher_partitions_unchanged": True}
    if partition_policy == GROUPED_PARTITIONS:
        rows, partition_report = protect_content_groups(rows)
    original_stage = {item["sample_id"]: item for item in lineage}
    for row in rows:
        original_stage[row["sample_id"]]["execution_phase"] = phase(row)
    config = StudyConfig(classes=len(INTENTS), time_basis="publisher_partition", seal_replay=True)
    rows = audit_rows(rows, config)
    return rows, config, {"partition_policy": partition_report, "lineage": lineage, "intents": list(INTENTS),
        "publication": "Larson et al., EMNLP 2019, An Evaluation Dataset for Intent Classification and Out-of-Scope Prediction",
        "license": "CC-BY-3.0", "source_revision": DATA_REVISION,
        "complete_clinc150_benchmark": False, "genuine_future_windows": False,
        "content_groups_are_independent_speakers": False, "production_authorized": False}


def prepare_dataset(source, output, *, partition_policy=STRICT_PARTITIONS):
    """Bind original public bytes before parsing or producing a study fold."""
    source, output = Path(source), Path(output)
    if source.is_symlink() or not source.is_file() or source.stat().st_size != DATA_BYTES:
        raise ValueError("publisher source byte count mismatch")
    with source.open("rb") as handle:
        raw = handle.read(DATA_BYTES + 1)
    actual = hashlib.sha1(f"blob {len(raw)}\0".encode() + raw).hexdigest()
    if actual != DATA_GIT_BLOB:
        raise ValueError("publisher source Git blob mismatch")
    data = json.loads(raw, object_pairs_hook=reject_duplicate_evidence_fields,
                      parse_constant=reject_nonstandard_evidence_number)
    rows, config, provenance = publisher_rows(data, partition_policy=partition_policy)
    # The raw file is kept, including nonselected classes; nothing is relabelled.
    with (output / "dataset.jsonl").open("xb") as handle:
        for row in rows:
            handle.write(canonical(row))
    config_sha = write_once(output / "config.jsonl", asdict(config))
    dataset_sha = hashlib.sha256((output / "dataset.jsonl").read_bytes()).hexdigest()
    provenance.update({"publisher_file_sha256": hashlib.sha256(raw).hexdigest(),
                       "dataset_sha256": dataset_sha, "config_sha256": config_sha})
    write_once(output / "dataset-provenance.json", provenance)
    return dataset_sha, config_sha
