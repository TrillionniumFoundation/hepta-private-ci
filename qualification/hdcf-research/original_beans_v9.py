"""Replay original real DINOv2 Beans features through the EXISTING HDCF CellBank.

RESEARCH_ONLY / SHADOW_ONLY / DENY_ALL. This code never runs a pretrained
model or claims that public retrospective TEST is a prospective future window.
Training receives only original TRAIN class labels. Withheld labels and source
parquets are admitted exclusively in a later, independent reviewer process.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
from zipfile import ZipFile
from typing import Any

from multimodal_token_bridge_v8 import (
    SCHEMA, WIDTH, MODALITIES, token_bytes_sha256, to_physical_bank,
)

SOURCE_ZIP_SHA = "49ee4b855879e8ad463fb3f0ffb21e30b332fb24d1626360aa8f382d16ef82ad"
FEATURE_ZIP_SHA = "92536c949e16ee0722357ccb1d881f371707df3c26424cd93dd2bfc96e49511e"
TARGET_ZIP_SHA = "946101fe7e57a151ce5ae9ec314fc6e01b7244aeac48f49034ee0a581e09c67d"
SOURCE_MANIFEST_SHA = "0233221fae3986612ed34c86b3da2e708b2423a77d19a74f1d0a73ed46e81490"
TRAIN_SHA = "7f905a7323966a58e89b8e839ed656bb869fc82d16a3fadc7dce40972a5f8b19"
TEST_SHA = "534a6b0648f585d69b7ec0ad7a7540720d60c8db8106dc6d0508296316f6cb27"
DATA_REV = "27aa014ce09b193e1a6f58112d4a66e0eddb69c5"
MODEL_REV = "150c8e7bb7cef2d30ec31b13a517af14840ee3f7"
WEIGHTS_SHA = "ae1e99fcefd534ed978cdeb8326f08030c96e28b7a81ffcbc98a857c84d14be1"
PREPROCESS_SHA = "14e780d86fa1861f8751f868d7f45425b5feb55c38ca26f152ca5097ab30f828"
FEATURE_ENCODER_SHA = "66301a1057dffff05adbb24d8e635b74d1b01e4d3ebb477bee1f25fdd5e3d8a8"
ORIGINAL_RUN_ID = 38680856403
SOURCE_ARTIFACT_ID = 11948574238
FEATURE_ARTIFACT_ID = 11949168280
TARGET_ARTIFACT_ID = 11948269689
CLASSES = ("angular_leaf_spot", "bean_rust", "healthy")
SCOPE = "hepta-e2-natural-beans-retrospective-research"
TASK = "healthy_vs_diseased_binary_reanalysis"
MAX_ZIP_BYTES = 16_000_000


class Reject(ValueError):
    pass


def need(predicate: bool, explanation: str) -> None:
    if not predicate:
        raise Reject(explanation)


def sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def canonical(obj: Any) -> bytes:
    return (json.dumps(obj, ensure_ascii=True, sort_keys=True,
                       separators=(",", ":"), allow_nan=False) + "\n").encode("ascii")


def pairs(seq):
    obj = {}
    for key, value in seq:
        need(key not in obj, "duplicate JSON key")
        obj[key] = value
    return obj


def json_strict(raw: bytes) -> Any:
    need(len(raw) <= 8_000_000, "oversized JSON")
    try:
        return json.loads(raw.decode("utf-8"), object_pairs_hook=pairs,
                          parse_constant=lambda _: (_ for _ in ()).throw(Reject("nonfinite JSON")))
    except (ValueError, UnicodeError, TypeError) as error:
        raise Reject("invalid JSON") from error


def lines_strict(raw: bytes) -> list[dict]:
    need(raw.endswith(b"\n") and 0 < len(raw) <= 8_000_000, "invalid JSONL length")
    rows = []
    for line in raw.splitlines():
        row = json_strict(line)
        need(type(row) is dict and canonical(row) == line + b"\n", "noncanonical JSONL row")
        rows.append(row)
    return rows


class PinnedZip:
    """Exact archive sha and safe-member census before returning any bytes."""
    def __init__(self, path: str | Path, expected_sha: str, *, image_files=False):
        path = Path(path)
        need(not path.is_symlink() and path.is_file() and
             0 < path.stat().st_size < MAX_ZIP_BYTES, "missing/oversized archive")
        with path.open("rb") as fd:
            need(hashlib.file_digest(fd, "sha256").hexdigest() == expected_sha,
                 "original GitHub artifact ZIP bytes changed")
        self.zip = ZipFile(path)
        infos = self.zip.infolist()
        need(1 <= len(infos) <= (100 if image_files else 18), "archive census")
        names = [i.filename for i in infos]
        need(len(names) == len(set(names)), "duplicate ZIP member")
        need(all(not n.startswith("/") and "\\" not in n and
                 all(part not in ("", ".", "..") for part in n.split("/"))
                 for n in names), "unsafe ZIP member")
        need(all(((i.external_attr >> 16) & 0o170000) != 0o120000
                 for i in infos), "linked ZIP member")
        need(sum(i.file_size for i in infos) < 32_000_000, "inflated ZIP member size")
        need(all(not i.is_dir() and i.file_size <= 8_000_000 for i in infos),
             "directory/oversize member")
        self.names = set(names)

    def read(self, name: str) -> bytes:
        need(name in self.names, "missing required archive member")
        return self.zip.read(name)

    def close(self) -> None:
        self.zip.close()


def images_and_labels(src: PinnedZip) -> tuple[dict, list[dict], list[dict], dict]:
    manifest_bytes = src.read("source-manifest.json")
    need(sha(manifest_bytes) == SOURCE_MANIFEST_SHA, "source manifest changed")
    manifest = json_strict(manifest_bytes)
    need(manifest["schema"] == "hepta.e2.beans-natural-retrospective.v1.source-plan" and
         manifest["natural_images"] is True and manifest["authority"] == "DENY_ALL" and
         manifest["production_accepted"] is False and manifest["stem_selected"] is False and
         manifest["scope"] == SCOPE and manifest["train_cases"] == 36 and
         manifest["test_cases"] == 24 and manifest["dataset_repo"] == "AI-Lab-Makerere/beans" and
         manifest["dataset_revision"] == DATA_REV and
         manifest["train_parquet_sha256"] == TRAIN_SHA and
         manifest["phase_time_is_not_original_timestamp"] is True,
         "source manifest contract rejected")
    expected_names = {"train_images.jsonl", "future_images.jsonl",
                      "train_class.jsonl", "train_anchors.jsonl"}
    need(set(manifest["file_sha256s"]) == expected_names, "source census drift")
    for name in expected_names:
        need(sha(src.read("source/" + name)) == manifest["file_sha256s"][name],
             "source record digest mismatch")
    train = lines_strict(src.read("source/train_images.jsonl"))
    held = lines_strict(src.read("source/future_images.jsonl"))
    classes = lines_strict(src.read("source/train_class.jsonl"))
    need(len(train) == len(classes) == 36 and len(held) == 24,
         "source sample census changed")
    classes_by_id = {}
    for c in classes:
        need(set(c) == {"case_id", "class_label"} and c["case_id"] not in classes_by_id
             and c["class_label"] in CLASSES, "invalid TRAIN source labels")
        classes_by_id[c["case_id"]] = c["class_label"]
    need(set(classes_by_id) == {x["case_id"] for x in train},
         "training original label identifiers drift")
    seen_ids, seen_groups, seen_image_shas = set(), set(), set()
    for phase, rows in (("train", train), ("future", held)):
        for ordinal, rec in enumerate(rows):
            need(set(rec) == {"case_id", "condition", "group_id", "image_path",
                              "image_sha256", "observed_at", "question", "scope",
                              "source_sha256", "split"}, "source row shape drift")
            need(rec["split"] == phase and rec["scope"] == SCOPE and
                 rec["condition"] == "vision_required" and
                 rec["observed_at"] == (ordinal + (1 if phase == "train" else 1000)) and
                 rec["question"] == "Which disease class does this photographed bean leaf show?",
                 "source task/scope changed")
            need(rec["case_id"] not in seen_ids and rec["group_id"] not in seen_groups
                 and rec["image_sha256"] not in seen_image_shas,
                 "source duplicate/leak across split")
            need(rec["image_path"] == rec["case_id"] + ".jpg", "noncanonical image name")
            im = src.read("source/images/" + rec["image_path"])
            need(sha(im) == rec["image_sha256"] and im[:2] == b"\xff\xd8",
                 "original real JPEG content changed")
            seen_ids.add(rec["case_id"])
            seen_groups.add(rec["group_id"])
            seen_image_shas.add(rec["image_sha256"])
    return manifest, train, held, classes_by_id


def _profile(arc: PinnedZip, phase: str, orig_rows: list[dict]) -> dict[str, list[float]]:
    directory = "vision_train" if phase == "train" else "vision_future"
    receipt = json_strict(arc.read(directory + "/receipt.json"))
    raw = arc.read(directory + "/features.jsonl")
    n = len(orig_rows)
    need(receipt["phase"] == phase and receipt["actual_model_forwards"] == n and
         receipt["image_count"] == n and receipt["feature_width"] == WIDTH and
         receipt["encoder_repo"] == "facebook/dinov2-small" and
         receipt["encoder_revision"] == MODEL_REV and
         receipt["schema"] == "hepta.e2.dinov2-source-features.v1" and
         receipt["authority"] == "DENY_ALL" and
         receipt["checkpoint_locally_byte_verified"] is True and
         receipt["labels_seen"] is False and
         receipt["publisher_authenticated"] is False and
         receipt["production_accepted"] is False and
         receipt["snapshot_file_sha256s"] == {
             "config.json": "1809f83e3bdb1609a501a610ad4a742f4fd8ae44d72ca4aa0df52d1f2ac8628d",
             "model.safetensors": WEIGHTS_SHA,
             "preprocessor_config.json": PREPROCESS_SHA,
         } and receipt["source_sha256"] == sha(b"".join(canonical(r) for r in orig_rows)) and
         receipt["output_sha256"] == sha(raw),
         "original DINO source/model/feature execution identity mismatch")
    features = lines_strict(raw)
    need(len(features) == n, "physical feature count mismatch")
    out: dict[str, list[float]] = {}
    for src, rec in zip(orig_rows, features, strict=True):
        need(rec["case_id"] == src["case_id"] and rec["group_id"] == src["group_id"]
             and rec["image_sha256"] == src["image_sha256"] and
             rec["source_sha256"] == src["source_sha256"] and
             rec["scope"] == SCOPE and rec["split"] == phase and
             rec["source"]["input_sha256"] == src["image_sha256"] and
             rec["source"]["encoder_sha256"] == FEATURE_ENCODER_SHA and
             rec["source"]["modality"] == "image" and
             rec["condition"] == "vision_required" and
             "target" not in rec and "label" not in rec,
             "unsealed feature source/label identity")
        vec = rec["source"]["values"]
        need(type(vec) is list and len(vec) == WIDTH and
             all(type(v) in (float, int) and math.isfinite(v) and abs(v) <= 8 for v in vec),
             "invalid original pretrained FP32 width")
        need(rec["case_id"] not in out, "duplicate feature")
        out[rec["case_id"]] = vec
    return out


def _cell_type(case_id: str) -> str:
    digest = hashlib.sha256(("hepta.hdcf.beans-image-type.v9\0" + case_id).encode()).digest()
    return "type0" if digest[0] & 1 == 0 else "type1"


def _inactive_digest(modality: str, kind: str) -> str:
    return sha(("hepta.hdcf.v9.not-executed." + kind + "." + modality).encode())


def stage(source_zip: str | Path, feature_zip: str | Path) -> dict:
    """Admit pre-existing genuine source/model payloads, not historical labels."""
    src = PinnedZip(source_zip, SOURCE_ZIP_SHA, image_files=True)
    feat = PinnedZip(feature_zip, FEATURE_ZIP_SHA)
    try:
        _manifest, train, held, classes = images_and_labels(src)
        f_train = _profile(feat, "train", train)
        f_held = _profile(feat, "future", held)
        recv = json_strict(feat.read("producer_receipt.json"))
        need(recv["schema"] == "hepta.e2.beans-natural-retrospective.v1.producer-receipt"
             and recv["source_manifest_sha256"] == SOURCE_MANIFEST_SHA and
             recv["dino_train_forwards"] == 36 and recv["dino_future_forwards"] == 24
             and recv["dino_revision"] == MODEL_REV and
             recv["dino_weights_sha256"] == WEIGHTS_SHA and
             recv["test_labels_seen"] is False and
             recv["model_origin_independently_attested"] is False and
             recv["production_accepted"] is False and recv["stem_selected"] is False,
             "original producer receipt altered")
        encoder_map = {m: _inactive_digest(m, "encoder") for m in MODALITIES}
        preprocess_map = {m: _inactive_digest(m, "preprocess") for m in MODALITIES}
        encoder_map["image"] = WEIGHTS_SHA
        preprocess_map["image"] = PREPROCESS_SHA
        prod = {"principal": "beans-public-e2", "purpose": "vision-original-replay",
                "generation": 1, "epoch": 1, "source_sha256": SOURCE_MANIFEST_SHA,
                "encoders": encoder_map, "preprocessors": preprocess_map,
                "topology": "separate_frozen_frontends"}
        bank = {"schema": SCHEMA, "producer": prod, "dimension": WIDTH,
                "types": ["type0", "type1"], "fit": [], "held": []}
        for dest, cases, features in (("fit", train, f_train), ("held", held, f_held)):
            for rec in cases:
                case_id = rec["case_id"]
                vector = features[case_id]
                span = {"kind": "image", "asset_sha256": rec["image_sha256"],
                        "encoder_sha256": WEIGHTS_SHA, "preprocess_sha256": PREPROCESS_SHA,
                        "vectors": [vector], "time_ms": [],
                        "tokens_sha256": token_bytes_sha256([vector])}
                row = {"id": case_id, "family": rec["group_id"],
                       "type": _cell_type(case_id), "event_sha256": rec["source_sha256"],
                       "modalities": [span]}
                if dest == "fit":
                    row["target"] = int(classes[case_id] == "healthy")
                bank[dest].append(row)
        converted = to_physical_bank(bank)
        # Intentional lossy adapter; 60 *already recorded* real DINO forwards.
        need(len(converted["fit"]) == 36 and len(converted["held"]) == 24 and
             all("target" not in r for r in converted["held"]),
             "unblind held targets or wrong cardinality")
        return converted
    finally:
        src.close()
        feat.close()


def _source_targets(source_zip: str | Path, targets_zip: str | Path,
                    *, train_and_held: bool = True) -> tuple[dict, list[dict], list[dict], dict]:
    src = PinnedZip(source_zip, SOURCE_ZIP_SHA, image_files=True)
    tg = PinnedZip(targets_zip, TARGET_ZIP_SHA)
    try:
        _manifest, train, held, labels = images_and_labels(src)
        t = json_strict(tg.read("target-manifest.json"))
        need(t["schema"] == "hepta.e2.beans-natural-retrospective.v1.withheld-target-plan"
             and t["source_manifest_sha256"] == SOURCE_MANIFEST_SHA
             and t["original_test_parquet_sha256"] == TEST_SHA
             and t["production_accepted"] is False and t["authority"] == "DENY_ALL",
             "invalid withheld target source provenance")
        need(set(t["file_sha256s"]) == {"future_class_targets.jsonl",
                                               "future_caption_targets.jsonl"},
             "withheld target inventory changed")
        for name in t["file_sha256s"]:
            need(sha(tg.read(name)) == t["file_sha256s"][name],
                 "withheld publisher source digest mismatch")
        future = lines_strict(tg.read("future_class_targets.jsonl"))
        need(len(future) == 24, "incomplete withheld original labels")
        targets = {}
        for a, b in zip(held, future, strict=True):
            need(set(b) == {"case_id", "class_label", "group_id", "observed_at",
                            "scope", "source_input_sha256", "source_sha256"} and
                 b["case_id"] == a["case_id"] and b["class_label"] in CLASSES and
                 b["source_input_sha256"] == a["image_sha256"] and
                 b["source_sha256"] == a["source_sha256"] and
                 b["group_id"] == a["group_id"] and
                 b["observed_at"] == a["observed_at"] and b["scope"] == SCOPE,
                 "wrong source-bound held label")
            targets[b["case_id"]] = b
        return _manifest, train, held, {"train": labels, "held": targets}
    finally:
        src.close()
        tg.close()


def select_parquet(records: list[dict], phase: str) -> list[tuple]:
    """Independently reconstruct original publisher's deterministic selection.

    The stage never calls this; source/publisher labels are evaluator-only.
    """
    need(phase in ("train", "test") and 100 <= len(records) <= 10000,
         "invalid publisher phase/scope")
    per_class = {0: [], 1: [], 2: []}
    for index, obj in enumerate(records):
        need(type(obj) is dict and set(obj) == {"image_file_path", "image", "labels"}
             and type(obj["labels"]) is int and obj["labels"] in per_class and
             type(obj["image"]) is dict and set(obj["image"]) == {"bytes", "path"},
             "malformed publisher row")
        raw = obj["image"]["bytes"]
        need(type(raw) is bytes and 50 < len(raw) <= 3_000_000,
             "bad publisher image payload")
        imgsha = sha(raw)
        priority = sha(canonical(["e2.beans.shuffle-by-image.v1", phase, imgsha, index]))
        per_class[obj["labels"]].append((priority, index, imgsha))
    count = 12 if phase == "train" else 8
    out = []
    for label in range(3):
        need(len(per_class[label]) >= count, "publisher class incomplete")
        out.extend((label, idx, img) for _, idx, img in sorted(per_class[label])[:count])
    return out


def verify_publisher_parquets(train_path: str | Path, test_path: str | Path,
                              train: list[dict], held: list[dict],
                              originals: dict[str, Any]) -> None:
    """Reviewer-only physical original train+test publisher labels reselect."""
    import pyarrow.parquet as pq  # Import only when reviewer has original labels.
    for path, phase, expected, cap, rows in (
        (train_path, "train", TRAIN_SHA, 150_000_000, train),
        (test_path, "test", TEST_SHA, 20_000_000, held),
    ):
        path = Path(path)
        need(path.is_file() and not path.is_symlink() and 0 < path.stat().st_size <= cap,
             "missing original publisher parquet")
        with path.open("rb") as f:
            need(hashlib.file_digest(f, "sha256").hexdigest() == expected,
                 "incorrect original publisher bytes")
        selected = select_parquet(pq.read_table(path).to_pylist(), phase)
        need(len(selected) == len(rows), "reselected original population mismatch")
        for ordinal, ((label, original_index, img_sha), rec) in enumerate(zip(selected, rows, strict=True)):
            phase_name = "train" if phase == "train" else "future"
            case_id = "beans-" + sha(canonical(["hepta.beans.real-image.v1",phase_name,
                                                original_index,img_sha]))[:24]
            group_id = "origin-" + sha(canonical(["hepta.beans.source-group.v1",
                                                 phase_name,original_index]))[:24]
            need(rec["case_id"] == case_id and rec["group_id"] == group_id and
                 rec["image_sha256"] == img_sha,
                 "publisher case identity/byte selected incorrectly")
            truth = originals["train"][case_id] if phase == "train" else originals["held"][case_id]["class_label"]
            need(truth == CLASSES[label], "original published source target changed")


def scored_stats(trial: dict, bank: dict, original_labels: dict,
                 original_features: PinnedZip) -> dict:
    """Independent five-arm paired outcomes, plus strong original vision reference."""
    from paired_utility_gate import audit_paired_utility
    from physical_bank import digest
    targets = []
    original_held = original_labels["held"]
    for row in bank["held"]:
        key = row["id"]
        need(key in original_held, "missing publisher label")
        targets.append({"id": key, "family": row["family"], "type": row["type"],
                        "target": int(original_held[key]["class_label"] == "healthy")})
    withheld = {"schema": "hepta.hdcf.blind-targets.v1",
                "bundle_digest": digest(bank), "targets": targets}
    paired = audit_paired_utility(bank, trial, withheld)
    # Independently replay the predecessor's original 3-way class predictions
    # against re-admitted publisher class targets (without trusting 20/24 summary).
    sealed = json_strict(original_features.read("sealed_class_predictions.json"))
    need(sealed["schema"] == "hepta.e2.beans-natural-retrospective.v1.class-predictions"
         and sealed["future_labels_seen"] is False and
         sealed["production_accepted"] is False and
         sealed["authority"] == "DENY_ALL" and
         len(sealed["rows"]) == 24,
         "archived visual prototype identity mismatch")
    prototype = {}
    original_counts = {k: 0 for k in sealed["arms"]}
    need(set(original_counts) == {"fitted", "rotated_target_control",
                                  "unaligned_identity", "vision_prototype"},
         "original four-arm controls missing")
    for row in sealed["rows"]:
        k = row["case_id"]
        need(k in original_held and k not in prototype and
             row["source_input_sha256"] == original_held[k]["source_input_sha256"] and
             row["group_id"] == original_held[k]["group_id"] and
             row["scope"] == SCOPE and
             set(row["predicted_labels"]) == set(original_counts),
             "archived source/vision-prototype case mismatch")
        gold = original_held[k]["class_label"]
        for mode, predicted in row["predicted_labels"].items():
            need(predicted in CLASSES, "bad frozen vision output label")
            original_counts[mode] += int(predicted == gold)
        prototype[k] = int(row["predicted_labels"]["vision_prototype"] == "healthy")
    need(len(prototype) == len(original_held) and original_counts["vision_prototype"] == 20,
         "incorrect inherited original 3-class baseline")
    # We independently compute task-relabelled reference rather than comparing
    # incompatible 3-class original accuracy to this new binary task.
    expected_arms = {"frozen", "shared_dense", "shared_one_touch", "split", "swapped"}
    need(set(trial["predictions"]) == expected_arms, "incomplete physical Head census")
    control = {}
    for mode in sorted(expected_arms):
        hits, wins, losses = 0, 0, 0
        for row in trial["predictions"][mode]:
            k = row["id"]
            need(k in prototype, "unknown held case in Cell prediction")
            true = int(original_held[k]["class_label"] == "healthy")
            guessed = int(row["p1"] >= .5)
            reference = prototype[k]
            hits += guessed == true
            wins += guessed == true and reference != true
            losses += guessed != true and reference == true
        control[mode] = {"correct": hits, "wins_vs_pretrained_vision_prototype": wins,
                         "losses_vs_pretrained_vision_prototype": losses}
    # Equal-labeled, equal-source diagnostic: Split vs equal-touch Shared.
    from paired_utility_gate import _mcnemar_exact
    by_name = {name: {r["id"]: int(r["p1"] >= .5) for r in rows}
               for name, rows in trial["predictions"].items()}
    wins = losses = both = neither = 0
    for key, record in original_held.items():
        truth = int(record["class_label"] == "healthy")
        split = by_name["split"][key] == truth
        shared = by_name["shared_one_touch"][key] == truth
        wins += bool(split and not shared)
        losses += bool(shared and not split)
        both += bool(split and shared)
        neither += bool(not split and not shared)
    split_vs_shared = {"split_only_correct": wins, "shared_only_correct": losses,
                       "both_correct": both, "both_incorrect": neither,
                       "nominal_two_sided_exact_mcnemar": _mcnemar_exact(wins, losses),
                       "source_independent": False, "efficacy_certified": False}
    return {"paired": paired, "split_vs_shared": split_vs_shared,
            "original_three_class_counts": original_counts,
            "binary_vision_prototype_correct": sum(prototype[k] ==
                      int(v["class_label"] == "healthy") for k,v in original_held.items()),
            "reclassified_binary_correct": control}


def rejudge(bank_doc: dict, trial_doc: dict, source_zip: str | Path,
            feature_zip: str | Path, target_zip: str | Path,
            original_train: str | Path, original_test: str | Path) -> dict:
    """Reviewer has publisher labels only AFTER model trial is sealed."""
    from physical_bank import validate_bundle, digest
    _s, train, held, lab = _source_targets(source_zip, target_zip)
    verify_publisher_parquets(original_train, original_test, train, held, lab)
    expected = stage(source_zip, feature_zip)
    need(digest(expected) == digest(bank_doc), "trainer bank changed after source sealing")
    validate_bundle(bank_doc)
    feature = PinnedZip(feature_zip, FEATURE_ZIP_SHA)
    try:
        scores = scored_stats(trial_doc, bank_doc, lab, feature)
    finally:
        feature.close()
    # Ensure the source-independent evaluator never claims promotion. Only
    # pre-existing real model work is observed; new experiment did SGD only.
    arms = {mode: {"correct": vals["correct"],
                   "wins_vs_pretrained_vision_prototype": vals["wins_vs_pretrained_vision_prototype"],
                   "losses_vs_pretrained_vision_prototype": vals["losses_vs_pretrained_vision_prototype"]}
            for mode, vals in scores["reclassified_binary_correct"].items()}
    counts = {k: {"steps": v["actual_sgd_steps"], "estimated_parameter_touches":v["estimated_parameter_touches"]}
              for k,v in trial_doc["arms"].items()}
    model = PinnedZip(feature_zip, FEATURE_ZIP_SHA)
    try:
        original_model_wall = sum(json_strict(model.read(k))["wall_ns"] for k in
                                  ("vision_train/receipt.json", "vision_future/receipt.json"))
    finally:
        model.close()
    return {"schema": "hepta.hdcf.original-beans-dino-v9-readout.v1",
            "source_run_id": ORIGINAL_RUN_ID, "model": "facebook/dinov2-small",
            "model_revision": MODEL_REV, "original_dino_image_forwards_reported": 60,
            "original_dino_forward_wall_ns_reported": original_model_wall,
            "new_dino_image_forwards": 0, "genuine_original_train_cases": 36,
            "genuine_original_held_cases": 24, "binary_task": TASK,
            "original_publisher_train_test_sha_verified": True,
            "source_original_images_sha_verified": True,
            "source_independent_issuers": False,
            "chronological_future": False,
            "publisher_origin_signature_verified": False,
            "original_three_class_counts": scores["original_three_class_counts"],
            "binary_original_visual_prototype_correct": scores["binary_vision_prototype_correct"],
            "head_arms": arms, "paid_head_work": counts,
            "matched_split_vs_shared_one_touch": scores["split_vs_shared"],
            "total_service_cost_attested": False,
            "independent_future_NDU_utility": False,
            "production_authorized": False, "model_selected": False,
            "disposition": "HOLD_NO_GO_DENY_ALL"}


def download_original(kind: str, output: str | Path, token: str) -> None:
    """Fetch exact GitHub Actions ZIP; never forward GH auth to CDN host.

    Only callable by an explicitly read-only GitHub Actions worker.
    Secrets never enter stdout, artifacts or destination filenames.
    """
    from urllib.error import HTTPError
    from urllib.parse import urlsplit
    from urllib.request import HTTPRedirectHandler, Request, build_opener

    expected = {"source": (SOURCE_ARTIFACT_ID, SOURCE_ZIP_SHA),
                "features": (FEATURE_ARTIFACT_ID, FEATURE_ZIP_SHA),
                "targets": (TARGET_ARTIFACT_ID, TARGET_ZIP_SHA)}
    need(kind in expected and type(token) is str and len(token) >= 16,
         "invalid authenticated original download")
    artifact_id, known_sha = expected[kind]

    class NoRedirect(HTTPRedirectHandler):
        def redirect_request(self, req, fp, code, msg, headers, newurl):
            return None

    opener = build_opener(NoRedirect())
    initial = "https://api.github.com/repos/TrillionniumFoundation/hepta-private-ci/actions/artifacts/" + str(artifact_id) + "/zip"
    try:
        opener.open(Request(initial, headers={
            "Authorization": "Bearer " + token,
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "hepta-hdcf-original-v9-readonly"}), timeout=45)
    except HTTPError as e:
        need(e.code in (301, 302, 303, 307, 308) and e.headers.get("Location"),
             "GitHub archive did not return known redirect")
        location = e.headers["Location"]
    else:
        raise Reject("unexpected authenticated ZIP direct response")
    parsed = urlsplit(location)
    need(parsed.scheme == "https" and parsed.hostname not in
         ("api.github.com", "github.com") and parsed.username is None and
         parsed.password is None and len(location) < 8192,
         "untrusted GitHub Actions archive redirect")
    # Deliberately NO auth/cookies on the signed CDN request.
    with opener.open(Request(location, headers={
        "Accept": "application/zip",
        "User-Agent": "hepta-hdcf-original-v9-readonly"}), timeout=90) as response:
        path = Path(output)
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL |
                     getattr(os, "O_NOFOLLOW", 0), 0o600)
        try:
            with os.fdopen(fd, "wb") as stream:
                total = 0
                digest = hashlib.sha256()
                while block := response.read(1024 * 1024):
                    total += len(block)
                    need(total <= MAX_ZIP_BYTES, "oversized signed original ZIP")
                    digest.update(block)
                    stream.write(block)
                stream.flush()
                os.fsync(stream.fileno())
        except BaseException:
            path.unlink(missing_ok=True)
            raise
        if not (total > 0 and digest.hexdigest() == known_sha):
            path.unlink(missing_ok=True)
            raise Reject("authenticated original ZIP has wrong SHA256")


def main(argv=None):
    from physical_cli import read_document, write_once
    p=argparse.ArgumentParser()
    sub=p.add_subparsers(dest="command",required=True)
    a=sub.add_parser("stage")
    a.add_argument("--source-zip",required=True)
    a.add_argument("--features-zip",required=True)
    a.add_argument("--out",required=True)
    b=sub.add_parser("review")
    for flag in ("bank", "trial", "source-zip", "features-zip", "targets-zip",
                 "publisher-train", "publisher-test", "out"):
        b.add_argument("--"+flag,required=True)
    c=sub.add_parser("download")
    c.add_argument("--kind", choices=("source", "features", "targets"), required=True)
    c.add_argument("--out",required=True)
    args=p.parse_args(argv)
    try:
        if args.command == "download":
            download_original(args.kind, args.out, os.environ.get("GH_TOKEN", ""))
            return 0
        if args.command == "stage":
            result = stage(args.source_zip,args.features_zip)
        else:
            result = rejudge(read_document(args.bank), read_document(args.trial),
                             args.source_zip,args.features_zip,args.targets_zip,
                             args.publisher_train,args.publisher_test)
        write_once(args.out, result)
    except (Reject, OSError, ValueError, KeyError, TypeError) as ex:
        p.exit(2,f"DENY_ALL: {type(ex).__name__}: {ex}\n")
    return 0


if __name__=="__main__":
    raise SystemExit(main())
