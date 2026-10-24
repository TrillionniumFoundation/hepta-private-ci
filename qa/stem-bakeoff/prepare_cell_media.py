"""Freeze source-disjoint real-media tasks before feature extraction or scoring.

Images use author-supplied CIFAR-10 binary labels; audio uses the five published
ESC-50 category groups. No label, category, filename or source identity is part
of the encoder's neutral text prompt. These are correlated recognition targets,
not new natural software-diagnostic tasks or evidence of unseen pretraining data.
"""

import argparse
import collections
import csv
import hashlib
import io
import json
from pathlib import Path
import re
import tarfile

import numpy as np
from PIL import Image

ESC_REVISION = "33c8ce9eb2cf0b1c2f8bcf322eb349b6be34dbb6"
CIFAR_MD5 = "c32a1d4ab5d03f1284b67883e8d87530"
IMAGE_CLASSES = ("airplane", "automobile", "bird", "cat", "deer", "dog", "frog", "horse", "ship", "truck")
IMAGE_TARGETS = {"image_animal": (2, 3, 4, 5, 6, 7), "image_mammal": (3, 4, 5, 7),
                 "image_road_transport": (1, 9), "image_air_or_water_transport": (0, 8)}
AUDIO_GROUPS = ("animals", "natural_soundscapes_water", "human_nonspeech", "interior_domestic", "exterior_urban")
SALT = "hepta-real-media-source-selection-v1-20261024"


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def order(source_id):
    return sha((SALT + "\0" + source_id).encode())


def input_identity(modality, text, media_digest):
    """Bind the full predictor, excluding labels, source names and split metadata."""
    return sha(canonical({"modality": modality, "text": text, "media_digest": media_digest}))


def verify_git_blob(raw, entry):
    digest = hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest()
    if len(raw) != entry["size"] or digest != entry["sha"]:
        raise ValueError("metadata bytes differ from the pinned Git tree")


def remove_crossing_groups(rows, partition):
    groups = collections.defaultdict(list)
    for row in rows:
        groups[row["group_id"]].append(row)
    excluded = sorted(group for group, members in groups.items()
                      if len({partition(row) for row in members}) > 1)
    excluded_set = set(excluded)
    return [row for row in rows if row["group_id"] not in excluded_set], excluded


def unique_representatives(rows):
    """At most one clip/image per original source group, chosen without scores."""
    grouped = collections.defaultdict(list)
    for row in rows:
        grouped[row["group_id"]].append(row)
    return [min(members, key=lambda row: order(row["source_id"])) for members in grouped.values()]


def definitions(modality):
    if modality == "image":
        return [{"task_id": task, "family": "real_image_taxonomy", "positive_classes": list(classes),
                 "label_origin": "published CIFAR-10 class membership"} for task, classes in IMAGE_TARGETS.items()]
    return [{"task_id": "audio_" + name, "family": "real_environmental_audio",
             "positive_classes": list(range(index * 10, index * 10 + 10)),
             "label_origin": "published ESC-50 category group membership"}
            for index, name in enumerate(AUDIO_GROUPS)]


def freeze_dataset(rows, modality, protocol, audit, root):
    tasks = definitions(modality)
    rows = sorted(rows, key=lambda row: row["source_id"])
    if len({row["group_id"] for row in rows}) != len(rows):
        raise ValueError("source groups must be unique across all sampled rows")
    if any(row["text"] != protocol["neutral_prompt"] for row in rows):
        raise ValueError("all predictors must use the fixed neutral prompt")
    if any(row["record"].get("text") != row["text"] or row["modality"] != modality
           or not re.fullmatch(r"[0-9a-f]{64}", row["input_content_sha256"]) for row in rows):
        raise ValueError("typed full-input identity and matching neutral record required")
    if len({row["input_content_sha256"] for row in rows}) != len(rows):
        raise ValueError("duplicate full predictor content")
    for row in rows:
        row["labels"] = {task["task_id"]: int(row["fine_label"] in task["positive_classes"]) for task in tasks}
    status = []
    for task in tasks:
        counts = {split: [sum(row["labels"][task["task_id"]] == label for row in rows if row["split"] == split)
                          for label in (0, 1)] for split in ("train", "calibration", "holdout")}
        status.append({"task_id": task["task_id"], "negative_positive_support": counts,
                       "available_balanced_budgets": [n for n in (8, 32, 128) if min(counts["train"]) >= n // 2]})
    dataset = {"schema": "hepta.real-media-cell-cohort.v1", "protocol": protocol,
               "selected_tasks": [task["task_id"] for task in tasks], "task_definitions": tasks,
               "task_status": status, "rows": rows}
    root.mkdir(parents=True, exist_ok=False)
    for name, value in (("dataset.json", dataset), ("protocol.json", protocol), ("audit.json", audit)):
        (root / name).write_bytes(canonical(value) + b"\n")
    return dataset


def image_records(archive):
    raw = Path(archive).read_bytes()
    if len(raw) > 200_000_000 or hashlib.md5(raw).hexdigest() != CIFAR_MD5:
        raise ValueError("official binary CIFAR-10 archive checksum differs")
    records = []
    expected = {f"data_batch_{i}.bin" for i in range(1, 6)} | {"test_batch.bin"}
    seen = set()
    with tarfile.open(fileobj=io.BytesIO(raw), mode="r:gz") as tar:
        for member in tar:
            name = Path(member.name).name
            if name not in expected:
                continue
            if name in seen or not member.isfile() or member.size != 30_730_000:
                raise ValueError("unexpected binary dataset member")
            seen.add(name)
            data = np.frombuffer(tar.extractfile(member).read(), dtype=np.uint8).reshape(10000, 3073)
            if np.any(data[:, 0] > 9):
                raise ValueError("invalid published image class")
            for index, values in enumerate(data):
                pixels = values[1:].reshape(3, 32, 32).transpose(1, 2, 0).copy()
                records.append({"source_id": f"cifar10:{name}:{index}", "group_id": "pixels:" + sha(pixels.tobytes()),
                    "fine_label": int(values[0]), "official_split": "test" if name == "test_batch.bin" else "train",
                    "pixels": pixels})
    if seen != expected or len(records) != 60000:
        raise ValueError("complete official binary inventory required")
    return records, sha(raw)


def prepare_images(archive, output):
    rows, digest = image_records(archive)
    rows, crossing = remove_crossing_groups(rows, lambda row: row["official_split"])
    # Identical pixels with disagreeing labels cannot yield an unambiguous target.
    labels = collections.defaultdict(set)
    for row in rows:
        labels[row["group_id"]].add(row["fine_label"])
    conflicts = {group for group, values in labels.items() if len(values) > 1}
    rows = unique_representatives([row for row in rows if row["group_id"] not in conflicts])
    chosen = []
    for label in range(10):
        train = sorted([r for r in rows if r["fine_label"] == label and r["official_split"] == "train"],
                       key=lambda row: order(row["source_id"]))
        test = sorted([r for r in rows if r["fine_label"] == label and r["official_split"] == "test"],
                      key=lambda row: order(row["source_id"]))
        train_count = 32 if label in (0, 1, 8, 9) else 16
        for split, subset in (("train", train[:train_count]), ("calibration", train[train_count:train_count + 8]),
                              ("holdout", test[:16])):
            if len(subset) != (train_count if split == "train" else 8 if split == "calibration" else 16):
                raise ValueError("predeclared image source support unavailable")
            chosen.extend(dict(row, split=split) for row in subset)
    protocol = {"selection_salt": SALT, "dataset": "CIFAR-10 binary", "archive_sha256": digest,
        "archive_md5": CIFAR_MD5, "neutral_prompt": "A photograph.", "input_modality": "image",
        "train_per_vehicle_class": 32, "train_per_animal_class": 16,
        "calibration_per_class": 8, "holdout_per_class": 16,
        "official_test_used_only_for_holdout": True, "deduplication": "exact RGB pixel groups; near duplicates not certified",
        "pretraining_overlap_known": False, "model_scores_used_for_selection": False,
        "vision_soft_token_budget": 70, "encoder_max_tokens": 1024,
        "source_code_sha256": sha(Path(__file__).read_bytes())}
    root = Path(output)
    material = []
    for row in chosen:
        pixels = row.pop("pixels")
        stream = io.BytesIO()
        Image.fromarray(pixels).save(stream, format="PNG")
        raw = stream.getvalue()
        relative = "media/" + row["group_id"].split(":", 1)[1] + ".png"
        row.update(text=protocol["neutral_prompt"], source_version="sha256:" + digest, modality="image",
                   record={"text": protocol["neutral_prompt"], "image": relative}, media_sha256=sha(raw), media_bytes=len(raw),
                   input_content_sha256=input_identity("image", protocol["neutral_prompt"], "sha256:" + sha(raw)))
        material.append((relative, raw))
    dataset = freeze_dataset(chosen, "image", protocol,
        {"cross_official_split_groups_excluded": crossing, "conflicting_pixel_groups_excluded": sorted(conflicts)}, root)
    (root / "media").mkdir()
    for relative, raw in material:
        (root / relative).write_bytes(raw)
    return dataset


def prepare_audio(metadata, tree, output):
    metadata, tree = Path(metadata), Path(tree)
    inputs = list(csv.DictReader(io.StringIO(metadata.read_text())))
    objects = {row["path"]: row for row in json.loads(tree.read_bytes())["tree"] if row["type"] == "blob"}
    verify_git_blob(metadata.read_bytes(), objects["meta/esc50.csv"])
    if len(inputs) != 2000 or len({row["filename"] for row in inputs}) != 2000:
        raise ValueError("complete ESC-50 metadata inventory required")
    rows = []
    for row in inputs:
        name, fold, label = row["filename"], int(row["fold"]), int(row["target"])
        if not re.fullmatch(r"[1-5]-[0-9]+-[A-Za-z0-9]+-[0-9]+\.wav", name) or not 0 <= label < 50:
            raise ValueError("invalid published audio identity or label")
        blob = objects["audio/" + name]
        rows.append({"source_id": "esc50:" + name, "group_id": "freesound:" + row["src_file"],
                     "fine_label": label, "official_fold": fold, "filename": name,
                     "upstream_blob_sha": blob["sha"], "media_bytes": blob["size"]})
    rows, crossing = remove_crossing_groups(rows, lambda row: row["official_fold"])
    rows = unique_representatives(rows)
    chosen, support = [], []
    for label in range(50):
        for split, folds, quota in (("train", (1, 2, 3), 8), ("calibration", (4,), 2), ("holdout", (5,), 4)):
            eligible = sorted([row for row in rows if row["fine_label"] == label and row["official_fold"] in folds],
                              key=lambda row: order(row["source_id"]))
            selected = eligible[:quota]
            support.append({"fine_label": label, "split": split, "quota": quota, "available_groups": len(eligible),
                            "selected_groups": len(selected)})
            chosen.extend(dict(row, split=split) for row in selected)
    protocol = {"selection_salt": SALT, "dataset": "ESC-50", "revision": ESC_REVISION,
        "metadata_sha256": sha(metadata.read_bytes()), "git_tree_sha256": sha(tree.read_bytes()),
        "neutral_prompt": "An environmental audio recording.", "input_modality": "audio",
        "train_folds": [1, 2, 3], "calibration_folds": [4], "holdout_folds": [5],
        "per_class_quotas": {"train": 8, "calibration": 2, "holdout": 4},
        "shortfall_rule": "retain all available distinct source groups; report unsupported learning budgets",
        "same_original_recording_used_at_most_once": True, "clip_duration_seconds": 5,
        "pretraining_overlap_known": False, "model_scores_used_for_selection": False,
        "vision_soft_token_budget": 70, "encoder_max_tokens": 1024,
        "source_code_sha256": sha(Path(__file__).read_bytes())}
    for row in chosen:
        row.update(text=protocol["neutral_prompt"], source_version="git:" + ESC_REVISION, modality="audio",
            record={"text": protocol["neutral_prompt"], "audio": "media/" + row["filename"]},
            input_content_sha256=input_identity("audio", protocol["neutral_prompt"], "git-blob-sha1:" + row["upstream_blob_sha"]),
            upstream_url=f"https://raw.githubusercontent.com/karolpiczak/ESC-50/{ESC_REVISION}/audio/" + row["filename"])
    return freeze_dataset(chosen, "audio", protocol,
        {"cross_official_fold_groups_excluded": crossing, "per_class_support": support}, Path(output))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--modality", required=True, choices=("image", "audio"))
    parser.add_argument("--input", required=True)
    parser.add_argument("--tree")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    result = prepare_images(args.input, args.output) if args.modality == "image" else prepare_audio(args.input, args.tree, args.output)
    print(json.dumps({"rows": len(result["rows"]), "tasks": result["selected_tasks"], "support": result["task_status"]}))
