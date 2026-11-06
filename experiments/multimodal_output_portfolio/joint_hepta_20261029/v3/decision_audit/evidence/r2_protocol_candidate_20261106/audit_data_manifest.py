"""Metadata-only overlap checks; no image/label access or custody certification."""

import argparse
from datetime import datetime
import json
from pathlib import Path

from r2_capture import digest, distinct, hash_string, require


ROOT = Path(__file__).resolve().parent


def audit_records(records, contract, exposure):
    require(isinstance(records, list) and bool(records), "no actual new source manifest")
    required = set(contract["public_manifest_fields"])
    forbidden = {"label", "labels", "answer", "reference_answer", "quality_score", "test_image_bytes"}
    seen_ids, cluster_split, hash_split, perceptual_split = set(), {}, {}, {}
    excluded_hashes = set(exposure["exposed_content_sha256"])
    excluded_source_ids = set(exposure["exposed_source_ids"])
    counts = {name: 0 for name in ("train", "validation", "test")}
    for row in records:
        require(required <= set(row), "source manifest columns missing")
        require(not forbidden.intersection(row), "private label/content leaked into public manifest")
        source, cluster, split = row["opaque_source_id"], row["source_cluster_id"], row["split"]
        require(isinstance(source, str) and source and source not in seen_ids, "duplicate/invalid source ID")
        require(isinstance(cluster, str) and cluster and split in counts, "invalid source cluster or split")
        seen_ids.add(source)
        require(source not in excluded_source_ids, "previously exposed source cannot be relabelled new")
        for key in ("content_sha256", "provenance_receipt_sha256", "instruction_sha256", "label_manifest_commitment"):
            hash_string(row[key], key)
        require(row["content_sha256"] not in excluded_hashes, "exposed image/crop family requires exclusion")
        require(bool(row["license_or_permission"]), "missing permission provenance")
        stamp = datetime.fromisoformat(row["capture_or_release_utc"].replace("Z", "+00:00"))
        require(stamp.tzinfo is not None, "capture/release time lacks timezone")
        require(bool(row["perceptual_duplicate_group"]), "near-duplicate grouping unrecorded")
        for table, key, what in ((cluster_split, cluster, "source cluster"),
                                  (hash_split, row["content_sha256"], "exact image"),
                                  (perceptual_split, row["perceptual_duplicate_group"], "perceptual group")):
            require(key not in table or table[key] == split, f"{what} crosses split")
            table[key] = split
        counts[split] += 1
    return {"schema": "hepta.r2.public-manifest-structure.v1", "manifest_sha256": digest(records),
            "rows_by_split": counts, "independent_source_cluster_counts": {s: sum(x == s for x in cluster_split.values()) for s in counts},
            "recorded_overlap_checks": "PASS_FOR_SUPPLIED_IDS_HASHES_AND_GROUPS_ONLY",
            "image_bytes_opened": False, "labels_opened": False,
            "actual_perceptual_audit_performed_here": False,
            "capture_time_authentication": False, "custody_authenticated": False,
            "test_qualified": False, "no_update": True}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    records = json.loads(Path(args.manifest).read_bytes())
    result = audit_records(records, json.loads((ROOT / "DATA_CONTRACT.json").read_bytes()),
                           json.loads((ROOT / "EXPOSURE_REGISTER.json").read_bytes()))
    with Path(args.output).open("x") as out:
        json.dump(result, out, indent=2, allow_nan=False)
        out.write("\n")


if __name__ == "__main__":
    main()
