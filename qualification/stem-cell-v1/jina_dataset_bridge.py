#!/usr/bin/env python3
"""Lossless identity bridge from existing Stem six windows to Jina v5 five splits.

The Jina code lives on stacked PR #1499. This file intentionally imports
neither its model runner nor an unreviewed Jina runtime, and does NOT provide
a Cell learning or NDU receipt. Conversion requires an independently pinned
source dataset and fails on missing Cell/task/principal provenance.
"""
import argparse
from collections import defaultdict
import hashlib
import json
from pathlib import Path

from decision_421m import audit_dataset, event_time
from study import load_jsonl

SPLIT_MAP = {
    "train": "train", "calibration": "calibration",
    "held_out": "test", "future_1": "future",
    "future_2": "future", "ood": "ood",
}
SCHEMA = "hepta.stem-to-jina-v5-window-bridge.v1"


def canonical(obj):
    return json.dumps(obj, sort_keys=True, ensure_ascii=False,
                      separators=(",", ":"))


def sha256_bytes(data):
    return hashlib.sha256(data).hexdigest()


def convert(source_rows):
    """Map rows with exact case ID, group, chronological windows and option order."""
    indexed, classes, groups_sha256 = audit_dataset(source_rows)
    output = []
    source_split_by_content = {}
    window_groups = defaultdict(set)
    for row in source_rows:
        for key in ("cell_id", "task_id", "principal_id"):
            if not isinstance(row.get(key), str) or not row[key]:
                raise ValueError("missing explicit scoped Cell/task/principal identity")
        if not row["state"] or not row["question"]:
            raise ValueError("empty state/question cannot be encoded")
        if row["language"] not in ("en", "zh", "cross"):
            raise ValueError("unregistered language")
        split = SPLIT_MAP[row["split"]]
        fingerprint = sha256_bytes(canonical(
            [row["state"], row["question"], row["options"]]).encode("utf-8"))
        if (fingerprint in source_split_by_content and
                source_split_by_content[fingerprint] != split):
            raise ValueError("identical candidate case leaked across Jina folds")
        source_split_by_content[fingerprint] = split
        if row["split"] in ("future_1", "future_2"):
            group_key = (row["scope"], row["source_group"])
            if group_key in window_groups["future_1" if
                                          row["split"] == "future_2" else "future_2"]:
                raise ValueError("same source group crosses future windows")
            window_groups[row["split"]].add(group_key)
        converted = {
            "case_id": row["sample_id"],
            "group_id": row["source_group"],
            "source_episode_id": row["episode_id"],
            "cell_id": row["cell_id"],
            "task_id": row["task_id"],
            "principal_id": row["principal_id"],
            "scope_id": row["scope"],
            "language": row["language"], "split": split,
            "state": row["state"], "question": row["question"],
            "options": row["options"], "label": row["label"],
            "event_time": row["event_time"],
        }
        if row["split"] in ("future_1", "future_2"):
            converted["future_window"] = row["split"]
        output.append(converted)
    if len({r["case_id"] for r in output}) != len(indexed):
        raise ValueError("lossy or duplicate case identity")
    f1 = [event_time(row) for row in output if row.get("future_window") == "future_1"]
    f2 = [event_time(row) for row in output if row.get("future_window") == "future_2"]
    if not f1 or not f2 or max(f1) >= min(f2):
        raise ValueError("overlapping Jina future windows")
    splits = sorted(set(row["split"] for row in output))
    if splits != sorted(set(SPLIT_MAP.values())):
        raise ValueError("missing strict five-fold Jina dataset coverage")
    return output, {
        "schema": SCHEMA,
        "status": "schema_conversion_only_no_model_executed",
        "production_promotion_permitted": False,
        "independent_data_authorization_verified": False,
        "ndu_utility_verified": False,
        "source_group_training_lineage_sha256": groups_sha256,
        "row_count": len(output), "classes": classes,
        "source_splits": sorted(SPLIT_MAP),
        "converted_splits": splits,
        "future_1_rows": len(f1), "future_2_rows": len(f2),
        "identity_mapping": "sample_id == case_id; source_group == group_id; episode is source_episode_id",
        "limitations": [
            "No inference, learned Cell, owner signature or resource benchmark is created",
            "Jina v5 native task adapter must remain pinned and run separately in PR #1499",
            "Token Landmark / Cross-attention unsupported without qualified Jina token-state interface",
        ],
    }


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--source", required=True)
    p.add_argument("--approved-source-sha256", required=True)
    p.add_argument("--output", required=True)
    a = p.parse_args()
    path = Path(a.source)
    raw = path.read_bytes()
    source_sha = sha256_bytes(raw)
    if source_sha != a.approved_source_sha256:
        raise ValueError("source does not match the externally approved dataset digest")
    destination = Path(a.output)
    manifest = Path(str(destination) + ".bridge.json")
    if destination.exists() or manifest.exists():
        raise FileExistsError("append-only Jina dataset bridge cannot overwrite")
    converted, receipt = convert(list(load_jsonl(path)))
    payload = "".join(canonical(row) + "\n" for row in converted).encode("utf-8")
    receipt.update({
        "approved_source_file_sha256_unverified_owner_claim": source_sha,
        "jina_converted_jsonl_sha256": sha256_bytes(payload),
        "jina_dataset_canonical_digest": sha256_bytes(canonical(converted).encode("utf-8")),
    })
    destination.write_bytes(payload)
    manifest.write_text(json.dumps(receipt, sort_keys=True,
                                   ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
