"""Independent label-bearing E3 scorer. Does not import model producer or trainer.

This scorer opens original held-out labels only AFTER immutable original-model
predictions have been sealed by SHA256. Paired outcomes are descriptive for a
historical release split; no Stem selection, model authority or false p99.
"""
from __future__ import annotations
import argparse
from math import comb, fsum
from pathlib import Path

from e3_scienceqa_contract import (ARMS, DINO, E3Error, GRANITE, SCHEMA,
    canonical, read_jsonl, read_pinned, decode, sha, validate_labels,
    validate_probabilities, validate_source, write_new)


def two_sided_mcnemar(n10, n01):
    if n10 + n01 == 0:
        return 1.0
    n = n10 + n01
    cutoff = min(n10, n01)
    return min(1.0, 2 * fsum(comb(n, j) for j in range(cutoff + 1)) / (2 ** n))


def score(sources, hold_labels, sealed, *, source_sha, target_sha, predictions_sha):
    validate_source(sources)
    label_map = validate_labels(sources, hold_labels, {"test"})
    if (type(sealed) is not dict or sealed.get("schema") != SCHEMA + ".sealed-predictions"
            or sealed.get("source_sha256") != source_sha or sealed.get("arms") != list(ARMS)
            or sealed.get("production_accepted") is not False
            or sealed.get("stem_model", {}).get("repo") != GRANITE[0]
            or sealed.get("stem_model", {}).get("revision") != GRANITE[1]
            or sealed.get("vision_model", {}).get("repo") != DINO[0]
            or sealed.get("vision_model", {}).get("revision") != DINO[1]
            or sealed.get("held_labels_visible_to_inference") is not False
            or sealed.get("fit", {}).get("private_cell_head_parameters") != 769
            or sealed.get("fit", {}).get("train_cases") != 96
            or sealed.get("fit", {}).get("calibration_cases") != 32
            or sealed.get("fit", {}).get("holdout_cases") != 64
            or type(sealed.get("physical_text_forward_batches")) is not int
            or sealed["physical_text_forward_batches"] < 1
            or type(sealed.get("physical_vision_forward_batches")) is not int
            or sealed["physical_vision_forward_batches"] < 1):
        raise E3Error("fake, incomplete or incompatible model prediction receipt")
    input_rows = {x["id"]: x for x in sources if x["split"] == "test"}
    pred = sealed.get("predictions")
    if type(pred) is not list or len(pred) != len(input_rows):
        raise E3Error("incomplete holdout prediction inventory")
    observed, preds = set(), {}
    for row in pred:
        if (type(row) is not dict or set(row) != {"id", "group", "split", "source_input_sha256", "arms"}
                or row["id"] not in input_rows or row["id"] in observed
                or row["split"] != "test" or row["group"] != input_rows[row["id"]]["group"]
                or row["source_input_sha256"] != sha(canonical(input_rows[row["id"]]))
                or type(row["arms"]) is not dict or set(row["arms"]) != set(ARMS)):
            raise E3Error("altered source provenance or arm schema")
        observed.add(row["id"])
        for values in row["arms"].values():
            validate_probabilities(values)
        if row["arms"]["image_masked"] != row["arms"]["text_only"]:
            raise E3Error("image mask did not equal text-only control")
        preds[row["id"]] = row["arms"]
    if observed != set(label_map):
        raise E3Error("source/label coverage mismatch")
    correct = {}
    metrics = {}
    by_ids = sorted(label_map)
    for arm in ARMS:
        y = []
        brier = []
        nll = []
        for item in by_ids:
            label = label_map[item]
            vals = preds[item][arm]
            guess = max(range(4), key=lambda j: (vals[j], -j))
            y.append(int(label == guess))
            brier.append(fsum((v - int(k == label))**2 for k, v in enumerate(vals))/4)
            import math
            nll.append(-math.log(max(vals[label], 1e-12)))
        correct[arm] = y
        metrics[arm] = {"cases": len(by_ids), "correct": sum(y),
                        "accuracy": sum(y)/len(y),
                        "brier_4class_mean": fsum(brier)/len(brier),
                        "nll": fsum(nll)/len(nll)}
    ref = correct["text_only"]
    pairing = {}
    for arm in ("unaligned_equal_fusion", "rotated_equal_fusion", "bridge_image_only",
                "bridge_equal_fusion", "train_gate", "calibrated_fusion"):
        cur = correct[arm]
        lost = sum(a == 1 and b == 0 for a,b in zip(ref,cur))
        gained = sum(a == 0 and b == 1 for a,b in zip(ref,cur))
        pairing[arm] = {"new_errors_vs_text": lost, "rescued_errors_vs_text": gained,
                        "discordant_cases": lost+gained,
                        "mcnemar_unadjusted_exact_p": two_sided_mcnemar(lost,gained)}
    return {"schema": SCHEMA + ".independent-heldout-review",
            "source_sha256": source_sha, "holdout_targets_sha256": target_sha,
            "sealed_predictions_sha256": predictions_sha,
            "original_heldout_cases": len(by_ids), "arms": metrics,
            "paired_vs_text_only": pairing,
            "visual_necessity_ground_truth_adjudicated": False,
            "external_ground_truth_independent_owner": False,
            "historical_scienceqa_release_not_future": True,
            "statistical_selection_authorized": False, "stem_winner": None,
            "production_accepted": False, "authority": "DENY_ALL"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sources", type=Path, required=True)
    parser.add_argument("--source-sha256", required=True)
    parser.add_argument("--heldout-labels", type=Path, required=True)
    parser.add_argument("--heldout-labels-sha256", required=True)
    parser.add_argument("--predictions", type=Path, required=True)
    parser.add_argument("--predictions-sha256", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    source = read_jsonl(args.sources, args.source_sha256)
    labels = read_jsonl(args.heldout_labels, args.heldout_labels_sha256)
    sealed = decode(read_pinned(args.predictions, args.predictions_sha256))
    write_new(args.output, score(source, labels, sealed, source_sha=args.source_sha256,
              target_sha=args.heldout_labels_sha256, predictions_sha=args.predictions_sha256))

if __name__ == "__main__":
    main()
