"""Fresh, source-disjoint COCO grounding tasks; actors receive observations only.

Boxes use normalized XYXY coordinates. References are evaluator-only. The
annotation screen is fixed before inference; synthetic fixtures are explicitly
marked and cannot establish real-image efficacy or pretraining independence.
"""

import argparse
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import math
from pathlib import Path
import re
from urllib.request import Request, urlopen

from PIL import Image, ImageOps

SPLITS = ("train", "dev", "calibration", "test")
DEFAULT_SIZES = (128, 32, 32, 64)
SEED = "hepta-grounded-generation-v1-20261022"
INSTANCES_SHA256 = "e8c7f7908f1d7278341fae127d0da654f102f11bd7b21d8aeefa635b8c810b6f"
ARCHIVE_URL = "https://s3.amazonaws.com/images.cocodataset.org/annotations/annotations_trainval2017.zip"
IMAGE_URL = "https://s3.amazonaws.com/images.cocodataset.org/val2017/"
DEFAULT_EXCLUSION = "/tmp/hepta-coco-cohorts-v1/manifest.json"
OBSERVATION_KEYS = {"task_id", "image_path", "image_sha256", "prompt", "target_category"}
REFERENCE_KEYS = {"task_id", "source_id", "image_size", "boxes", "label", "count", "largest_side"}


def canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False,
                      separators=(",", ":"), allow_nan=False).encode()


def sha(payload):
    return hashlib.sha256(payload).hexdigest()


def _source(path, fixture):
    raw = Path(path).read_bytes()
    if len(raw) > 32_000_000 or (not fixture and sha(raw) != INSTANCES_SHA256):
        raise ValueError("official instances_val2017.json source hash required")
    return json.loads(raw), sha(raw)


def _exclusions(path):
    if path is None:
        return [], None
    raw = Path(path).read_bytes()
    return json.loads(raw)["source_sample"]["images"], sha(raw)


def _largest_side(boxes):
    areas = [(b[2] - b[0]) * (b[3] - b[1]) for b in boxes]
    largest = max(areas)
    indices = [i for i, area in enumerate(areas) if math.isclose(area, largest, abs_tol=1e-12)]
    if len(indices) != 1:
        raise ValueError("ambiguous largest instance")
    box = boxes[indices[0]]
    center = (box[0] + box[2]) / 2
    if math.isclose(center, 0.5, abs_tol=1e-12):
        raise ValueError("largest instance is exactly centered")
    return "left" if center < 0.5 else "right"


def candidate_sources(data, excluded_ids=(), seed=SEED):
    """One category per image; every instance of that category is referenced."""
    categories = {row["id"]: row["name"] for row in data["categories"]}
    grouped = defaultdict(lambda: defaultdict(list))
    for ann in data["annotations"]:
        grouped[ann["image_id"]][ann["category_id"]].append(ann)
    for image in sorted(data["images"], key=lambda row: sha(f"{seed}:{row['id']}".encode())):
        iid, width, height = image["id"], image["width"], image["height"]
        if iid in excluded_ids or image.get("license") not in (4, 5) or min(width, height) <= 0:
            continue
        if image["file_name"] != f"{iid:012d}.jpg":
            raise ValueError("unexpected COCO source filename")
        order = sorted(grouped[iid], key=lambda cid: sha(f"{seed}:{iid}:{cid}".encode()))
        for cid in order:
            anns = sorted(grouped[iid][cid], key=lambda ann: ann["id"])
            if not 1 <= len(anns) <= 3 or any(ann.get("iscrowd", 0) for ann in anns):
                continue
            boxes = []
            for ann in anns:
                x, y, w, h = ann["bbox"]
                if (not all(math.isfinite(v) for v in (x, y, w, h)) or min(x, y) < 0
                        or min(w, h) <= 0 or x + w > width or y + h > height):
                    break
                boxes.append([x / width, y / height, (x + w) / width, (y + h) / height])
            if len(boxes) != len(anns) or max((b[2]-b[0])*(b[3]-b[1]) for b in boxes) < 0.04:
                continue
            try:
                side = _largest_side(boxes)
            except ValueError:
                continue
            task_id = "ggv1_" + sha(f"{seed}:{iid}:{cid}".encode())[:24]
            reference = {"task_id": task_id, "source_id": f"coco:val2017:{iid}",
                         "image_size": [width, height], "boxes": boxes,
                         "label": categories[cid], "count": len(boxes), "largest_side": side}
            yield image, reference, [ann["id"] for ann in anns]
            break


def image_fingerprint(path, size):
    raw = Path(path).read_bytes()
    if not 0 < len(raw) <= 3_000_000:
        raise ValueError("image exceeds bounded COCO image size")
    with Image.open(path) as image:
        if image.format != "JPEG" or list(image.size) != list(size):
            raise ValueError("image format or dimensions differ from annotation")
        rgb = ImageOps.exif_transpose(image).convert("RGB")
        tiny = list(rgb.convert("L").resize((9, 8), Image.Resampling.LANCZOS).getdata())
        bits = 0
        for y in range(8):
            for x in range(8):
                bits = (bits << 1) | int(tiny[y * 9 + x] > tiny[y * 9 + x + 1])
        return {"image_sha256": sha(raw), "image_bytes": len(raw), "dhash64": f"{bits:016x}",
                "decoded_rgb_sha256": sha(canonical([rgb.width, rgb.height, "RGB"]) + rgb.tobytes())}


def _duplicate(fingerprint, previous):
    return any(fingerprint["image_sha256"] == old["image_sha256"]
               or fingerprint["decoded_rgb_sha256"] == old["decoded_rgb_sha256"]
               or (int(fingerprint["dhash64"], 16) ^ int(old["dhash64"], 16)).bit_count() <= 4
               for old in previous)


def _fetch(path, download_images):
    if path.is_symlink():
        raise ValueError("image cache must not contain symlinks")
    if path.exists():
        return
    if not download_images:
        raise FileNotFoundError(f"missing cached photo {path}; pass --download-images")
    url = IMAGE_URL + path.name
    with urlopen(Request(url, headers={"User-Agent": "Hepta-grounded-research/1"}), timeout=45) as response:
        if not response.geturl().startswith(IMAGE_URL):
            raise ValueError("image redirected outside official COCO source")
        raw = response.read(3_000_001)
        etag = response.headers.get("ETag", "").strip('"')
    if not 0 < len(raw) <= 3_000_000 or (re.fullmatch(r"[a-f0-9]{32}", etag)
                                       and hashlib.md5(raw).hexdigest() != etag):
        raise ValueError("COCO image size or source ETag mismatch")
    temporary = path.with_suffix(".partial")
    temporary.write_bytes(raw)
    temporary.replace(path)


def build_cohort(annotations, output_dir, *, sizes=DEFAULT_SIZES, exclusion_manifest=DEFAULT_EXCLUSION,
                 image_cache=None, download_images=False, seed=SEED, fixture=False):
    """Build a frozen roster without querying or inspecting any model output."""
    if len(sizes) != 4 or any(type(n) is not int or n < 1 for n in sizes):
        raise ValueError("four positive train/dev/calibration/test sizes required")
    data, source_sha = _source(annotations, fixture)
    old, exclusion_sha = _exclusions(exclusion_manifest)
    if not fixture and len(old) < 384:
        raise ValueError("real cohort must exclude the complete prior 384-image roster")
    output = Path(output_dir).resolve()
    if (output / "manifest.json").exists():
        raise FileExistsError("refusing to overwrite an existing frozen cohort")
    cache = Path(image_cache or output / "images").resolve()
    cache.mkdir(parents=True, exist_ok=True)
    candidates = list(candidate_sources(data, {row["image_id"] for row in old}, seed))
    selected, fingerprints, rejected, offset = [], list(old), [], 0

    def materialize(candidate):
        image, reference, annotation_ids = candidate
        path = cache / image["file_name"]
        _fetch(path, download_images)
        return image, reference, annotation_ids, path, image_fingerprint(path, reference["image_size"])

    with ThreadPoolExecutor(max_workers=8) as executor:
        while len(selected) < sum(sizes) and offset < len(candidates):
            batch = candidates[offset:offset + min(16, sum(sizes) - len(selected))]
            offset += len(batch)
            for item in executor.map(materialize, batch):
                if _duplicate(item[-1], fingerprints):
                    rejected.append({"image_id": item[0]["id"], "reason": "exact_or_dhash_near_duplicate"})
                    continue
                selected.append(item)
                fingerprints.append(item[-1])
    if len(selected) != sum(sizes):
        raise ValueError("insufficient eligible, source-disjoint photos; no cohort was published")
    output.mkdir(parents=True, exist_ok=True)
    manifest = {"schema": "hepta.grounded-cohort.v1", "evidence_kind": "synthetic-fixture" if fixture else "real-coco",
                "annotation_path": str(Path(annotations).resolve()), "annotation_sha256": source_sha,
                "annotation_url": ARCHIVE_URL, "annotation_member": "annotations/instances_val2017.json",
                "selection_seed": seed, "model_outputs_used_for_sampling": False,
                "prior_manifest_path": str(Path(exclusion_manifest).resolve()) if exclusion_manifest else None,
                "prior_manifest_sha256": exclusion_sha, "prior_images_excluded": len(old),
                "near_duplicate_screen": {"algorithm": "64-bit horizontal dHash", "max_hamming": 4},
                "real_world_entity_disjointness_attested": False,
                "foundation_pretraining_contamination_excluded": False, "rejected": rejected, "splits": {}}
    start = 0
    for split, size in zip(SPLITS, sizes):
        observations, references, sources = [], [], []
        for image, reference, annotation_ids, path, fingerprint in selected[start:start + size]:
            category = reference["label"]
            prompt = (f"Locate every {category} in the image. Give all bounding boxes as normalized "
                      "[x1,y1,x2,y2] coordinates in [0,1], count them, and state whether the center of "
                      "the largest bounding box is left or right of the image center. Return a concise "
                      "text explanation and a corresponding annotated image.")
            observations.append({"task_id": reference["task_id"], "image_path": str(path),
                                 "image_sha256": fingerprint["image_sha256"], "prompt": prompt,
                                 "target_category": category})
            references.append(reference)
            sources.append({"source_id": reference["source_id"], "image_id": image["id"],
                            "task_id": reference["task_id"], "annotation_ids": annotation_ids,
                            "license_id": image["license"], "download_url": IMAGE_URL + image["file_name"],
                            **fingerprint})
        start += size
        entry = {"count": size, "sources": sources}
        for kind, rows in (("observations", observations), ("references", references)):
            raw = b"".join(canonical(row) + b"\n" for row in rows)
            name = f"{split}.{kind}.jsonl"
            (output / name).write_bytes(raw)
            entry[kind] = {"file": name, "sha256": sha(raw)}
        manifest["splits"][split] = entry
    (output / "manifest.json").write_bytes(canonical(manifest) + b"\n")
    validate_splits(output)
    return manifest


def load_observations(directory, split):
    """Actor-facing loader: this function never opens a reference file."""
    if split not in SPLITS:
        raise ValueError("unknown split")
    rows = [json.loads(line) for line in (Path(directory) / f"{split}.observations.jsonl").read_text().splitlines()]
    for row in rows:
        if set(row) != OBSERVATION_KEYS or not all(isinstance(v, str) for v in row.values()):
            raise ValueError("observation schema violation or reference leakage")
        if not re.fullmatch(r"[0-9a-f]{64}", row["image_sha256"]):
            raise ValueError("invalid image digest")
    return rows


def iter_pairs(directory, split):
    """Evaluator-only iterator; do not pass its references to an actor."""
    observations = load_observations(directory, split)
    references = [json.loads(line) for line in (Path(directory) / f"{split}.references.jsonl").read_text().splitlines()]
    if len(observations) != len(references):
        raise ValueError("observation/reference cardinality mismatch")
    for observation, reference in zip(observations, references):
        if set(reference) != REFERENCE_KEYS or reference["task_id"] != observation["task_id"]:
            raise ValueError("reference schema or task pairing mismatch")
        yield observation, reference


def validate_splits(directory):
    """Independently recompute source labels, hashes and cross-split isolation."""
    directory = Path(directory)
    manifest = json.loads((directory / "manifest.json").read_text())
    fixture = manifest["evidence_kind"] == "synthetic-fixture"
    if manifest["schema"] != "hepta.grounded-cohort.v1" or set(manifest["splits"]) != set(SPLITS):
        raise ValueError("cohort manifest schema mismatch")
    data, source_sha = _source(manifest["annotation_path"], fixture)
    old, exclusion_sha = _exclusions(manifest["prior_manifest_path"])
    if source_sha != manifest["annotation_sha256"] or exclusion_sha != manifest["prior_manifest_sha256"]:
        raise ValueError("annotation or exclusion custody mismatch")
    if len(old) != manifest["prior_images_excluded"] or (not fixture and len(old) < 384):
        raise ValueError("incomplete historical source exclusion")
    original = {reference["task_id"]: (image, reference, ids) for image, reference, ids in
                candidate_sources(data, {row["image_id"] for row in old}, manifest["selection_seed"])}
    seen_sources, seen_tasks, fingerprints = set(), set(), list(old)
    for split in SPLITS:
        entry = manifest["splits"][split]
        for kind in ("observations", "references"):
            expected = f"{split}.{kind}.jsonl"
            if entry[kind]["file"] != expected or sha((directory / expected).read_bytes()) != entry[kind]["sha256"]:
                raise ValueError("split file custody mismatch")
        pairs = list(iter_pairs(directory, split))
        if len(pairs) != entry["count"] or len(entry["sources"]) != len(pairs):
            raise ValueError("split size differs from frozen roster")
        for (observation, reference), source in zip(pairs, entry["sources"]):
            expected = original.get(reference["task_id"])
            if expected is None or reference != expected[1] or observation["target_category"] != reference["label"]:
                raise ValueError("reference differs from original COCO annotation")
            if (reference["source_id"] in seen_sources or reference["task_id"] in seen_tasks
                    or source["source_id"] != reference["source_id"] or source["task_id"] != reference["task_id"]
                    or source["image_id"] != expected[0]["id"] or source["annotation_ids"] != expected[2]):
                raise ValueError("duplicate source/task or roster identity mismatch")
            fingerprint = image_fingerprint(observation["image_path"], reference["image_size"])
            if any(source.get(k) != v for k, v in fingerprint.items()) or observation["image_sha256"] != fingerprint["image_sha256"]:
                raise ValueError("image custody mismatch")
            if _duplicate(fingerprint, fingerprints):
                raise ValueError("historical or cross-split exact/near-duplicate image")
            seen_sources.add(reference["source_id"])
            seen_tasks.add(reference["task_id"])
            fingerprints.append(fingerprint)
    return {"valid": True, "evidence_kind": manifest["evidence_kind"], "source_groups": len(seen_sources),
            "splits": {split: manifest["splits"][split]["count"] for split in SPLITS}}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--annotations", required=True)
    parser.add_argument("--output-dir", default="run/ndu-grounded-cohort")
    parser.add_argument("--image-cache")
    parser.add_argument("--exclude-manifest", default=DEFAULT_EXCLUSION)
    parser.add_argument("--sizes", default=",".join(map(str, DEFAULT_SIZES)))
    parser.add_argument("--download-images", action="store_true")
    parser.add_argument("--fixture", action="store_true", help="explicit synthetic fixture; never real efficacy evidence")
    args = parser.parse_args()
    build_cohort(args.annotations, args.output_dir, sizes=tuple(map(int, args.sizes.split(","))),
                 exclusion_manifest=args.exclude_manifest, image_cache=args.image_cache,
                 download_images=args.download_images, fixture=args.fixture)
    print(json.dumps(validate_splits(args.output_dir), sort_keys=True))
