"""Enumerate the fixed public universe before a single larger replication."""
import argparse
from pathlib import Path
import re
import time
import urllib.parse

from .common import read, save, sha
from .fetch_speech import obtain


def run(workspace, output):
    source = Path(__file__).parent
    spec = read(source / "DOCUMENT_REPLICATION_PROTOCOL.json")
    old = read(workspace / "natural-continuation-assets/document/MANIFEST.json")
    first = read(workspace / "natural-v2-assets/document/MANIFEST.json")
    excluded = set(old["excluded_historical_merchants"]) | {r["merchant_group"] for r in old["documents"] + first["documents"]}
    known_hashes = {r["sha256"] for r in old["documents"] + first["documents"]}
    used, candidates, files, attempts = set(excluded), [], [], []
    output.mkdir(parents=True, exist_ok=False)
    for split, size in (("test", 347), ("train", 626)):
        for offset in range(0, size, 100):
            query = urllib.parse.urlencode({"dataset": spec["dataset"], "config": "default", "split": split,
                "offset": offset, "length": min(100, size - offset)})
            path = output / "metadata" / f"{split}-{offset}.json"
            files.append(obtain("https://datasets-server.huggingface.co/rows?" + query, path, 15000000, attempts))
            for item in read(path)["rows"]:
                row = item["row"]
                merchant = re.sub(r"[^A-Z0-9]", "", row["entities"]["company"].upper())
                if not merchant or merchant in used:
                    continue
                if f"/--/{spec['dataset_revision']}/--/" not in row["image"]["src"]:
                    raise ValueError("Replication source version differs")
                candidates.append({"upstream_split": split, "row_index": item["row_idx"], "merchant_group": merchant, "row": row})
                used.add(merchant)
    save(output / "ENUMERATION_FROZEN.json", {"registered_ns": time.time_ns(), "protocol_sha256": sha(source / "DOCUMENT_REPLICATION_PROTOCOL.json"),
        "candidate_universe": "All347 official test rows then626 official train rows, lexicographic numeric row order within each",
        "candidate_groups_available": len(candidates), "target_N": min(spec["target_merchants"], len(candidates)),
        "excluded_groups": sorted(excluded), "ordered_candidates": [{k: r[k] for k in ("upstream_split", "row_index", "merchant_group")} for r in candidates],
        "model_prediction_started": False, "label_content_not_used_to_choose_better_cases": True,
        "all_prior_experiment_sources_excluded": True})
    documents, duplicates = [], []
    for item in candidates:
        row = item["row"]
        asset = obtain(row["image"]["src"], output / "images" / (row["key"] + ".jpg"), 8000000, attempts)
        files.append(asset)
        if asset["sha256"] in known_hashes:
            duplicates.append({"id": row["key"], "reason": "exact_prior_or_selected_image_hash", **asset})
            continue
        known_hashes.add(asset["sha256"])
        documents.append({"id": row["key"], "role": "replication", "upstream_split": item["upstream_split"],
            "merchant_group": item["merchant_group"], "row_index": item["row_index"], "reference": row["entities"],
            "reference_words": row["words"], "reference_bboxes": row["bboxes"], "image_size": row["image_size"], **asset})
        if len(documents) == spec["target_merchants"]:
            break
    expected = min(spec["target_merchants"], len(candidates) - len(duplicates))
    if len(documents) != expected:
        raise ValueError("Incomplete prespecified source enumeration")
    save(output / "MANIFEST.json", {"schema": "hepta.ndu.closure-v2.natural.document.replication.assets.v1",
        "registered_ns": time.time_ns(), "protocol_sha256": sha(source / "DOCUMENT_REPLICATION_PROTOCOL.json"),
        "enumeration_sha256": sha(output / "ENUMERATION_FROZEN.json"), "documents": documents,
        "files": files, "excluded_merchants": sorted(excluded), "duplicate_images_excluded": duplicates,
        "actual_N": len(documents), "target_N": spec["target_merchants"], "shortfall_uses_full_available_universe": len(documents) < spec["target_merchants"],
        "model_prediction_started": False, "old_qualification_not_pooled": True,
        "upstream_split_counts": {split: sum(r["upstream_split"] == split for r in documents) for split in ("test", "train")},
        "group_scope": "Unseen normalized annotated merchant groups and exact images; source templates and corporate families may recur"})
    save(output / "FETCH_ATTEMPTS.json", attempts)
    print({"available_candidates": len(candidates), "frozen_N": len(documents), "bytes": sum(r["bytes"] for r in files)}, flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    run(args.workspace, args.output)
