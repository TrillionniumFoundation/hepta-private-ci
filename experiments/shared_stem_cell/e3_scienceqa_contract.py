"""Bounded source-only ScienceQA contract for genuine frozen Stem/vision research.

The acquisition process stages public source inputs before accessing the answer
column. A different inference process sees train/cal labels but no holdout labels;
the independent scorer receives holdout labels only AFTER predictions are sealed.
Not a cryptographic independent label owner or a chronological future dataset.
"""
from __future__ import annotations
import hashlib
import json
import math
import os
from pathlib import Path

DATASET = "lmms-lab/ScienceQA-IMG"
DATASET_REVISION = "b9984af01798586705cee1fbdfa80a6dcbef04f1"
GRANITE = ("ibm-granite/granite-embedding-97m-multilingual-r2",
           "835ad14087e140460703cf0fae09f97d469d65c2")
DINO = ("facebook/dinov2-small", "ed25f3a31f01632728cabb09d1542f84ab7b0056")
SIZES = {"train": 96, "validation": 32, "test": 64}
SCHEMA = "hepta.e3-granite-dinov2-scienceqa.v1"
ARMS = ("text_only", "unaligned_equal_fusion", "rotated_equal_fusion",
        "bridge_image_only", "bridge_equal_fusion", "train_gate", "calibrated_fusion",
        "image_masked")
MAX_ROWS = 256
MAX_BYTES = 32 * 1024 * 1024


class E3Error(ValueError):
    pass


def canonical(value):
    return (json.dumps(value, sort_keys=True, ensure_ascii=True,
                       separators=(",", ":"), allow_nan=False) + "\n").encode()


def sha(data):
    return hashlib.sha256(data).hexdigest()


def digest(value):
    if (type(value) is not str or len(value) != 64 or
            any(ch not in "0123456789abcdef" for ch in value)):
        raise E3Error("invalid sha256")
    return value


def revision(value):
    if (type(value) is not str or len(value) != 40 or
            any(ch not in "0123456789abcdef" for ch in value)):
        raise E3Error("immutable model/dataset revision required")
    return value


def pairs(kv):
    result = {}
    for key, value in kv:
        if key in result:
            raise E3Error("duplicate JSON key")
        result[key] = value
    return result


def decode(data):
    def reject(x):
        raise E3Error("nonfinite input: " + x)
    try:
        obj = json.loads(data, object_pairs_hook=pairs, parse_constant=reject)
        canonical(obj)  # fail also for 1e999 overflow
        return obj
    except (TypeError, ValueError, OverflowError) as error:
        raise E3Error("invalid or nonfinite JSON document") from error


def read_pinned(path, expected, *, maximum=MAX_BYTES):
    digest(expected)
    if not isinstance(path, Path) or path.is_symlink() or not path.is_file():
        raise E3Error("unsafe or absent input")
    if path.stat().st_size == 0 or path.stat().st_size > maximum:
        raise E3Error("input size outside bound")
    payload = path.read_bytes()
    if sha(payload) != expected:
        raise E3Error("source/artifact digest changed")
    return payload


def write_new(path, value):
    data = canonical(value)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as f:
        f.write(data)
        f.flush()
        os.fsync(f.fileno())
    return sha(data)


def write_jsonl(path, rows):
    if not 1 <= len(rows) <= MAX_ROWS:
        raise E3Error("invalid row count")
    data = b"".join(canonical(r) for r in rows)
    if len(data) > MAX_BYTES:
        raise E3Error("oversized rows")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as f:
        f.write(data)
        f.flush()
        os.fsync(f.fileno())
    return sha(data)


def read_jsonl(path, expected):
    data = read_pinned(path, expected)
    rows = [decode(line) for line in data.splitlines()]
    if not 1 <= len(rows) <= MAX_ROWS or any(type(row) is not dict for row in rows):
        raise E3Error("invalid row content/cardinality")
    return rows


def source_row(row):
    required = {"id", "group", "split", "image", "question", "hint", "choices", "scope"}
    if type(row) is not dict or set(row) != required:
        raise E3Error("source fields must be exact; no target")
    for key in ("id", "group", "image"):
        digest(row[key])
    if row["scope"] != "public-scienceqa-e3-research" or row["split"] not in SIZES:
        raise E3Error("scope/source-split drift")
    if (type(row["question"]) is not str or not 1 <= len(row["question"].encode()) <= 4096
            or type(row["hint"]) is not str or len(row["hint"].encode()) > 2048
            or type(row["choices"]) is not list or len(row["choices"]) != 4
            or any(type(c) is not str or not 1 <= len(c.encode()) <= 1024 for c in row["choices"])):
        raise E3Error("malformed bounded task")
    return row


def label_row(row):
    if type(row) is not dict or set(row) != {"id", "group", "label", "split"}:
        raise E3Error("exact source label record required")
    digest(row["id"])
    digest(row["group"])
    if row["split"] not in SIZES or type(row["label"]) is not int or not 0 <= row["label"] < 4:
        raise E3Error("invalid original answer")
    return row


def validate_source(rows, *, enforce_sizes=True):
    if not 1 <= len(rows) <= MAX_ROWS:
        raise E3Error("source cardinality")
    ids, groups, texts, counts = set(), {}, {}, {s: 0 for s in SIZES}
    for row in rows:
        source_row(row)
        if row["id"] in ids:
            raise E3Error("duplicate source")
        ids.add(row["id"])
        counts[row["split"]] += 1
        txt = sha(canonical([row["question"], row["hint"], row["choices"]]))
        for registry, key in ((groups, row["group"]), (texts, txt)):
            if key in registry and registry[key] != row["split"]:
                raise E3Error("cross-split image or question leakage")
            registry[key] = row["split"]
    if enforce_sizes and counts != SIZES:
        raise E3Error("predeclared full cohort missing")
    return counts


def validate_labels(sources, labels, allowed_splits):
    src = {r["id"]: r for r in sources if r["split"] in allowed_splits}
    if len(labels) != len(src):
        raise E3Error("incomplete target coverage")
    seen = set()
    for item in labels:
        label_row(item)
        r = src.get(item["id"])
        if r is None or item["id"] in seen or r["group"] != item["group"] or r["split"] != item["split"]:
            raise E3Error("label/source/split mismatch or duplicate")
        seen.add(item["id"])
    return {r["id"]: r["label"] for r in labels}


def unit_probabilities(logits):
    if type(logits) not in (tuple, list) or len(logits) != 4:
        raise E3Error("four-choice probability required")
    if any(type(x) not in (float, int) or not math.isfinite(x) for x in logits):
        raise E3Error("nonfinite logits")
    t = max(logits)
    exp = [math.exp(x - t) for x in logits]
    total = math.fsum(exp)
    probs = [x / total for x in exp]
    if abs(math.fsum(probs) - 1) > 1e-12:
        raise E3Error("invalid score normalization")
    return probs


def validate_probabilities(values):
    if type(values) is not list or len(values) != 4 or any(
            type(x) not in (float, int) or not math.isfinite(x) or not 0 <= x <= 1 for x in values):
        raise E3Error("invalid probabilities")
    if abs(math.fsum(values) - 1.0) > 1e-6:
        raise E3Error("probabilities do not sum to one")
