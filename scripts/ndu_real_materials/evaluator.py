"""Objective source-bound receipt scorer; run as a separate trusted process."""

import argparse
from datetime import date
from decimal import Decimal, InvalidOperation
import hashlib
import io
import json
from pathlib import Path
import re
import resource
import time
import unicodedata

from PIL import Image

from .common import digest, read_bound, read_relative, strict_json, write_json


def canonical(text, field):
    if not isinstance(text, str):
        return None
    value = unicodedata.normalize("NFKC", text).strip().upper()
    if field == "total":
        value = re.sub(r"\s", "", value).removeprefix("RM").replace(",", "")
        try:
            result = Decimal(value)
            return str(result.normalize()) if result.is_finite() else None
        except InvalidOperation:
            return None
    if field == "date":
        match = re.fullmatch(r"(\d{1,2})[./-](\d{1,2})[./-](\d{2}|\d{4})", value)
        if not match:
            return None
        day, month, year = map(int, match.groups())
        try:
            return date(year + 2000 if year < 100 else year, month, day).isoformat()
        except ValueError:
            return None
    return " ".join(value.split())


def image_from_bytes(raw):
    with Image.open(io.BytesIO(raw)) as source:
        if (source.format not in {"PNG", "JPEG", "WEBP"} or getattr(source, "n_frames", 1) != 1
                or source.width * source.height > 16_000_000):
            raise ValueError("Image outside the frozen decoding profile")
        return source.convert("RGB")


def box_metrics(box, target):
    area = (box[2] - box[0]) * (box[3] - box[1])
    target_area = (target[2] - target[0]) * (target[3] - target[1])
    intersection = max(0, min(box[2], target[2]) - max(box[0], target[0])) * max(
        0, min(box[3], target[3]) - max(box[1], target[1]))
    return intersection / (area + target_area - intersection), intersection / target_area


def score_delivery(reference, delivery, source_bytes, delivered_image=None, initial_image=None):
    if set(delivery) != {"schema", "case_id", "text", "image"}:
        raise ValueError("Delivery has unknown or missing fields")
    if delivery["schema"] != "ndu.real.delivery.v1" or delivery["case_id"] != reference["case_id"]:
        raise ValueError("Delivery identity differs")
    text = delivery["text"]
    if text is not None and (not isinstance(text, str) or len(text) > 8192):
        raise ValueError("Delivered text outside the frozen bound")
    expected_text = canonical(reference["expected_text"], reference["field"])
    if expected_text is None:
        raise ValueError("Registered reference cannot be scored by the frozen normalizer")
    text_quality = float(canonical(text, reference["field"]) == expected_text)
    source = image_from_bytes(source_bytes)
    image_quality, coverage, pixels_match = 0.0, 0.0, False
    image = delivery["image"]
    decoded = None
    if image is not None:
        if set(image) != {"path", "sha256", "bytes", "bbox"}:
            raise ValueError("Delivered image has unknown fields")
        box = image["bbox"]
        if (not isinstance(box, list) or len(box) != 4 or any(type(x) is not int for x in box)
                or not 0 <= box[0] < box[2] <= source.width
                or not 0 <= box[1] < box[3] <= source.height):
            raise ValueError("Delivered image region is invalid")
        if delivered_image is None or digest(delivered_image) != image["sha256"]:
            raise ValueError("Scorer did not receive bound image bytes")
        decoded = image_from_bytes(delivered_image)
        expected = source.crop(box)
        pixels_match = decoded.size == expected.size and decoded.tobytes() == expected.tobytes()
        if pixels_match:
            candidates = [box_metrics(box, target) for target in reference["target_boxes"]]
            image_quality, coverage = max(candidates)
    preserved = True
    initial = reference["initial_commitment"]
    if initial["text"] is not None and text != initial["text"]:
        preserved = False
    if initial["image"] is not None:
        if decoded is None or initial_image is None:
            preserved = False
        else:
            prior = image_from_bytes(initial_image)
            preserved = preserved and decoded.size == prior.size and decoded.tobytes() == prior.tobytes()
    weights = reference["weights"]
    quality = (weights["text"] * text_quality + weights["image"] * image_quality) if preserved else 0.0
    return {"quality": quality, "text_quality": text_quality, "image_quality": image_quality,
            "image_target_coverage": coverage, "image_pixels_verified": pixels_match,
            "image_pass": pixels_match and coverage >= 0.95 and image_quality >= 0.5,
            "committed_output_preserved": preserved, "utility_upper_bound": 1.0}


def evaluate(root, case_id, delivery_root, delivery_path, *, expected_index_sha256,
             expected_rubric_sha256):
    root, delivery_root = Path(root), Path(delivery_root)
    started_cpu, started_wall = time.process_time(), time.perf_counter()
    index_bytes = read_relative(root, "private/reference-index.v2.json", limit=8 * 1024 * 1024)
    if digest(index_bytes) != expected_index_sha256:
        raise ValueError("External reference index pin differs")
    index = strict_json(index_bytes)
    if index.get("schema") != "ndu.real.reference-index.v2":
        raise ValueError("Role-bound reference index v2 is required before any hidden target is read")
    role = index["case_roles"][case_id]
    if role in {"confirmation", "retention_test"}:
        raise PermissionError("Confirmation is sealed; no native owner release adapter is installed")
    if role not in {"train", "development", "retention_validation"}:
        raise ValueError("Unknown registered evaluation role")
    rubric_bytes = read_bound(root, index["rubric"])
    if digest(rubric_bytes) != expected_rubric_sha256:
        raise ValueError("Frozen rubric pin differs")
    reference_bytes = read_bound(root, index["cases"][case_id], limit=2 * 1024 * 1024)
    reference = strict_json(reference_bytes)
    if reference["role"] != role:
        raise ValueError("Reference reassigns the separately pinned source role")
    source_bytes = read_bound(root, reference["source_image"])
    supplied_path = Path(delivery_path)
    relative_delivery = supplied_path.relative_to(delivery_root) if supplied_path.is_absolute() else supplied_path
    delivered_raw = read_relative(delivery_root, relative_delivery.as_posix(), limit=65536)
    delivery = strict_json(delivered_raw)
    image_binding = delivery.get("image")
    image_bytes = None if image_binding is None else read_bound(
        delivery_root, {key: image_binding[key] for key in ("path", "sha256", "bytes")})
    prior = reference["initial_commitment"]["image"]
    prior_bytes = None if prior is None else read_bound(root, prior)
    result = score_delivery(reference, delivery, source_bytes, image_bytes, prior_bytes)
    return {"schema": "ndu.real.independent-evaluation.v1", "case_id": case_id,
            "source_group": reference["source_group"], "episode_group": reference["episode_group"],
            "role": reference["role"], "rubric_sha256": expected_rubric_sha256,
            "reference_sha256": digest(reference_bytes), "delivery_sha256": digest(delivered_raw),
            "evaluator_source_sha256": digest(Path(__file__).read_bytes()),
            "scoring": "fixed external annotations and pixel comparison; no actor score consumed",
            "confirmation_evaluated": False, "native_owner_authentication": "SEPARATE_REQUIRED",
            "cost": {"cpu_seconds": time.process_time() - started_cpu,
                     "wall_seconds": time.perf_counter() - started_wall,
                     "max_rss_kib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss},
            **result}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--case-id", required=True)
    parser.add_argument("--delivery-root", type=Path, required=True)
    parser.add_argument("--delivery", type=Path, required=True)
    parser.add_argument("--reference-index-sha256", required=True)
    parser.add_argument("--rubric-sha256", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = evaluate(args.root, args.case_id, args.delivery_root, args.delivery,
                      expected_index_sha256=args.reference_index_sha256,
                      expected_rubric_sha256=args.rubric_sha256)
    write_json(args.output, result)
    print(json.dumps(result, sort_keys=True))
