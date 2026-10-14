"""Separate target-bearing evaluation of sealed future cross-modal predictions.

Never imports or executes the fit routine. Reports feature geometry only; no
semantic accuracy, NDU, model authority, or real checkpoint execution claims.
"""
import argparse
import math
from pathlib import Path

from multimodal_bridge import ContractError
from multimodal_alignment_contract import (
    SCHEMA, _text, load_pinned_document, load_pinned_jsonl,
    parse_feature, sha, write_new,
)


def cosine(a: tuple[float, ...], b: tuple[float, ...]) -> float:
    if len(a) != len(b):
        raise ContractError("incompatible aligned vector dimensions")
    dot = math.fsum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(math.fsum(x * x for x in a))
    norm_b = math.sqrt(math.fsum(y * y for y in b))
    if norm_a == 0 or norm_b == 0:
        raise ContractError("undefined cosine due to zero vector")
    return dot / (norm_a * norm_b)


def evaluate(predictions: dict, targets: list[dict], predictions_sha: str,
             targets_sha: str) -> dict:
    if predictions.get("schema") != SCHEMA + ".sealed-predictions":
        raise ContractError("not an exact sealed prediction format")
    seen, actual = set(), {}
    for row in targets:
        if (set(row) != {"case_id", "group_id", "scope", "observed_at", "target", "source_input_sha256", "split"}
                or row["split"] != "future"
                or type(row["observed_at"]) is not int or row["observed_at"] < 0):
            raise ContractError("future target schema mismatch")
        for key in ("case_id", "group_id", "scope"):
            _text(row[key], key)
        target = parse_feature(row["target"])
        if target.modality != "text" or target.encoder_sha256 != predictions["target_encoder_sha256"]:
            raise ContractError("future target model identity drift")
        if target.input_sha256 in predictions["train_target_input_sha256s"]:
            raise ContractError("training target identity reused in future")
        if row["case_id"] in actual:
            raise ContractError("duplicate future target")
        actual[row["case_id"]] = (row, target)
    rec = predictions["predictions"]
    if type(rec) is not list or not rec or len(rec) != len(actual):
        raise ContractError("incomplete or empty future predictions")
    for item in rec:
        case_id = item.get("case_id")
        if case_id not in actual or case_id in seen:
            raise ContractError("unknown or duplicate sealed prediction")
        seen.add(case_id)
        expected, target = actual[case_id]
        if any(item[k] != expected[k] for k in ("case_id", "group_id", "scope", "observed_at", "source_input_sha256")):
            raise ContractError("future evidence identity mismatch")
        if item["scope"] != predictions["scope"] or item["observed_at"] <= predictions["max_train_observed_at"]:
            raise ContractError("scope or future temporal failure")
        if (sha(item["group_id"].encode()) in predictions["train_group_hashes"]
                or item["source_input_sha256"] in predictions["train_source_input_sha256s"]):
            raise ContractError("training lineage in independent evaluation")
        if set(item["predictions"]) != {"fitted", "rotated_target_control", "unaligned_identity"}:
            raise ContractError("missing negative control arm")
        for values in item["predictions"].values():
            if type(values) is not list or len(values) != len(target.values) or any(
                    type(v) not in (int, float) or not math.isfinite(v) or not -8 <= v <= 8
                    for v in values):
                raise ContractError("invalid feature prediction")
    if seen != set(actual):
        raise ContractError("future target coverage mismatch")
    ordered = sorted(rec, key=lambda r: r["case_id"])
    labels = [actual[r["case_id"]][1].values for r in ordered]
    output = {}
    for arm in ("fitted", "rotated_target_control", "unaligned_identity"):
        values = [tuple(r["predictions"][arm]) for r in ordered]
        scores = [cosine(v, t) for v, t in zip(values, labels)]
        mse = [math.fsum((u - w) ** 2 for u, w in zip(v, t)) / len(t)
               for v, t in zip(values, labels)]
        # Retrieval is an optional geometry diagnostic, not a semantic accuracy.
        best = [max(range(len(labels)), key=lambda j: (cosine(v, labels[j]), -j))
                for v in values]
        output[arm] = {"mean_cosine": math.fsum(scores) / len(scores),
                       "mean_squared_error": math.fsum(mse) / len(mse),
                       "within_cohort_retrieval_top1": sum(i == j for i, j in enumerate(best)) / len(best),
                       "cases": len(values)}
    return {"schema": SCHEMA + ".independent-evaluation", "predictions_sha256": predictions_sha,
            "targets_sha256": targets_sha, "measured_real_model_capability": False,
            "external_ground_truth_verified": False, "production_accepted": False,
            "scope": predictions["scope"], "arms": output}


def main() -> None:
    parser = argparse.ArgumentParser(description="Research-only independent bridge evaluator")
    parser.add_argument("--predictions", type=Path, required=True)
    parser.add_argument("--predictions-sha256", required=True)
    parser.add_argument("--future-targets", type=Path, required=True)
    parser.add_argument("--future-targets-sha256", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    predictions = load_pinned_document(args.predictions, args.predictions_sha256)
    targets, digest = load_pinned_jsonl(args.future_targets, args.future_targets_sha256)
    write_new(args.output, evaluate(predictions, targets, args.predictions_sha256, digest))


if __name__ == "__main__":
    main()
