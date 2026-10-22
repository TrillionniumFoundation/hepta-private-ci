"""Independent post-run audit of rendered grounding-box perimeter pixels.

No model, inference callbacks or task references are visible to generation here.
This forensic check detects missing/misaligned rendered rectangles; it does NOT
establish correctness against the underlying image, pixel generation, or a
semantically independent text/image correspondence.
"""

import argparse
import hashlib
import json
import math
import re
from pathlib import Path

from PIL import Image

SCHEMA = "hepta.ndu-overlay-geometry-audit.v1"
BORDER_RGB = (255, 30, 30)
BORDER_TOLERANCE_L1 = 10  # FASTOCTREE may round (255,30,30) to (254,29,29).
MIN_BORDER_COVERAGE = 0.90  # Exploratory post-hoc integrity screen, not a quality threshold.


def _read_jsonl(path):
    with Path(path).open(encoding="utf-8") as stream:
        for line in stream:
            if line.strip():
                yield json.loads(line)


def _border_coverage(image, box):
    """Mean coverage of the four predicted rectangle sides at recorded coords."""
    if not isinstance(box, list) or len(box) != 4:
        return None
    if any(not isinstance(v, (int, float)) or not math.isfinite(v) for v in box):
        return None
    left, top, right, bottom = box
    if not (0 <= left < right <= 1 and 0 <= top < bottom <= 1):
        return None
    width, height = image.size
    x0, y0, x1, y1 = (
        min(width - 1, int(left * width)),
        min(height - 1, int(top * height)),
        min(width - 1, int(right * width)),
        min(height - 1, int(bottom * height)),
    )
    if x0 == x1 or y0 == y1:
        return None
    rgb = image.load()

    def red(x, y):
        pixel = rgb[x, y]
        return sum(abs(int(a) - b) for a, b in zip(pixel, BORDER_RGB)) <= BORDER_TOLERANCE_L1

    edges = (
        [(x, y0) for x in range(x0, x1 + 1)],
        [(x, y1) for x in range(x0, x1 + 1)],
        [(x0, y) for y in range(y0, y1 + 1)],
        [(x1, y) for y in range(y0, y1 + 1)],
    )
    return sum(sum(red(x, y) for x, y in edge) / len(edge) for edge in edges) / 4


def audit(episodes_path, artifact_root, references_path=None, threshold=MIN_BORDER_COVERAGE):
    """Validate content-addressed PNG, reference frame size and marker alignment."""
    if not (0 < threshold <= 1):
        raise ValueError("threshold must be in (0,1]")
    refs = None
    if references_path is not None:
        refs = {row["task_id"]: row for row in _read_jsonl(references_path)}
    artifacts = Path(artifact_root)
    seen = set()
    checked = 0
    boxes = 0
    unrenderable = 0
    empty = 0
    low_coverage = []
    bad_artifacts = []
    smallest = 1.0
    digest_cache = {}
    for episode in _read_jsonl(episodes_path):
        task_id, method = episode["task_id"], episode["method"]
        key = (task_id, method)
        if key in seen:
            raise ValueError(f"duplicate task/method row: {key}")
        seen.add(key)
        checked += 1
        if refs is not None and task_id not in refs:
            bad_artifacts.append({"task_id": task_id, "method": method, "reason": "unknown_reference"})
            continue
        digest = episode["artifact_sha256"]
        if not isinstance(digest, str) or re.fullmatch(r"[0-9a-f]{64}", digest) is None:
            bad_artifacts.append({"task_id": task_id, "method": method, "reason": "invalid_digest"})
            continue
        path = artifacts / f"{digest}.png"
        if not path.is_file():
            bad_artifacts.append({"task_id": task_id, "method": method, "reason": "missing_png"})
            continue
        if digest not in digest_cache:
            with path.open("rb") as source:
                digest_cache[digest] = hashlib.file_digest(source, "sha256").hexdigest()
        if digest_cache[digest] != digest:
            bad_artifacts.append({"task_id": task_id, "method": method, "reason": "digest_mismatch"})
            continue
        try:
            with Image.open(path) as source:
                if source.format != "PNG":
                    raise ValueError("not_png")
                if refs is not None and list(source.size) != refs[task_id]["image_size"]:
                    raise ValueError("frame_size_mismatch")
                rgb = source.convert("RGB")
        except (OSError, ValueError) as exc:
            bad_artifacts.append({"task_id": task_id, "method": method, "reason": str(exc)})
            continue
        predicted = episode.get("boxes", [])
        if not predicted:
            empty += 1
        for i, box in enumerate(predicted):
            coverage = _border_coverage(rgb, box)
            boxes += 1
            if coverage is None:
                unrenderable += 1
                continue
            smallest = min(smallest, coverage)
            if coverage < threshold:
                low_coverage.append({"task_id": task_id, "method": method,
                                     "box_index": i, "border_coverage": round(coverage, 6)})
    return {
        "schema": SCHEMA,
        "status": "pass" if not bad_artifacts and not low_coverage and not unrenderable else "fail",
        "scope": "Post-hoc rectangle-pixel integrity only; no original JPEG, object accuracy, free-language or generated-pixel verification.",
        "post_hoc": True,
        "border_rgb": list(BORDER_RGB),
        "border_l1_tolerance": BORDER_TOLERANCE_L1,
        "threshold": threshold,
        "episodes": checked,
        "unique_task_method": len(seen),
        "predicted_boxes": boxes,
        "unrenderable_boxes": unrenderable,
        "empty_box_episodes": empty,
        "minimum_eligible_box_border_coverage": round(smallest, 9) if boxes > unrenderable else None,
        "bad_artifacts": bad_artifacts,
        "low_coverage_boxes": low_coverage,
        "independent_text_generation_proven": False,
        "independent_pixel_generation_proven": False,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--episodes", required=True)
    parser.add_argument("--artifact-root", required=True)
    parser.add_argument("--references", help="Read independently for original frame dimensions only")
    parser.add_argument("--output", help="Write JSON receipt without altering pilot scores")
    args = parser.parse_args()
    result = audit(args.episodes, args.artifact_root, args.references)
    text = json.dumps(result, indent=2, allow_nan=False) + "\n"
    if args.output:
        Path(args.output).write_text(text, encoding="utf-8")
    print(text, end="")
    if result["status"] != "pass":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
