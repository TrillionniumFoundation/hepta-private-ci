"""Build an immutable 640-image exclusion registry for the *next* Hepta cohort.

Takes the pinned 384-image historical exclusion wrapper and the complete
256-image frozen v1 cohort manifest. No training, model, outcomes or image
pixels are read. The resulting source_sample.images is directly accepted by
v1 cohort.py's existing --exclude-manifest contract.

This does NOT build or verify a v2 model cohort, establish disjoint entities,
or rule out pretrained-model memorization.
"""

import argparse
import hashlib
import json
from pathlib import Path
import re

HISTORICAL_SHA256 = "4c2b88f85c9ef5fea08790775a652798a72e9281bed1534561f14c681e7bba9d"
V1_MANIFEST_SHA256 = "71168c26fffdd913d71a69d8708cec957f55dc2bece112c9c50153fbf31de75d"
EXPECTED_SPLITS = {"train": 128, "dev": 32, "calibration": 32, "test": 64}
HISTORICAL_COUNT = 384
EXPECTED_TOTAL = 640
FINGERPRINT_KEYS = ("image_sha256", "decoded_rgb_sha256", "dhash64")
HEX64 = re.compile(r"[a-f0-9]{16}\Z")
HEX256 = re.compile(r"[a-f0-9]{64}\Z")


class ExclusionError(ValueError):
    """Missing/altered provenance or source collision: do not publish."""


def digest(data):
    return hashlib.sha256(data).hexdigest()


def _json_bytes(data):
    return (json.dumps(data, sort_keys=True, separators=(",", ":"),
                       ensure_ascii=False, allow_nan=False) + "\n").encode("utf-8")


def _load_pinned(path, expected, name):
    source = Path(path).read_bytes()
    actual = digest(source)
    if actual != expected:
        raise ExclusionError(f"{name} SHA256 mismatch: {actual} != pinned {expected}")
    try:
        return json.loads(source)
    except (ValueError, UnicodeDecodeError) as exc:
        raise ExclusionError(f"{name} is not valid JSON") from exc


def _fingerprint(row, *, historical=False):
    if not isinstance(row, dict):
        raise ExclusionError("every historical image requires a dictionary")
    image_id = row.get("image_id")
    if type(image_id) is not int or image_id < 0:
        raise ExclusionError("invalid original COCO image_id")
    if not historical and row.get("source_id") != f"coco:val2017:{image_id}":
        raise ExclusionError("cohort source_id and original image_id disagree")
    for name in FINGERPRINT_KEYS:
        pattern = HEX64 if name == "dhash64" else HEX256
        if not isinstance(row.get(name), str) or pattern.fullmatch(row[name]) is None:
            raise ExclusionError(f"invalid or missing {name} for image {image_id}")
    return {"image_id": image_id, **{name: row[name] for name in FINGERPRINT_KEYS}}


def build_registry(historical, v1_manifest, *, historical_sha=HISTORICAL_SHA256,
                   v1_sha=V1_MANIFEST_SHA256, near_duplicate_distance=4):
    """Reject collisions among all 640 pinned sources, including cross-roster dHash.

    Byte digests of *both* inputs are pinned outside this function (load_pinned)
    or supplied by the isolated fixtures in tests. The generated schema remains
    compatible with cohort.py::_exclusions without altering the frozen v1 code.
    """
    if type(near_duplicate_distance) is not int or not 0 <= near_duplicate_distance <= 64:
        raise ExclusionError("invalid near-duplicate Hamming cutoff")
    if (not isinstance(historical, dict)
            or historical.get("schema") != "hepta.ndu.historical-exclusions.v1"):
        raise ExclusionError("the 384-image historical exclusion wrapper is required")
    source_sample = historical.get("source_sample")
    if not isinstance(source_sample, dict):
        raise ExclusionError("malformed historical source_sample wrapper")
    old = source_sample.get("images")
    if not isinstance(old, list) or len(old) != HISTORICAL_COUNT:
        raise ExclusionError("the full original 384-image roster is required")
    if (not isinstance(v1_manifest, dict)
            or v1_manifest.get("schema") != "hepta.grounded-cohort.v1"):
        raise ExclusionError("the original v1 cohort manifest is required")
    splits = v1_manifest.get("splits")
    if not isinstance(splits, dict) or set(splits) != set(EXPECTED_SPLITS):
        raise ExclusionError("the original four v1 source splits are required")
    registry = [_fingerprint(row, historical=True) for row in old]
    for split, count in EXPECTED_SPLITS.items():
        rows = splits[split]
        if (not isinstance(rows, dict) or type(rows.get("count")) is not int
                or rows["count"] != count or not isinstance(rows.get("sources"), list)
                or len(rows["sources"]) != count):
            raise ExclusionError(f"incorrect v1 source roster: {split}")
        registry.extend(_fingerprint(row) for row in rows["sources"])
    if len(registry) != EXPECTED_TOTAL:
        raise ExclusionError("incomplete historical + v1 image registry")
    ids, image_hashes, rgb_hashes, dhashes = set(), set(), set(), []
    for row in registry:
        source_id = row["image_id"]
        if (source_id in ids or row["image_sha256"] in image_hashes
                or row["decoded_rgb_sha256"] in rgb_hashes):
            raise ExclusionError(f"exact historical/v1 image overlap at {source_id}")
        h = int(row["dhash64"], 16)
        if any((h ^ prior).bit_count() <= near_duplicate_distance for prior in dhashes):
            raise ExclusionError(f"perceptual near-duplicate historical/v1 image at {source_id}")
        ids.add(source_id)
        image_hashes.add(row["image_sha256"])
        rgb_hashes.add(row["decoded_rgb_sha256"])
        dhashes.append(h)
    images = sorted(registry, key=lambda row: row["image_id"])
    return {
        "schema": "hepta.ndu.historical-exclusions.v1",
        "note": "Combined immutable prior-original-image roster for a *new* Hepta v2 cohort. Original v1 science unchanged.",
        "provenance": {
            "historical_wrapper_sha256": historical_sha,
            "v1_cohort_manifest_sha256": v1_sha,
            "historical_sources": HISTORICAL_COUNT,
            "v1_source_split_counts": EXPECTED_SPLITS,
            "all_unique_original_sources": EXPECTED_TOTAL,
            "near_duplicate_dhash_hamming_cutoff": near_duplicate_distance,
            "source_selection_used_model_outputs": False,
            "real_world_entity_disjointness_proven": False,
            "foundation_pretraining_overlap_excluded": False,
        },
        "source_sample": {"images": images},
    }


def create(historical_path, v1_manifest_path, output_path):
    historical = _load_pinned(historical_path, HISTORICAL_SHA256, "historical roster")
    v1 = _load_pinned(v1_manifest_path, V1_MANIFEST_SHA256, "frozen v1 cohort")
    payload = _json_bytes(build_registry(historical, v1))
    destination = Path(output_path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    try:
        with destination.open("xb") as handle:
            handle.write(payload)
    except FileExistsError:
        if destination.read_bytes() != payload:
            raise ExclusionError("refuse to replace an existing nonidentical frozen exclusion registry")
    return {"status": "pass", "image_count": EXPECTED_TOTAL,
            "exclusion_sha256": digest(payload), "output": str(destination.resolve()),
            "compatible_with": "cohort.py --exclude-manifest", "fresh_v2_cohort_executed": False}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--historical", required=True)
    parser.add_argument("--v1-manifest", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args(argv)
    try:
        print(json.dumps(create(args.historical, args.v1_manifest, args.output), sort_keys=True))
    except (OSError, ExclusionError) as exc:
        print(json.dumps({"status": "fail", "error": str(exc)}, sort_keys=True))
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
