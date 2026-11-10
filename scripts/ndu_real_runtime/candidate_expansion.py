"""Independent, target-free three-line proposals over one public observation.

The original candidate/feature prefix is preserved. New spans need separate
training/calibration; this entry does not install a generator in the actor.
Use a fresh worker after source changes. Load-time pins reject ordinary disk
drift; they do not authenticate a runtime or resist malicious monkeypatching.
"""

import hashlib
import io
import json
import math
from pathlib import Path
import re
import time
import types

import numpy as np
from PIL import Image

from . import ocr as _base_ocr

CONFIG = {
    "span_length": 3,
    "max_public_lines": 256,
    "max_extensions": 64,
    "candidate_cap": 128,
    "fields": ("company", "address"),
    "context": "span_plus_one_original_neighbor_each_side",
    "feature_layout": "ocr_v1_126_with_original_start_and_final_candidate_position",
}
_SOURCE_PATHS = {
    "base_ocr_sha256": Path(_base_ocr.__file__),
    "extension_sha256": Path(__file__),
}
_OCR_SOURCE = _SOURCE_PATHS["base_ocr_sha256"].read_bytes()
# A previously imported package OCR module may contain older callables. Compile
# this entry's OCR namespace from the same bytes committed by the profile.
ocr = types.ModuleType(__name__ + ".pinned_ocr")
ocr.__file__ = str(_SOURCE_PATHS["base_ocr_sha256"])
exec(compile(_OCR_SOURCE, ocr.__file__, "exec"), ocr.__dict__)
_LOADED_SOURCE_PINS = {
    key: hashlib.sha256(
        _OCR_SOURCE if key == "base_ocr_sha256" else path.read_bytes()
    ).hexdigest()
    for key, path in _SOURCE_PATHS.items()
}


def digest(value):
    return hashlib.sha256(
        json.dumps(
            value, sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode()
    ).hexdigest()


def profile():
    current = {
        key: hashlib.sha256(path.read_bytes()).hexdigest()
        for key, path in _SOURCE_PATHS.items()
    }
    if current != _LOADED_SOURCE_PINS:
        raise ValueError("EXPANSION_LOADED_SOURCE_CHANGED_FRESH_WORKER_REQUIRED")
    return {
        "schema": "ndu.ctrl.candidate-expansion-profile.v1",
        "config": dict(CONFIG),
        **current,
    }


def _lines(lines, public_text):
    if (
        type(lines) is not list
        or len(lines) > CONFIG["max_public_lines"]
        or type(public_text) is not str
        or len(public_text.encode()) > 65536
    ):
        raise ValueError("EXPANSION_PUBLIC_INPUT_BOUND")
    public = [
        {
            "text": text.strip(),
            "confidence": 1.0,
            "bbox": None,
            "origin": "registered_public_text",
        }
        for text in public_text.splitlines()
        if text.strip()
    ]
    pixels = []
    for row in lines:
        if (
            type(row) is not dict
            or not {"text", "confidence", "bbox", "origin"} <= set(row)
            or set(row) - {"text", "confidence", "bbox", "origin", "words"}
        ):
            raise ValueError("EXPANSION_OCR_SCHEMA")
        text, confidence, box = row["text"], row["confidence"], row["bbox"]
        if (
            type(text) is not str
            or not text.strip()
            or len(text.encode()) > 8192
            or type(confidence) not in (int, float)
            or not math.isfinite(confidence)
            or not 0 <= confidence <= 1
            or row["origin"] != "pixel_ocr"
            or type(box) is not list
            or len(box) != 4
            or any(type(v) is not int for v in box)
            or not 0 <= box[0] < box[2]
            or not 0 <= box[1] < box[3]
        ):
            raise ValueError("EXPANSION_OCR_CONTENT")
        pixels.append(
            {key: row[key] for key in ("text", "confidence", "bbox", "origin")}
        )
    result = public + pixels
    if len(result) > CONFIG["max_public_lines"] or any(
        len(r["text"].encode()) > 8192 for r in public
    ):
        raise ValueError("EXPANSION_PUBLIC_LINE_BOUND")
    return result, pixels


def _span(start, rows, pixels, source_size, observation_bbox):
    window = rows[start : start + CONFIG["span_length"]]
    if len({row["origin"] for row in window}) != 1:
        return None
    text = " ".join(row["text"] for row in window)
    if len(text.encode()) > 8192:
        return None
    width, height = source_size
    ox1, oy1, ox2, oy2 = observation_bbox
    if window[0]["origin"] == "registered_public_text":
        box, patch = [ox1, oy1, ox2, oy2], pixels
    else:
        boxes = [row["bbox"] for row in window]
        local_h, local_w = pixels.shape[:2]
        x1, y1 = min(b[0] for b in boxes), min(b[1] for b in boxes)
        x2, y2 = max(b[2] for b in boxes), max(b[3] for b in boxes)
        x1, y1 = min(local_w - 1, x1), min(local_h - 1, y1)
        x2, y2 = max(x1 + 1, min(local_w, x2)), max(y1 + 1, min(local_h, y2))
        box = [
            round(ox1 + x1 / local_w * (ox2 - ox1)),
            round(oy1 + y1 / local_h * (oy2 - oy1)),
            round(ox1 + x2 / local_w * (ox2 - ox1)),
            round(oy1 + y2 / local_h * (oy2 - oy1)),
        ]
        if not 0 <= box[0] < box[2] <= width or not 0 <= box[1] < box[3] <= height:
            return None
        patch = pixels[y1:y2, x1:x2]
    return {
        "candidate": {"text": text, "bbox": box, "origin": window[0]["origin"]},
        "confidence": sum(r["confidence"] for r in window) / len(window),
        "context": " ".join(
            r["text"] for r in rows[max(0, start - 1) : start + len(window) + 1]
        ),
        "line_indices": list(range(start, start + len(window))),
        "patch_mean": patch.mean(axis=(0, 1)).tolist(),
        "patch_std": patch.std(axis=(0, 1)).tolist(),
    }


def _encode(span, field, line_count, index, source_size, observation_bbox):
    candidate = span["candidate"]
    text, lower = candidate["text"], span["context"].casefold()
    width, height = source_size
    length, box = max(1, len(text)), candidate["bbox"]
    extras = [
        box[0] / width,
        box[1] / height,
        box[2] / width,
        box[3] / height,
        span["confidence"],
        min(length / 100, 1),
        min(len(text.split()) / 20, 1),
        sum(c.isdigit() for c in text) / length,
        bool(ocr.MONEY.search(text)),
        bool(ocr.DATE.search(text)),
        bool(re.search(r"\b(?:rm|myr)\b", lower)),
        "total" in lower,
        any(word in lower for word in ("sdn", "bhd", "enterprise")),
        any(word in lower for word in ("jalan", "taman", "street")),
        text.startswith("-"),
        any(word in lower for word in ("subtotal", "tax", "change")),
        span["line_indices"][0] / max(1, line_count - 1),
        index / CONFIG["candidate_cap"],
        candidate["origin"] == "registered_public_text",
        observation_bbox != [0, 0, width, height],
        *[field == name for name in ocr.FIELDS],
        *span["patch_mean"],
        *span["patch_std"],
    ]
    vector = np.concatenate(
        (
            ocr._hash_text(text, 64),
            ocr._hash_text(span["context"], 32),
            np.asarray(extras, np.float32),
        )
    )
    if vector.shape != (ocr.FEATURE_WIDTH,) or not np.isfinite(vector).all():
        raise ValueError("EXPANSION_FEATURE_LAYOUT")
    return vector


def expand_candidates(
    lines,
    *,
    prompt,
    image_path,
    source_size,
    observation_bbox,
    public_text="",
    expected_observation_sha256,
    expected_profile_sha256,
):
    started = time.perf_counter()
    frozen_profile = profile()
    if digest(frozen_profile) != expected_profile_sha256:
        raise ValueError("EXPANSION_PROFILE_PIN")
    rows, pixel_lines = _lines(lines, public_text)
    path = Path(image_path)
    if path.is_symlink() or not path.is_file():
        raise ValueError("EXPANSION_OBSERVATION_FILE")
    with path.open("rb") as stream:
        raw = stream.read(64 * 1024 * 1024 + 1)
    observation_sha = hashlib.sha256(raw).hexdigest()
    if len(raw) > 64 * 1024 * 1024 or observation_sha != expected_observation_sha256:
        raise ValueError("EXPANSION_OBSERVATION_PIN")
    # Both encoders consume the same verified in-memory observation snapshot.
    candidates, original = ocr.candidate_features(
        pixel_lines,
        prompt=prompt,
        image_path=io.BytesIO(raw),
        source_size=source_size,
        observation_bbox=observation_bbox,
        public_text=public_text,
        max_candidates=CONFIG["candidate_cap"],
    )
    field = ocr.requested_field(prompt)
    proposals, seen = (
        [],
        {(c["text"], tuple(c["bbox"]), c["origin"]) for c in candidates},
    )
    with Image.open(io.BytesIO(raw)) as image:
        pixels = np.asarray(image.convert("RGB"), dtype=np.float32) / 255
    if field in CONFIG["fields"]:
        for start in range(max(0, len(rows) - CONFIG["span_length"] + 1)):
            value = _span(start, rows, pixels, source_size, observation_bbox)
            if value is not None:
                c = value["candidate"]
                key = c["text"], tuple(c["bbox"]), c["origin"]
                if key not in seen:
                    seen.add(key)
                    proposals.append(value)
    available = CONFIG["candidate_cap"] - len(candidates)
    admitted = proposals[: min(available, CONFIG["max_extensions"])]
    output, vectors, provenance = list(candidates), [], []
    for span in admitted:
        index = len(output)
        vectors.append(
            _encode(span, field, len(rows), index, source_size, observation_bbox)
        )
        output.append(span["candidate"])
        provenance.append(
            {
                "index": index,
                "candidate_sha256": digest(span["candidate"]),
                "line_indices": span["line_indices"],
                "origin": span["candidate"]["origin"],
            }
        )
    features = (
        np.concatenate((original, np.stack(vectors)), axis=0)
        if vectors
        else original.copy()
    )
    if (
        features[: len(original)].tobytes() != original.tobytes()
        or profile() != frozen_profile
    ):
        raise ValueError("EXPANSION_PREFIX_OR_SOURCE_CHANGED")
    receipt = {
        "schema": "ndu.ctrl.candidate-expansion-receipt.v1",
        "profile_sha256": expected_profile_sha256,
        "observation_sha256": observation_sha,
        "public_input_sha256": digest(
            [rows, prompt, list(source_size), observation_bbox]
        ),
        "base_candidates": len(candidates),
        "base_at_cap": len(candidates) == CONFIG["candidate_cap"],
        "base_pre_cap_unique_count": None,
        "base_truncation": None,
        "eligible_unique_extensions": len(proposals),
        "added_candidates": len(admitted),
        "dropped_by_extension_limit": max(0, len(proposals) - CONFIG["max_extensions"]),
        "dropped_by_candidate_cap": max(
            0, min(len(proposals), CONFIG["max_extensions"]) - available
        ),
        "final_candidates": len(output),
        "prefix_bytes_unchanged": True,
        "added_provenance": provenance,
        "candidates_sha256": digest(output),
        "features_sha256": digest(
            [
                str(features.dtype),
                list(features.shape),
                hashlib.sha256(features.tobytes()).hexdigest(),
            ]
        ),
        "wall_seconds": time.perf_counter() - started,
        "duration_scope": "entry call only: profile checks, observation snapshot, base encoding, extension generation and encoding; module import, pinned OCR compilation, OCR execution and upstream capture excluded",
        "actor_installed": False,
        "policy_efficacy_evaluated": False,
        "complete_physical_cost": False,
        "requires_refit_and_calibration": True,
    }
    return output, features, receipt
