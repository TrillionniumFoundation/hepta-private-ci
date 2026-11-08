"""Real pixel OCR and target-free public candidate features.

The receipt annotations are never an input to this module. Public transcript
text is accepted only when it is explicitly present in the registered task.
Image observations are the currently released overview/crop, not a private scan.
"""

import csv
import hashlib
import io
import math
import os
from pathlib import Path
import re
import subprocess

import numpy as np
from PIL import Image

FEATURE_WIDTH = 126
FIELDS = ("company", "date", "address", "total")
MONEY = re.compile(r"(?<!\w)(?:RM\s*)?[-+]?\d[\d,]*\.\d{2}(?!\d)", re.I)
DATE = re.compile(r"\b\d{1,4}[-/.]\d{1,2}[-/.]\d{1,4}\b")


def requested_field(prompt):
    found = [name for name in FIELDS if re.search(r"\b" + name + r"\b", prompt.lower())]
    if len(found) != 1:
        raise ValueError("Prompt must identify exactly one supported receipt field")
    return found[0]


def _hash_text(text, bins):
    vector = np.zeros(bins, dtype=np.float32)
    value = " " + text.casefold() + " "
    for index in range(max(1, len(value) - 2)):
        token = value[index:index+3].encode()
        digest = hashlib.sha256(token).digest()
        vector[int.from_bytes(digest[:4], "big") % bins] += 1 if digest[4] & 1 else -1
    return vector / max(1.0, float(np.linalg.norm(vector)))


def extract_ocr(image_path, *, executable="tesseract", timeout=20,
                tessdata_dir=None, library_dir=None, evidence_dir=None, evidence_prefix="ocr"):
    """Call the actual frozen OCR executable on released pixels, retaining status."""
    path = Path(image_path)
    if not path.is_file() or path.is_symlink():
        raise ValueError("Released image must be a regular file")
    env = dict(os.environ)
    env.update(OMP_THREAD_LIMIT="1", OMP_NUM_THREADS="1")
    if tessdata_dir is not None:
        env["TESSDATA_PREFIX"] = str(Path(tessdata_dir).resolve(strict=True))
    if library_dir is not None:
        env["LD_LIBRARY_PATH"] = str(Path(library_dir).resolve(strict=True))
    command = [executable, str(path), "stdout", "-l", "eng", "--oem", "1", "--psm", "6", "tsv"]
    # OCR logs are real artifacts, including a timed-out/failed original attempt.
    try:
        result = subprocess.run(command, capture_output=True, timeout=timeout, env=env, check=False)
    except subprocess.TimeoutExpired as error:
        if evidence_dir is not None:
            for suffix, raw in (("tsv", error.stdout or b""), ("stderr", error.stderr or b"")):
                with (Path(evidence_dir) / f"{evidence_prefix}.{suffix}").open("xb") as stream:
                    stream.write(raw)
        raise
    if evidence_dir is not None:
        for suffix, raw in (("tsv", result.stdout), ("stderr", result.stderr)):
            with (Path(evidence_dir) / f"{evidence_prefix}.{suffix}").open("xb") as stream:
                stream.write(raw)
    if result.returncode != 0:
        raise RuntimeError(f"OCR exited {result.returncode}; stderr_sha256="
                           + hashlib.sha256(result.stderr).hexdigest())
    rows = list(csv.DictReader(io.StringIO(result.stdout.decode("utf-8", errors="strict")), delimiter="\t"))
    groups = {}
    for row in rows:
        if row.get("level") != "5" or not row.get("text", "").strip():
            continue
        confidence = float(row["conf"])
        if not math.isfinite(confidence) or confidence < 0:
            continue
        key = tuple(row[name] for name in ("page_num", "block_num", "par_num", "line_num"))
        word = {"text": row["text"].strip(), "confidence": confidence / 100,
                "bbox": [int(row["left"]), int(row["top"]),
                         int(row["left"]) + int(row["width"]), int(row["top"]) + int(row["height"])]}
        groups.setdefault(key, []).append(word)
    lines = []
    for words in groups.values():
        boxes = [w["bbox"] for w in words]
        lines.append({"text": " ".join(w["text"] for w in words),
                      "confidence": sum(w["confidence"] for w in words) / len(words),
                      "bbox": [min(b[0] for b in boxes), min(b[1] for b in boxes),
                               max(b[2] for b in boxes), max(b[3] for b in boxes)],
                      "words": words, "origin": "pixel_ocr"})
    return lines, {"argv": command, "exit_code": result.returncode,
                   "stdout_sha256": hashlib.sha256(result.stdout).hexdigest(),
                   "stderr_sha256": hashlib.sha256(result.stderr).hexdigest(),
                   "recognized_lines": len(lines), "annotations_read": False}


def candidate_features(lines, *, prompt, image_path, source_size, observation_bbox,
                       public_text="", max_candidates=128):
    """Encode actual OCR/public text and image patches without task references."""
    field = requested_field(prompt)
    width, height = source_size
    with Image.open(image_path) as im:
        pixels = np.asarray(im.convert("RGB"), dtype=np.float32) / 255
    local_h, local_w = pixels.shape[:2]
    ox1, oy1, ox2, oy2 = observation_bbox
    if not (0 <= ox1 < ox2 <= width and 0 <= oy1 < oy2 <= height):
        raise ValueError("Observation transform lies outside the public source size")
    all_lines = []
    if public_text:
        all_lines = [{"text": value.strip(), "confidence": 1.0, "bbox": None, "words": [],
                       "origin": "registered_public_text"}
                      for value in public_text.splitlines() if value.strip()]
    all_lines += [dict(row) for row in lines]
    candidates, vectors, seen = [], [], set()
    for line_index, row in enumerate(all_lines):
        options = []
        regexes = (DATE,) if field == "date" else (MONEY,) if field == "total" else (MONEY, DATE)
        for regex in regexes:
            for match in regex.finditer(row["text"]):
                value = match.group().strip()
                # Text selects a value; the image head starts from its observed
                # source line, then learns a coordinate refinement separately.
                box = row["bbox"]
                options.append((value, box))
        options.append((row["text"], row["bbox"]))
        # Adjacent OCR lines support real multi-line address/company fields.
        if field in {"company", "address"} and line_index + 1 < len(all_lines) and row["bbox"] is not None:
            following = all_lines[line_index + 1]
            if following["bbox"] is not None:
                b, c = row["bbox"], following["bbox"]
                options.append((row["text"] + " " + following["text"],
                                [min(b[0], c[0]), min(b[1], c[1]), max(b[2], c[2]), max(b[3], c[3])]))
        for text_value, local_box in options:
            if not text_value or len(text_value) > 8192:
                continue
            if local_box is None:
                source_box = [ox1, oy1, ox2, oy2]
                patch = pixels
            else:
                x1, y1, x2, y2 = local_box
                x1, y1 = max(0, min(local_w-1, x1)), max(0, min(local_h-1, y1))
                x2, y2 = max(x1+1, min(local_w, x2)), max(y1+1, min(local_h, y2))
                source_box = [round(ox1 + x1 / local_w * (ox2-ox1)), round(oy1 + y1 / local_h * (oy2-oy1)),
                              round(ox1 + x2 / local_w * (ox2-ox1)), round(oy1 + y2 / local_h * (oy2-oy1))]
                patch = pixels[y1:y2, x1:x2]
            key = (text_value, tuple(source_box), row["origin"])
            if key in seen:
                continue
            seen.add(key)
            context = " ".join(x["text"] for x in all_lines[max(0, line_index-1):line_index+2])
            lower = context.casefold()
            length = max(1, len(text_value))
            extras = [source_box[0]/width, source_box[1]/height, source_box[2]/width, source_box[3]/height,
                      row["confidence"], min(length/100, 1), min(len(text_value.split())/20, 1),
                      sum(c.isdigit() for c in text_value)/length,
                      bool(MONEY.search(text_value)), bool(DATE.search(text_value)),
                      bool(re.search(r"\b(?:rm|myr)\b", lower)), "total" in lower,
                      any(word in lower for word in ("sdn", "bhd", "enterprise")),
                      any(word in lower for word in ("jalan", "taman", "street")),
                      text_value.startswith("-"), any(word in lower for word in ("subtotal", "tax", "change")),
                      line_index/max(1, len(all_lines)-1), len(candidates)/max_candidates,
                      row["origin"] == "registered_public_text", observation_bbox != [0, 0, width, height],
                      *[field == name for name in FIELDS],
                      *patch.mean(axis=(0, 1)).tolist(), *patch.std(axis=(0, 1)).tolist()]
            vector = np.concatenate((_hash_text(text_value, 64), _hash_text(context, 32), np.asarray(extras, np.float32)))
            if vector.shape != (FEATURE_WIDTH,) or not np.isfinite(vector).all():
                raise ValueError("Invalid public candidate features")
            candidates.append({"text": text_value, "bbox": source_box, "origin": row["origin"]})
            vectors.append(vector)
            if len(candidates) == max_candidates:
                break
        if len(candidates) == max_candidates:
            break
    if not candidates:
        candidates = [{"text": "", "bbox": [ox1, oy1, ox2, oy2], "origin": "no_recognized_text"}]
        vectors = [np.zeros(FEATURE_WIDTH, dtype=np.float32)]
    return candidates, np.stack(vectors)
