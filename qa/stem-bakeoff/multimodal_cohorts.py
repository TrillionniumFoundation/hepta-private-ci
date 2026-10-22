"""Pinned real COCO photos/human captions with disjoint balanced pair blocks.

Labels describe original caption-image provenance. A caption from another
photo is not necessarily a semantic contradiction. No model chooses samples.
"""

import argparse
from collections import Counter
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import unicodedata
from urllib.request import Request, urlopen
import zipfile

from PIL import Image, ImageOps

ARCHIVE_URL = "https://s3.amazonaws.com/images.cocodataset.org/annotations/annotations_trainval2017.zip"
ARCHIVE_BYTES = 252907541
ARCHIVE_SHA256 = "113a836d90195ee1f884e704da6304dfaaecff1f023f49b6ca93c4aaae470268"
CAPTION_MEMBER = "annotations/captions_val2017.json"
CAPTIONS_SHA256 = "afe3b30e403dd7f228e2373023abbd60042a6e10ec6874d3652df034d289ebb9"
CAPTIONS_FILE = "source_captions_val2017.json"
SOURCE_SAMPLE = Path(__file__).with_name("coco_caption_sample_v1.json")
SOURCE_SAMPLE_SHA256 = "bdcd27245d5435820ddd6ef305b42bdeca236e4411839f1d209d314547567b23"
SPLIT_IMAGES = {"train": 128, "dev": 64, "calibration": 64, "test": 128}
SEED = "hepta-coco-pair-v1-20261022"
ALLOWED_LICENSES = (4, 5)
NEAR_DUPLICATE_DISTANCE = 4
MAX_DOWNLOAD_BYTES = 400_000_000
MAX_IMAGE_BYTES = 2 * 1024 * 1024
MAX_JSON_BYTES = 8 * 1024 * 1024
TERMS_URL = "https://cocodataset.org/dataset/termsofuse.htm"


class MultimodalDataError(ValueError):
    pass


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"), allow_nan=False).encode()


def sha(payload):
    return hashlib.sha256(payload).hexdigest()


def _regular(path, limit):
    path = Path(path)
    if any(p.is_symlink() for p in (path, *path.parents)):
        raise MultimodalDataError("dataset paths cannot traverse symlinks")
    info = path.stat()
    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or not 0 < info.st_size <= limit:
        raise MultimodalDataError("unaliased bounded regular dataset file required")
    return info


def read_bytes(path, limit=MAX_JSON_BYTES):
    before = _regular(path, limit)
    with Path(path).open("rb") as stream:
        payload = stream.read(limit + 1)
    after = _regular(path, limit)
    if (len(payload) != before.st_size or (before.st_ino, before.st_mtime_ns, before.st_ctime_ns)
            != (after.st_ino, after.st_mtime_ns, after.st_ctime_ns)):
        raise MultimodalDataError("dataset file changed while reading")
    return payload


def verify_archive(path):
    info = _regular(path, ARCHIVE_BYTES)
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    if info.st_size != ARCHIVE_BYTES or digest.hexdigest() != ARCHIVE_SHA256:
        raise MultimodalDataError("COCO archive differs from the official fixed release bytes")
    with zipfile.ZipFile(path) as archive:
        entry = archive.getinfo(CAPTION_MEMBER)
        if entry.file_size > MAX_JSON_BYTES:
            raise MultimodalDataError("caption member exceeds budget")
        raw = archive.read(entry)
    if sha(raw) != CAPTIONS_SHA256:
        raise MultimodalDataError("original human caption member hash mismatch")
    return raw, json.loads(raw)


def candidate_sources(data):
    """A model-independent order and one original caption per image."""
    captions = {}
    for item in data["annotations"]:
        captions.setdefault(item["image_id"], []).append(item)
    licenses = {item["id"]: item for item in data["licenses"]}
    ordered = sorted(data["images"], key=lambda x: sha(f"{SEED}:image:{x['id']}".encode()))
    for image in ordered:
        if image["license"] not in ALLOWED_LICENSES or image["id"] not in captions:
            continue
        caption = min(captions[image["id"]],
                      key=lambda x: sha(f"{SEED}:caption:{x['id']}".encode()))
        yield {"image_id": image["id"], "file_name": image["file_name"],
               "width": image["width"], "height": image["height"],
               "license": licenses[image["license"]], "flickr_url": image["flickr_url"],
               "coco_url": image["coco_url"], "download_url":
               f"https://s3.amazonaws.com/images.cocodataset.org/val2017/{image['file_name']}",
               "caption_id": caption["id"], "text": caption["caption"],
               "text_sha256": sha(caption["caption"].encode())}


def normalized_caption(text):
    return " ".join(unicodedata.normalize("NFKC", text).casefold().split())


def image_fingerprint(path, source):
    """Hashes and a declared dHash screen; no learned or semantic image judge."""
    payload = read_bytes(path, MAX_IMAGE_BYTES)
    with Image.open(path) as opened:
        if (opened.format != "JPEG" or opened.size != (source["width"], source["height"])
                or opened.width * opened.height > 4_194_304):
            raise MultimodalDataError("photo format/dimensions differ from COCO source")
        rgb = ImageOps.exif_transpose(opened).convert("RGB")
        pixels = rgb.tobytes()
        tiny = list(rgb.convert("L").resize((9, 8), Image.Resampling.LANCZOS).getdata())
        dhash = 0
        for y in range(8):
            for x in range(8):
                dhash = (dhash << 1) | int(tiny[y * 9 + x] > tiny[y * 9 + x + 1])
    return {"image_sha256": sha(payload), "image_bytes": len(payload),
            "decoded_rgb_sha256": sha(canonical([rgb.width, rgb.height, "RGB"]) + pixels),
            "dhash64": f"{dhash:016x}"}


def fetch_file(url, path, *, expected_sha256=None, expected_bytes=None, limit=MAX_IMAGE_BYTES):
    """Public fixed-source acquisition; existing files are never overwritten."""
    path = Path(path)
    if path.exists() or path.is_symlink():
        info = _regular(path, limit)
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            while chunk := stream.read(1024 * 1024):
                digest.update(chunk)
        if ((expected_sha256 is not None and digest.hexdigest() != expected_sha256)
                or (expected_bytes is not None and info.st_size != expected_bytes)):
            raise MultimodalDataError("existing acquisition conflicts with source pin")
        return info.st_size
    if not url.startswith("https://s3.amazonaws.com/images.cocodataset.org/"):
        raise MultimodalDataError("only the official public COCO bucket is admitted")
    temporary = path.with_name(path.name + ".partial")
    digest, md5, total = hashlib.sha256(), hashlib.md5(), 0
    created = False
    try:
        with temporary.open("xb") as output:
            created = True
            with urlopen(Request(url, headers={"User-Agent": "Hepta-reproducible-research/1"}),
                         timeout=60) as response:
                etag = response.headers.get("ETag", "").strip('"')
                while chunk := response.read(1024 * 1024):
                    total += len(chunk)
                    if total > limit:
                        raise MultimodalDataError("COCO download exceeds fixed byte budget")
                    digest.update(chunk)
                    md5.update(chunk)
                    output.write(chunk)
        if ((expected_sha256 is not None and digest.hexdigest() != expected_sha256)
                or (expected_bytes is not None and total != expected_bytes)
                or (re.fullmatch(r"[0-9a-f]{32}", etag) and md5.hexdigest() != etag)):
            raise MultimodalDataError("COCO download does not match its pinned bytes/ETag")
        os.link(temporary, path, follow_symlinks=False)
        return total
    finally:
        if created:
            temporary.unlink(missing_ok=True)


def _source_sample(data):
    raw = read_bytes(SOURCE_SAMPLE)
    if sha(raw) != SOURCE_SAMPLE_SHA256:
        raise MultimodalDataError("fixed COCO sample registry changed")
    pin = json.loads(raw)
    if (pin["archive_sha256"] != ARCHIVE_SHA256 or pin["captions_sha256"] != CAPTIONS_SHA256
            or pin["split_images"] != SPLIT_IMAGES or pin["selection_seed"] != SEED
            or len(pin["images"]) != sum(SPLIT_IMAGES.values())):
        raise MultimodalDataError("sample registry plan differs from fixed cohort")
    candidates = {item["image_id"]: item for item in candidate_sources(data)}
    seen_ids, seen_captions, seen_pixels, previous = set(), set(), set(), []
    for record in pin["images"]:
        source = candidates.get(record["image_id"])
        if source is None or any(record.get(key) != value for key, value in source.items()):
            raise MultimodalDataError("selected photo/caption is not the original pinned annotation")
        text_key = normalized_caption(record["text"])
        if (record["image_id"] in seen_ids or text_key in seen_captions
                or record["decoded_rgb_sha256"] in seen_pixels
                or any((int(record["dhash64"], 16) ^ old).bit_count()
                       <= NEAR_DUPLICATE_DISTANCE for old in previous)):
            raise MultimodalDataError("duplicate/near-duplicate source groups in sample registry")
        seen_ids.add(record["image_id"])
        seen_captions.add(text_key)
        seen_pixels.add(record["decoded_rgb_sha256"])
        previous.append(int(record["dhash64"], 16))
    ordered = sorted(pin["images"], key=lambda x: sha(f"{SEED}:image:{x['image_id']}".encode()))
    if ordered != pin["images"]:
        raise MultimodalDataError("sample registry order differs from the fixed hash order")
    if ARCHIVE_BYTES + sum(x["image_bytes"] for x in ordered) > MAX_DOWNLOAD_BYTES:
        raise MultimodalDataError("fixed source acquisition exceeds 400 MB")
    return pin


def build_rows(pin):
    """Two-photo transpositions: four rows and balanced marginals per block."""
    result, offset = {}, 0
    for split, count in SPLIT_IMAGES.items():
        images = pin["images"][offset:offset + count]
        offset += count
        if count % 2:
            raise MultimodalDataError("split requires complete independent two-photo blocks")
        rows = []
        for index in range(0, count, 2):
            a, b = images[index:index + 2]
            block = sha(canonical({"seed": SEED, "split": split,
                                   "image_ids": [a["image_id"], b["image_id"]]}))
            for image, caption, label in ((a, a, 1), (a, b, 0), (b, b, 1), (b, a, 0)):
                row = {"image_id": image["image_id"], "group_id": f"coco2017:{image['image_id']}",
                       "image_path": f"images/{image['file_name']}",
                       "image_sha256": image["image_sha256"], "caption_id": caption["caption_id"],
                       "text": caption["text"], "text_sha256": caption["text_sha256"],
                       "label": label, "source_caption_image_id": caption["image_id"],
                       "split": split, "pair_block_id": block}
                row["row_id"] = sha(canonical(row))
                rows.append(row)
        result[split] = sorted(rows, key=lambda row: sha((SEED + row["row_id"]).encode()))
    return result


def _manifest(pin, splits):
    return {"schema": "hepta.real-coco-pair-cohorts.v1", "release": "COCO-val2017",
            "archive_url": ARCHIVE_URL, "archive_sha256": ARCHIVE_SHA256,
            "captions_sha256": CAPTIONS_SHA256, "source_sample_sha256": SOURCE_SAMPLE_SHA256,
            "selection_seed": SEED, "split_images": SPLIT_IMAGES, "splits": splits,
            "source_sample": pin, "planned_source_download_bytes":
            ARCHIVE_BYTES + sum(row["image_bytes"] for row in pin["images"]),
            "source_labels": "original caption-image provenance; negatives may be semantically compatible",
            "near_duplicate_screen": {"algorithm": "64-bit horizontal dHash", "max_hamming": 4,
                "exact_rgb_hash_checked": True, "real_world_entity_disjointness_attested": False},
            "foundation_pretraining_contamination_excluded": False,
            "model_outputs_used_for_sampling": False, "quality_qualified": False,
            "authority": "DENY_ALL", "production_activation_allowed": False}


def prepare_cohorts(*, archive, output, download_images=False, image_cache=None):
    raw, data = verify_archive(archive)
    pin = _source_sample(data)
    destination = Path(output).absolute()
    if any(p.is_symlink() for p in (destination, *destination.parents)):
        raise MultimodalDataError("output may not traverse symlinks")
    destination.mkdir(mode=0o700, parents=False, exist_ok=False)
    (destination / "images").mkdir(mode=0o700)
    (destination / CAPTIONS_FILE).write_bytes(raw)
    for record in pin["images"]:
        target = destination / "images" / record["file_name"]
        if image_cache is not None:
            original = Path(image_cache) / record["file_name"]
            target.write_bytes(read_bytes(original, MAX_IMAGE_BYTES))
        elif download_images:
            fetch_file(record["download_url"], target, expected_sha256=record["image_sha256"],
                       expected_bytes=record["image_bytes"])
        else:
            raise MultimodalDataError("provide a verified image cache or explicitly enable public acquisition")
        if any(record[key] != value for key, value in image_fingerprint(target, record).items()):
            raise MultimodalDataError("photo bytes/decoded identity differ from fixed source sample")
    rows = build_rows(pin)
    splits = {}
    for name, values in rows.items():
        payload = b"".join(canonical(row) + b"\n" for row in values)
        (destination / f"{name}.jsonl").write_bytes(payload)
        splits[name] = {"rows": len(values), "images": SPLIT_IMAGES[name],
                        "pair_blocks": SPLIT_IMAGES[name] // 2, "jsonl_sha256": sha(payload),
                        "labels": dict(Counter(str(row["label"]) for row in values))}
    manifest = _manifest(pin, splits)
    (destination / "manifest.json").write_bytes(canonical(manifest) + b"\n")
    load_cohorts(destination, expected_manifest_sha256=sha(canonical(manifest) + b"\n"))
    return manifest


def load_cohorts(directory, *, expected_manifest_sha256=None):
    """Replay pinned source captions and pairing; never trust self-edited labels."""
    root = Path(directory)
    raw = read_bytes(root / "manifest.json")
    if expected_manifest_sha256 is not None and sha(raw) != expected_manifest_sha256:
        raise MultimodalDataError("cohort manifest hash mismatch")
    manifest = json.loads(raw)
    captions = read_bytes(root / CAPTIONS_FILE)
    if sha(captions) != CAPTIONS_SHA256:
        raise MultimodalDataError("original human caption source was modified")
    pin = _source_sample(json.loads(captions))
    if (manifest.get("source_sample") != pin or manifest.get("source_sample_sha256") != SOURCE_SAMPLE_SHA256
            or manifest.get("split_images") != SPLIT_IMAGES or manifest.get("selection_seed") != SEED
            or manifest.get("archive_sha256") != ARCHIVE_SHA256
            or manifest.get("captions_sha256") != CAPTIONS_SHA256):
        raise MultimodalDataError("cohort manifest disagrees with immutable source registry")
    for record in pin["images"]:
        observed = image_fingerprint(root / "images" / record["file_name"], record)
        if any(record[key] != value for key, value in observed.items()):
            raise MultimodalDataError("photo bytes/decoded source changed")
    expected = build_rows(pin)
    split_records = {}
    for name, values in expected.items():
        payload = read_bytes(root / f"{name}.jsonl")
        actual = [json.loads(line) for line in payload.splitlines()]
        statistics = {"rows": len(values), "images": SPLIT_IMAGES[name],
                      "pair_blocks": SPLIT_IMAGES[name] // 2, "jsonl_sha256": sha(payload),
                      "labels": dict(Counter(str(row["label"]) for row in values))}
        if actual != values or manifest.get("splits", {}).get(name) != statistics:
            raise MultimodalDataError("rows/labels/blocks do not replay from original caption sources")
        split_records[name] = statistics
    if manifest != _manifest(pin, split_records):
        raise MultimodalDataError("cohort claims do not match replayed source evidence")
    return manifest, expected


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--download-images", action="store_true")
    parser.add_argument("--image-cache")
    args = parser.parse_args()
    result = prepare_cohorts(archive=args.archive, output=args.output,
                             download_images=args.download_images, image_cache=args.image_cache)
    print(json.dumps({"status": "PREPARED", "output": args.output,
                      "splits": result["splits"], "quality_qualified": False}, sort_keys=True))


if __name__ == "__main__":
    main()
