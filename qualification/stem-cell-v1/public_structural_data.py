"""Fixed CLINC publisher partitions, never invented observation dates.

This eight-intent diagnostic is not the complete CLINC150 benchmark, prospective
Hepta data, independent source-family evidence, or production no-change.
"""
from __future__ import annotations

from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import unicodedata

from development_study_data import StudyConfig, audit_rows, canonical, write_once
from study import reject_duplicate_evidence_fields, reject_nonstandard_evidence_number

DATA_REVISION = "828f8093932c8fe6ca7936c3d2e52903b1c523de"
DATA_GIT_BLOB = "7a7b26c5f2dfbbf213f3e67d2dd0727e1af545aa"
DATA_BYTES = 2_495_390
INTENTS = ("alarm", "calendar", "date", "reminder", "time", "timer", "todo_list", "weather")
PARTITIONS = {"train": 100, "val": 20, "test": 30}
QUESTION = "Which of the listed intentions does this utterance express?"


def text_key(text):
    return hashlib.sha256(" ".join(unicodedata.normalize("NFC", text).split()).encode()).hexdigest()


def publisher_rows(data):
    """Keep every selected source row; leakage rejects rather than filtering it.

    The fixed 40/30/30 subdivision only uses original training text order by
    content hash. Official validation and test assignments remain untouched.
    Content IDs detect exact reuse; they do NOT identify independent speakers.
    """
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
    config = StudyConfig(classes=len(INTENTS), time_basis="publisher_partition", seal_replay=True)
    rows = audit_rows(rows, config)
    return rows, config, {"lineage": lineage, "intents": list(INTENTS),
        "publication": "Larson et al., EMNLP 2019, An Evaluation Dataset for Intent Classification and Out-of-Scope Prediction",
        "license": "CC-BY-3.0", "source_revision": DATA_REVISION,
        "complete_clinc150_benchmark": False, "genuine_future_windows": False,
        "content_groups_are_independent_speakers": False, "production_authorized": False}


def prepare_dataset(source, output):
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
    rows, config, provenance = publisher_rows(data)
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
