"""Fail-closed v2 cohort isolation against v1 and earlier image histories.

The historical input may be a regular hepta.grounded-cohort manifest or the
hepta.ndu.historical-exclusions wrapper. This checks observable identities
only; it cannot attest real-world entity overlap or base-model pretraining.
"""

import argparse
import hashlib
import json
from pathlib import Path
import re

HEX256 = re.compile(r"^[0-9a-f]{64}$")
HEX64 = re.compile(r"^[0-9a-f]{16}$")
SPLITS = ("train", "dev", "calibration", "test")

# Immutable source identities from the completed negative v1 experiment.
# A hash of a user-provided JSON manifest is not meaningful evidence unless
# compared with a reference that was pinned before selecting v2 sources.
PINNED_HISTORIES = {
    "hepta.grounded-cohort.v1": {
        "sha256": "71168c26fffdd913d71a69d8708cec957f55dc2bece112c9c50153fbf31de75d",
        "sources": 256,
    },
    "hepta.ndu.historical-exclusions.v1": {
        "sha256": "4c2b88f85c9ef5fea08790775a652798a72e9281bed1534561f14c681e7bba9d",
        "sources": 384,
    },
}


class CohortContractError(ValueError):
    pass


def _checked_image(row, origin, *, allow_image_id=False):
    if not isinstance(row, dict):
        raise CohortContractError(f"{origin}: source must be an object")
    identifier = row.get("source_id")
    if allow_image_id and not identifier:
        image_id = row.get("image_id")
        if type(image_id) is not int or image_id < 0:
            raise CohortContractError(f"{origin}: invalid historical image_id")
        identifier = f"coco:val2017:{image_id}"
    if not isinstance(identifier, str) or not identifier.strip():
        raise CohortContractError(f"{origin}: missing source_id")
    keys = ("image_sha256", "decoded_rgb_sha256", "dhash64")
    for key, rule in zip(keys, (HEX256, HEX256, HEX64)):
        if not isinstance(row.get(key), str) or not rule.fullmatch(row[key]):
            raise CohortContractError(f"{origin}: missing or invalid {key}")
    return {"origin": origin, "source_id": identifier,
            **{key: row[key] for key in keys}}


def load_sources(document, origin, *, historical=False):
    if not isinstance(document, dict):
        raise CohortContractError(f"{origin}: manifest is not an object")
    if document.get("schema") == "hepta.ndu.historical-exclusions.v1":
        if not historical:
            raise CohortContractError(f"{origin}: an exclusions wrapper cannot be a candidate cohort")
        images = document.get("source_sample", {}).get("images")
        if not isinstance(images, list) or not images:
            raise CohortContractError(f"{origin}: empty historical exclusions")
        return [_checked_image(item, f"{origin}:prior:{n}", allow_image_id=True)
                for n, item in enumerate(images)]
    if document.get("schema") != "hepta.grounded-cohort.v1":
        raise CohortContractError(f"{origin}: unsupported manifest schema")
    splits = document.get("splits")
    if not isinstance(splits, dict) or set(splits) != set(SPLITS):
        raise CohortContractError(f"{origin}: require exactly four original-source splits")
    sources = []
    for split in SPLITS:
        part = splits[split]
        if not isinstance(part, dict) or not isinstance(part.get("sources"), list):
            raise CohortContractError(f"{origin}:{split}: malformed source list")
        if type(part.get("count")) is not int or part["count"] != len(part["sources"]) or not part["sources"]:
            raise CohortContractError(f"{origin}:{split}: empty or incorrect count")
        for n, item in enumerate(part["sources"]):
            if not isinstance(item, dict) or not isinstance(item.get("task_id"), str) or not item["task_id"]:
                raise CohortContractError(f"{origin}:{split}:{n}: missing task_id")
            sources.append(_checked_image(item, f"{origin}:{split}:{n}"))
    return sources


def verify_pinned_histories(raw_documents):
    """Require both authentic, *complete* historical cohorts at the CLI boundary.

    Checking only the supplied historical rows would allow a caller to omit
    inconvenient past images and receive a misleading disjointness PASS.
    Raw-byte SHA256 protects all 256 v1 identities and all 384 older images
    against omission, substitution, or changed identity claims.
    """
    if len(raw_documents) != len(PINNED_HISTORIES):
        raise CohortContractError("require both pinned v1 and pre-v1 historical inputs")
    lookup = {item["sha256"]: (schema, item["sources"])
              for schema, item in PINNED_HISTORIES.items()}
    documents, receipts, seen = {}, {}, set()
    for index, data in enumerate(raw_documents):
        if not isinstance(data, bytes):
            raise CohortContractError(f"history:{index}: expected raw file bytes")
        digest = hashlib.sha256(data).hexdigest()
        if digest not in lookup:
            raise CohortContractError(f"history:{index}: unpinned or modified historical evidence")
        schema, expected_count = lookup[digest]
        if schema in seen:
            raise CohortContractError(f"history:{index}: duplicate pinned history")
        try:
            document = json.loads(data)
        except (ValueError, UnicodeDecodeError) as exc:
            raise CohortContractError(f"history:{index}: invalid historical JSON") from exc
        if document.get("schema") != schema:
            raise CohortContractError(f"history:{index}: historical schema mismatch")
        count = len(load_sources(document, f"history:{index}", historical=True))
        if count != expected_count:
            raise CohortContractError(f"history:{index}: historical source-count mismatch")
        seen.add(schema)
        documents[schema] = document
        receipts[schema] = {"sha256": digest, "sources": count}
    if seen != set(PINNED_HISTORIES):
        raise CohortContractError("historical evidence set is incomplete")
    return [documents[schema] for schema in PINNED_HISTORIES], receipts


def verify_candidate_image_bytes(candidate, image_dir):
    """Verify every claimed candidate fingerprint against a local original JPEG.

    Candidate manifests can otherwise fabricate source_id and fingerprint
    values. This is only byte/provenance checking, NOT proof of an independent
    training/pretraining cohort or of legal source attribution.
    """
    if not image_dir:
        raise CohortContractError("candidate image bytes are required (--image-dir)")
    folder = Path(image_dir)
    if folder.is_symlink() or not folder.is_dir():
        raise CohortContractError("image-dir must be an existing non-symlink directory")
    # Reuse the original frozen v1 fingerprint algorithm byte-for-byte:
    # raw JPEG SHA, EXIF-transposed RGB SHA, and 9x8 horizontal dHash.
    from PIL import Image
    from cohort import image_fingerprint
    validated = 0
    bytes_total = 0
    for split in SPLITS:
        for index, item in enumerate(candidate["splits"][split]["sources"]):
            origin = f"candidate:{split}:{index}"
            filename = item.get("image_filename")
            if (not isinstance(filename, str) or not filename or
                    Path(filename).name != filename or
                    filename in (".", "..") or "\\" in filename):
                raise CohortContractError(f"{origin}: require a safe image_filename basename")
            path = folder / filename
            if path.is_symlink() or not path.is_file():
                raise CohortContractError(f"{origin}: missing image or image symlink")
            expected_size = item.get("image_size")
            if (not isinstance(expected_size, list) or len(expected_size) != 2 or
                    any(type(n) is not int or n < 1 or n > 4096 for n in expected_size) or
                    expected_size[0] * expected_size[1] > 8_000_000):
                raise CohortContractError(f"{origin}: require bounded image_size [width,height]")
            expected_bytes = item.get("image_bytes")
            if type(expected_bytes) is not int or not 0 < expected_bytes <= 3_000_000:
                raise CohortContractError(f"{origin}: missing/invalid image_bytes")
            try:
                actual = image_fingerprint(path, expected_size)
            except (OSError, ValueError, Image.DecompressionBombError) as exc:
                raise CohortContractError(f"{origin}: invalid candidate JPEG: {exc}") from exc
            for key in ("image_sha256", "decoded_rgb_sha256", "dhash64", "image_bytes"):
                if actual[key] != item.get(key):
                    raise CohortContractError(f"{origin}: actual image bytes disagree with {key}")
            validated += 1
            bytes_total += actual["image_bytes"]
    return {"checked_images": validated, "source_jpeg_bytes": bytes_total,
            "algorithm": "original v1 cohort.image_fingerprint (JPEG/RGB/dHash)",
            "original_bytes_cryptographically_checked": True,
            "independent_real_world_entities_proven": False,
            "foundation_pretraining_excluded": False}


def collision(first, second, distance):
    keys = ("source_id", "image_sha256", "decoded_rgb_sha256")
    exact = [key for key in keys if first[key] == second[key]]
    hamming = (int(first["dhash64"], 16) ^ int(second["dhash64"], 16)).bit_count()
    if hamming <= distance:
        exact.append(f"dhash64_distance_{hamming}")
    return exact


def check_cohort(candidate, history, *, max_hamming=4):
    """Return a machine-verifiable verdict; a missing source list fails closed.

    Only *identity overlap* passes. Entity/pretraining disjointness must be
    attested independently, not inferred from hashes.
    """
    if type(max_hamming) is not int or not 0 <= max_hamming <= 64:
        raise CohortContractError("max_hamming must be an integer in [0,64]")
    new_sources = load_sources(candidate, "candidate")
    if not history:
        raise CohortContractError("at least one historical manifest is required; CLI separately pins two")
    old_sources = []
    for index, document in enumerate(history):
        old_sources.extend(load_sources(document, f"history:{index}", historical=True))
    violations = []
    for n, entry in enumerate(new_sources):
        for prior in new_sources[:n]:
            reasons = collision(entry, prior, max_hamming)
            if reasons:
                violations.append({"candidate": entry["origin"], "prior": prior["origin"], "reasons": reasons})
        for prior in old_sources:
            reasons = collision(entry, prior, max_hamming)
            if reasons:
                violations.append({"candidate": entry["origin"], "prior": prior["origin"], "reasons": reasons})
    return {"schema": "hepta.ndu-cohort-firewall.v2", "status": "pass" if not violations else "fail",
            "candidate_sources": len(new_sources), "historical_sources": len(old_sources),
            "max_dhash_distance": max_hamming, "violations": violations,
            "observable_image_identity_disjoint": not bool(violations),
            "real_world_entity_disjointness_attested": False,
            "foundation_pretraining_contamination_excluded": False,
            "scope": "source_id/byte/RGB/dHash only; entity and pretraining claims remain unproven"}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate", required=True)
    parser.add_argument("--historical", action="append", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--max-dhash-distance", type=int, default=4)
    parser.add_argument("--image-dir", help="required for a PASS: directory of exact candidate JPEG files")
    args = parser.parse_args(argv)
    try:
        candidate = json.loads(Path(args.candidate).read_text())
        history, receipts = verify_pinned_histories(
            [Path(p).read_bytes() for p in args.historical])
        result = check_cohort(candidate, history, max_hamming=args.max_dhash_distance)
        # No PASS from merely claimed candidate fingerprints. Verify raw
        # JPEG, RGB and dHash before a disjointness receipt is authorizing.
        if result["status"] == "pass":
            result["candidate_image_custody"] = verify_candidate_image_bytes(
                candidate, args.image_dir)
        else:
            result["candidate_image_custody"] = {
                "original_bytes_cryptographically_checked": False,
                "reason": "image identity already overlaps pinned history"}
        result["pinned_history_receipts"] = receipts
        result["pinned_history_source_total"] = sum(
            row["sources"] for row in receipts.values())
    except (OSError, json.JSONDecodeError, CohortContractError) as exc:
        result = {"schema": "hepta.ndu-cohort-firewall.v2", "status": "fail",
                  "error": str(exc), "observable_image_identity_disjoint": False}
    dest = Path(args.output)
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(json.dumps(result, sort_keys=True, indent=2) + "\n")
    print(json.dumps({"status": result["status"], "output": str(dest)}, sort_keys=True))
    return 0 if result["status"] == "pass" else 2


if __name__ == "__main__":
    raise SystemExit(main())
