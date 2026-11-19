"""Pinned raw COCO bytes -> independent slots and separate real EG2 targets.

These source groups were used in earlier pairing experiments. This is an
exploratory reuse, not fresh blind, temporal or out-of-distribution evaluation.
"""

from dataclasses import replace
import hashlib
import io
import json
from pathlib import Path
import stat

import numpy as np
from PIL import Image, ImageOps
import torch

from cell_evolution_snapshot import digest
from feature_shard import write_shard
from offline_shard_distill import PairedCohort, SPLITS
from shared_student_training import TEACHER, TEACHER_INVENTORY, TEACHER_REVISION, tensor_sha

DATASET_SHA256 = "4d7eec98a8546f8af64b0a5f2b4f192b30c6c43cb086f73f67bb0793a4509d63"
BANK_SHA256 = "e620c7ac8264979136cf39d992ddd575ab37c71baa6a729269af41bc42ca290d"
FEATURE_FILE_SHA256 = "1a4458c0d065d697ae491190ec00c0d30b29b8bc853cb96400d9ed1d432941ae"
ROLE_NAMES = {"train": "original_train", "calibration": "original_calibration",
              "future_1": "original_dev", "future_2": "original_test_A", "ood": "original_test_B"}
RECIPE = {
    "schema": "hepta.independent-coco-slots.v1", "shape": [32, 64], "dtype": "float32",
    "image": "EXIF-oriented RGB; bilinear 16x16 resize; row-major sixteen 4x4x3 patches in slots 0..15",
    "image_channels": "RGB/127.5-1 in 0..47; modality +1 at 48; grid x,y normalized to [-1,1] at 49,50",
    "text": "caption UTF-8 first 256 bytes; sixteen 16-byte chunks in slots 16..31",
    "text_channels": "byte/127.5-1 in 0..15; valid-byte flags in 16..31; modality -1 at 48; chunk position at 49",
    "presence": "channel 63 is one for present slots; absent slots all zero; student attention masks absent slots",
    "targets": "concatenate separately encoded real EG2 image-global[768], text-global[768]; width 1536",
    "selection": "sort each original split by SHA256('hepta-shared-tiny-v1:'+decimal image_id); first 8, test first16 split8+8",
    "labels_source_ids_or_teacher_features_enter_student_inputs": False,
    "control_inputs": {"multimodal": "all raw slots", "image_only": "zero text slots", "text_only": "zero image slots"},
}


def sha(data):
    return hashlib.sha256(data).hexdigest()


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def pinned_bytes(path, expected, limit=8 * 1024 * 1024):
    path = Path(path)
    if any(p.is_symlink() for p in (path, *path.parents)):
        raise ValueError("raw source path traverses a symlink")
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or not 0 < info.st_size <= limit:
        raise ValueError("raw source file boundary differs")
    data = path.read_bytes()
    if len(data) != info.st_size or sha(data) != expected:
        raise ValueError("raw source bytes differ from retained pin")
    return data


def select_sources(raw_root):
    root = Path(raw_root)
    manifest = json.loads(pinned_bytes(root / "manifest.json", DATASET_SHA256))
    sources = {r["image_id"]: r for r in manifest["source_sample"]["images"]}
    if len(sources) != 384:
        raise ValueError("original raw image roster differs")
    original, seen = {}, set()
    for split, expected in (("train", 128), ("calibration", 64), ("dev", 64), ("test", 128)):
        rows = [json.loads(line) for line in pinned_bytes(root / (split + ".jsonl"),
                manifest["splits"][split]["jsonl_sha256"]).splitlines()]
        ids = {r["image_id"] for r in rows}
        if len(ids) != expected or seen & ids:
            raise ValueError("original source groups overlap or changed size")
        for row in rows:
            caption = sources[row["source_caption_image_id"]]
            if (row["group_id"] != f"coco2017:{row['image_id']}"
                    or row["source_caption_image_id"] not in ids
                    or row["text"] != caption["text"] or row["caption_id"] != caption["caption_id"]
                    or row["image_sha256"] != sources[row["image_id"]]["image_sha256"]):
                raise ValueError("image or caption escaped its original source split")
        original[split] = sorted(ids, key=lambda i: sha(("hepta-shared-tiny-v1:" + str(i)).encode()))
        seen.update(ids)
    if seen != set(sources):
        raise ValueError("original source partition is incomplete")
    selected = {"train": original["train"][:8], "calibration": original["calibration"][:8],
        "future_1": original["dev"][:8], "future_2": original["test"][:8], "ood": original["test"][8:16]}
    return {role: [sources[i] for i in selected[role]] for role in SPLITS}


def source_digest(source, channel):
    # Reproduce real_encoder.encode_records' original text/media binding.
    text = source["text"] if channel == "text" else "Image."
    metadata = {"image_id": source["image_id"], "caption_id": source["caption_id"],
        "source_image_sha256": source["image_sha256"], "source_caption_sha256": source["text_sha256"],
        "channel": channel}
    media = [["text", sha(text.encode())]]
    if channel == "image":
        media.append(["image", source["image_sha256"]])
    return sha(canonical({"text_source": sha(canonical({"text": text, "record": metadata})), "media_sources": media}))


def raw_slots(image_bytes, source):
    if sha(image_bytes) != source["image_sha256"] or sha(source["text"].encode()) != source["text_sha256"]:
        raise ValueError("student raw input bytes do not match original source")
    with Image.open(io.BytesIO(image_bytes)) as opened:
        if (opened.format != "JPEG" or opened.size != (source["width"], source["height"])
                or opened.width * opened.height > 4_194_304):
            raise ValueError("raw image decoder boundary differs")
        rgb = ImageOps.exif_transpose(opened).convert("RGB")
        if sha(canonical([rgb.width, rgb.height, "RGB"]) + rgb.tobytes()) != source["decoded_rgb_sha256"]:
            raise ValueError("decoded original image pin differs")
        pixels = np.asarray(rgb.resize((16, 16), Image.Resampling.BILINEAR), dtype=np.float32)
    slots = np.zeros((32, 64), dtype=np.float32)
    for y in range(4):
        for x in range(4):
            row = slots[4 * y + x]
            row[:48] = pixels[4*y:4*y+4, 4*x:4*x+4].reshape(-1) / 127.5 - 1
            row[48:51] = [1, x / 1.5 - 1, y / 1.5 - 1]
            row[63] = 1
    text = source["text"].encode()[:256]
    for index in range(16):
        chunk = np.frombuffer(text[index*16:(index+1)*16], dtype=np.uint8).astype(np.float32)
        if len(chunk):
            row = slots[16 + index]
            row[:len(chunk)] = chunk / 127.5 - 1
            row[16:16+len(chunk)] = 1
            row[48:50] = [-1, index / 7.5 - 1]
            row[63] = 1
    return torch.from_numpy(slots)


def load_teacher_bank(bank_root):
    root = Path(bank_root)
    manifest = json.loads(pinned_bytes(root / "manifest.json", BANK_SHA256))
    plan = manifest["plan"]  # The retained hash identifies canonical JSON, not file whitespace.
    if (sha(canonical(plan)) != manifest["plan_sha256"]
            or plan["candidate"] != TEACHER or plan["checkpoint_revision"] != TEACHER_REVISION
            or plan["checkpoint_inventory_sha256"] != TEACHER_INVENTORY
            or plan["dataset_manifest_sha256"] != DATASET_SHA256 or plan["labels_enter_model_inputs"] is not False
            or plan["image_neutral_prompt"] != "Image." or manifest["shape"] != [384, 768]
            or len(set(manifest["image_ids"])) != 384):
        raise ValueError("teacher identity or source declaration differs")
    data = pinned_bytes(root / "features.npz", FEATURE_FILE_SHA256)
    with np.load(io.BytesIO(data), allow_pickle=False) as archive:
        if set(archive.files) != {"image", "text"}:
            raise ValueError("teacher bank tensor roster differs")
        arrays = {name: archive[name].copy() for name in ("text", "image")}
    tensor_digest, receipts = hashlib.sha256(), {}
    for channel, value in arrays.items():
        if value.dtype != np.float32 or value.shape != (384, 768) or not np.isfinite(value).all():
            raise ValueError("teacher bank arrays invalid")
        tensor_digest.update(canonical([channel, str(value.dtype), list(value.shape)]))
        tensor_digest.update(value.tobytes())
        entry = manifest["receipts"][channel]
        receipts[channel] = json.loads(pinned_bytes(root / entry["file"], entry["sha256"]))
        offset = 0
        for row in receipts[channel]:
            count, bundle = row["batch_size"], row["bundle_manifest"]
            if (row["offset"] != offset or not 1 <= count <= 8 or offset + count > 384
                    or row["candidate"] != TEACHER or row["checkpoint_revision"] != TEACHER_REVISION
                    or row["checkpoint_inventory_sha256"] != TEACHER_INVENTORY
                    or row["source_ids"] != manifest["image_ids"][offset:offset+count]
                    or bundle["source_record_digests"] != manifest["provenance"][channel][offset:offset+count]
                    or bundle["views"]["global_features"]["bytes_sha256"] != sha(value[offset:offset+count].tobytes())):
                raise ValueError("teacher array rows do not match retained real forward receipts")
            offset += count
        if offset != 384:
            raise ValueError("teacher forward receipt coverage incomplete")
    if tensor_digest.hexdigest() != manifest["feature_tensor_sha256"]:
        raise ValueError("teacher bank aggregate tensor hash differs")
    return manifest, arrays, receipts


def make_inputs(raw_root, bank_root, selection, directory):
    if selection != select_sources(raw_root):
        raise ValueError("selection differs from fixed source-only rule")
    manifest, arrays, receipts = load_teacher_bank(bank_root)
    positions = {image: i for i, image in enumerate(manifest["image_ids"])}
    target = Path(directory)
    target.mkdir(parents=False, exist_ok=False)
    records, slots, targets = {}, {}, {}
    for role in SPLITS:
        records[role], raw, teacher = [], [], []
        for source in selection[role]:
            index = positions[source["image_id"]]
            origins = {channel: source_digest(source, channel) for channel in ("image", "text")}
            if any(origins[c] != manifest["provenance"][c][index] for c in origins):
                raise ValueError("teacher feature source does not match independent raw source")
            path = Path(raw_root) / "images" / source["file_name"]
            raw.append(raw_slots(pinned_bytes(path, source["image_sha256"]), source))
            teacher.append(np.concatenate([arrays["image"][index], arrays["text"][index]]))
            record = {k: source[k] for k in ("image_id", "caption_id", "image_sha256", "text_sha256")}
            record.update({"source_group_id": f"coco2017:{source['image_id']}",
                "teacher_image_source_sha256": origins["image"], "teacher_text_source_sha256": origins["text"]})
            records[role].append({**record, "source_record_sha256": digest(record)})
        slots[role], targets[role] = torch.stack(raw), torch.from_numpy(np.stack(teacher))
    input_manifest = {"schema": "hepta.shared-coco-independent-inputs.v1", "dataset_sha256": DATASET_SHA256,
        "teacher_bank_sha256": BANK_SHA256, "teacher_features_file_sha256": FEATURE_FILE_SHA256,
        "recipe": RECIPE, "role_names": ROLE_NAMES, "records": records, "raw_selected_sources": selection,
        "raw_slot_sha256": {k: tensor_sha(v) for k, v in slots.items()},
        "teacher_target_sha256": {k: tensor_sha(v) for k, v in targets.items()},
        "previously_used_pairing_bank": True, "new_blind_or_temporal_holdout": False,
        "authority": "DENY_ALL", "production_activation_allowed": False}
    payload = canonical(input_manifest) + b"\n"
    (target / "manifest.json").write_bytes(payload)
    np.savez(target / "raw_slots.npz", **{k: v.numpy() for k, v in slots.items()})
    cohorts = {}
    for role in SPLITS:
        shard = target / (role + "-teacher")
        receipt = write_shard(shard, targets[role], candidate=TEACHER, revision=TEACHER_REVISION,
            checkpoint_inventory_sha256=TEACHER_INVENTORY, ordered_source_manifest_sha256=digest(records[role]))
        cohorts[role] = PairedCohort(slots[role], shard, digest(records[role]), receipt["npy_sha256"],
            tensor_sha(slots[role]), tuple(r["source_record_sha256"] for r in records[role]))
    (target / "teacher-receipts.json").write_bytes(canonical(receipts) + b"\n")
    return cohorts, records, input_manifest, sha(payload)


def control_cohorts(cohorts, arm):
    if arm not in RECIPE["control_inputs"]:
        raise ValueError("unknown predeclared raw-input control")
    result = {}
    for name, cohort in cohorts.items():
        slots = cohort.slots.detach().clone()
        if arm == "image_only":
            slots[:, 16:] = 0
        elif arm == "text_only":
            slots[:, :16] = 0
        result[name] = replace(cohort, slots=slots, expected_slot_sha256=tensor_sha(slots))
    return result
