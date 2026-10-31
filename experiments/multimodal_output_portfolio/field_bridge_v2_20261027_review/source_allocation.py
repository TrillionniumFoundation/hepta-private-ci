"""Reserve new pixel identities without scoring outputs or fitting any model.

The unchanged corpus loader reads labels to exclude duplicate-pixel conflicts.
This allocation helper never inspects target labels or pixel values, loads a
model/observer, constructs a task batch, or evaluates the reserved identities.
"""

import argparse
import hashlib
import json
from pathlib import Path

import torch

from ..v6.data import load_corpus

OLD_MANIFEST = "224911f36aa829245ad5a0fbe8ee0c971147150ee848183404781279592f1f39"
OLD_COUNTS = {"train": 10000, "validation": 2000, "evaluator": 10000,
              "retention": 1000, "test": 2000}
NEW_COUNTS = {**OLD_COUNTS, "retention": 3000, "test": 4000}
RESERVATIONS = {"primary_test": {"split": "test", "pair_offset": 1000, "pair_count": 512},
                "retention_test": {"split": "retention", "pair_offset": 500, "pair_count": 512}}


def identity_digest(ids):
    return hashlib.sha256("\n".join(ids).encode()).hexdigest()


def allocate(cache_dir, destination):
    if destination.exists():
        raise ValueError("Allocation destination must be new")
    torch.set_num_threads(1)
    old = load_corpus(cache_dir, evaluator_sources=OLD_COUNTS["evaluator"])
    expanded = load_corpus(cache_dir, evaluator_sources=NEW_COUNTS["evaluator"],
                           retention_sources=NEW_COUNTS["retention"], test_sources=NEW_COUNTS["test"])
    if old.manifest["manifest_sha256"] != OLD_MANIFEST:
        raise ValueError("Original source population identity changed")
    original_hashes = {h for split in old.splits.values() for h in split.pixel_hashes}
    if len(original_hashes) != sum(OLD_COUNTS.values()):
        raise ValueError("Original registry contains unexpected duplicate identities")
    prefixes = {}
    full_splits = {}
    for name, count in OLD_COUNTS.items():
        previous, current = old.splits[name], expanded.splits[name]
        if len(previous) != count or len(current) != NEW_COUNTS[name]:
            raise ValueError("Population cardinality differs from registered allocation")
        if (previous.ids != current.ids[:count]
                or previous.pixel_hashes != current.pixel_hashes[:count]):
            raise ValueError("An existing split prefix changed")
        prefixes[name] = {"old_count": count, "expanded_count": len(current),
                          "original_prefix_unchanged": True,
                          "old_identity_sha256": identity_digest(previous.ids),
                          "expanded_identity_sha256": identity_digest(current.ids)}
        full_splits[name] = {"original_prefix_count": count,
                             "identities": list(current.ids),
                             "pixel_sha256": list(current.pixel_hashes)}
    reserved, summary_roles, role_sets = {}, {}, {}
    for role, specification in RESERVATIONS.items():
        population = expanded.splits[specification["split"]]
        start = 2 * specification["pair_offset"]
        end = start + 2 * specification["pair_count"]
        ids, hashes = population.ids[start:end], population.pixel_hashes[start:end]
        if len(ids) != 1024 or len(set(hashes)) != 1024:
            raise ValueError("Reserved role has missing or repeated pixel identities")
        overlap = set(hashes) & original_hashes
        if overlap:
            raise ValueError("Reserved future role overlaps the original source registry")
        role_sets[role] = set(hashes)
        pairs = [list(ids[i:i + 2]) for i in range(0, len(ids), 2)]
        reserved[role] = {**specification, "source_pairs": pairs,
                          "pixel_sha256": list(hashes)}
        summary_roles[role] = {**specification, "source_image_count": len(ids),
                               "identity_sha256": identity_digest(ids),
                               "pixel_set_sha256": identity_digest(sorted(hashes)),
                               "intersection_with_entire_old_registry": 0}
    if role_sets["primary_test"] & role_sets["retention_test"]:
        raise ValueError("Primary and retention roles overlap")
    all_expanded = [h for split in expanded.splits.values() for h in split.pixel_hashes]
    if len(all_expanded) != len(set(all_expanded)):
        raise ValueError("Expanded corpus has cross-role duplicate pixel identities")
    identity = {"schema": "hepta.field-bridge.v2.complete-source-identities.v1",
                "source_splits": full_splits, "reserved_roles": reserved}
    destination.mkdir(parents=True)
    identity_path = destination / "SOURCE_IDENTITIES.json"
    identity_path.write_text(json.dumps(identity, indent=2, sort_keys=True) + "\n")
    loader = Path(__file__).parent.parent / "v6" / "data.py"
    result = {"schema": "hepta.field-bridge.v2.source-allocation.v1",
              "original_manifest": old.manifest, "expanded_manifest": expanded.manifest,
              "old_registry_unique_images": len(original_hashes),
              "expanded_unique_images": len(all_expanded),
              "prefix_checks": prefixes, "reserved_roles": summary_roles,
              "primary_retention_pixel_intersection": 0,
              "source_identity_file": identity_path.name,
              "source_identity_file_sha256": hashlib.sha256(identity_path.read_bytes()).hexdigest(),
              "source_identity_file_bytes": identity_path.stat().st_size,
              "script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
              "loader_source_sha256": hashlib.sha256(loader.read_bytes()).hexdigest(),
              "new_role_model_outputs_scored": 0, "models_or_observers_loaded": 0,
              "target_labels_inspected_by_allocation_helper": False,
              "loader_uses_labels_for_duplicate_conflict_filter": True,
              "claim_limits": [
                  "Fresh relative to every pixel in the complete original recorded source pool, including its unused prefixes.",
                  "Not a global cross-repository exposure registry, new-writer claim, or guarantee about unknown pretraining corpora.",
                  "The new allocation reserves identities only; it does not open output-scoring access or confer scientific acceptance.",
                  "Three recovered model seeds remain fixed historical models."]}
    summary_path = destination / "SOURCE_ALLOCATION.json"
    summary_path.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cache", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    result = allocate(args.cache, args.out)
    print(json.dumps({key: result[key] for key in ("old_registry_unique_images",
        "expanded_unique_images", "reserved_roles", "source_identity_file_sha256",
        "source_identity_file_bytes", "new_role_model_outputs_scored")}, sort_keys=True))


if __name__ == "__main__":
    main()
