"""Independent NumPy scorer of original V18 physical logits (no Torch/producer import).

This validates original-source numerical outcomes and sealed raw logits, not
independent dataset/model publisher custody, gradient replay or future utility.
"""
import argparse
import hashlib
import json
import math
import zipfile
from pathlib import Path

import numpy as np

ARCHIVE_SHA = "0f3c8c2ceb22b61cabb8a08ca06d2fb0a9a7f4681e9f1af45138cf7979a0e1c7"
DATASET_SHA = "50335a2214756c7a9e09fee9ac9ed27ab855ea98635bb0fab0998144165ffb2c"
ARMS = frozenset(("no_change", "linear", "gated_residual", "continued_single", "split_router"))
SEEDS = frozenset((41, 47, 53))

class Invalid(ValueError):
    pass


def digest(b):
    return hashlib.sha256(b).hexdigest()


def verify(archive: Path, report: Path, original_logits: Path):
    original_bytes = archive.read_bytes()
    if digest(original_bytes) != ARCHIVE_SHA:
        raise Invalid("wrong original archive")
    with zipfile.ZipFile(archive) as z:
        members = z.namelist()
        if len(members) != len(set(members)) or len(members) > 200:
            raise Invalid("duplicate/unbounded archive entries")
        dataset = z.read("hepta-public-study/dataset.jsonl")
    if digest(dataset) != DATASET_SHA:
        raise Invalid("wrong publisher-data bytes")
    split_y = {"train": [], "calibration": []}
    counts = {"train": 0, "calibration": 0, "holdout": 0}
    for line in dataset.splitlines():
        row = json.loads(line)
        split = row.get("split")
        if split not in counts:
            raise Invalid("unknown original split")
        counts[split] += 1
        if split != "holdout":
            y = row["label"]
            if type(y) is not int or not 0 <= y < 4:
                raise Invalid("invalid original training/calibration label")
            split_y[split].append(y)
        # Holdout labels remain unread for model selection or scoring.
    if counts != {"train": 64, "calibration": 32, "holdout": 32}:
        raise Invalid("original source partition drift")
    packet = json.loads(report.read_text())
    raw = json.loads(original_logits.read_text())
    if packet.get("schema") != "hepta.stem.v18.original-feature-investment.v1" or packet.get("decision") != "DENY_ALL_HISTORICAL_CALIBRATION_ONLY" or packet.get("model_selection_authorized") is not False or packet.get("cell_split_authorized") is not False or packet.get("final_use_authorized") is not False or packet.get("future_window_count") != 0 or packet.get("new_pretrained_encoder_forwards") != 0 or packet.get("independent_blind_label_custody") is not False or packet.get("full_lifecycle_cost_qualified") is not False or packet.get("holdout_labels_used_for_training_or_scoring") is not False:
        raise Invalid("attempt to misstate non-authorizing empirical scope")
    if raw.get("source_sha256") != ARCHIVE_SHA or raw.get("research_only") is not True:
        raise Invalid("unmatched private prediction source")
    reported = {s["seed"]: s for s in packet["seeds"]}
    if len(reported) != len(SEEDS) or set(reported) != SEEDS:
        raise Invalid("incomplete original seed panel")
    records = raw.get("records")
    if not isinstance(records, list) or len(records) != 15:
        raise Invalid("all original private physical inference records required")
    seen = set()
    for record in records:
        seed, arm = record["seed"], record["arm"]
        if seed not in SEEDS or arm not in ARMS or (seed, arm) in seen:
            raise Invalid("inconsistent original seed/arm")
        seen.add((seed, arm))
        entry = reported[seed]["arms"][arm]
        if entry.get("research_authorized") is not False or (arm != "no_change" and entry.get("initial_equals_nochange") is not True):
            raise Invalid("wrong initial/authority status")
        for group, n in (("train", 64), ("calibration", 32), ("blind", 32)):
            logits = np.array(record["logits"][group], dtype="<f4")
            if logits.shape != (n, 4) or not np.isfinite(logits).all():
                raise Invalid("invalid original inference logits")
            if digest(logits.tobytes()) != entry["logit_sha256"][group]:
                raise Invalid("physical output digest mismatch")
            if group == "blind":
                continue
            # Float64 NumPy independent reference for accuracy and multiclass Brier.
            scaled = logits.astype(np.float64)
            probs = np.exp(scaled - scaled.max(axis=-1, keepdims=True))
            probs /= probs.sum(axis=-1, keepdims=True)
            labels = np.array(split_y[group], dtype=np.int64)
            score = np.eye(4)[labels]
            accuracy = np.mean(probs.argmax(axis=-1) == labels)
            brier = np.mean(np.sum((probs - score) ** 2, axis=-1))
            key = "train_fit" if group == "train" else "historical_calibration"
            claimed = entry["metrics"][key]
            if abs(accuracy - claimed["accuracy"]) > 5e-7 or abs(brier - claimed["multiclass_brier"]) > 1e-6:
                raise Invalid("reported learning result not independently reproducible")
    if len(seen) != 15:
        raise Invalid("incomplete score matrix")
    return {"independently_recounted_physical_arms": 15, "original_train_cases": 64, "original_historical_calibration_cases": 32, "original_unscored_blind_cases": 32, "future_windows": 0, "verified_original_source_sha256": ARCHIVE_SHA, "independent_model_execution_or_publisher_signature": False, "production_authorized": False, "decision": "RECOUNT_CONSISTENT_RESEARCH_NO_GO"}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--archive", type=Path, required=True)
    p.add_argument("--report", type=Path, required=True)
    p.add_argument("--private-logits", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    a = p.parse_args()
    result = verify(a.archive, a.report, a.private_logits)
    with a.output.open("x") as f:
        json.dump(result, f, sort_keys=True, indent=2)
    print(result)


if __name__ == "__main__":
    main()
