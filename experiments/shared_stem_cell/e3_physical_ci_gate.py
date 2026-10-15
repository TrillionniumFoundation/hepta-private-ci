"""Research-only witness that E3 model and independent readout both produced outputs.

This is a *numeric/phase-completeness* check, not source authentication, external
label adjudication, or a production model-selection authority. It uses no model
producer, trainer, or label-bearing reviewer code.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path

SCHEMA = "hepta.e3-granite-dinov2-scienceqa.v1"
ARMS = (
    "text_only", "unaligned_equal_fusion", "rotated_equal_fusion",
    "bridge_image_only", "bridge_equal_fusion", "train_gate",
    "calibrated_fusion", "image_masked",
)
GRANITE = ("ibm-granite/granite-embedding-97m-multilingual-r2",
           "835ad14087e140460703cf0fae09f97d469d65c2")
DINO = ("facebook/dinov2-small", "ed25f3a31f01632728cabb09d1542f84ab7b0056")
DATASET_REVISION = "b9984af01798586705cee1fbdfa80a6dcbef04f1"
MAX_INPUT_BYTES = 8 * 1024 * 1024


class PhysicalGateError(ValueError):
    pass


def require(condition, message):
    if not condition:
        raise PhysicalGateError(message)


def is_hex(value, length):
    return type(value) is str and len(value) == length and all(ch in "0123456789abcdef" for ch in value)


def digest(data):
    return hashlib.sha256(data).hexdigest()


def reject_duplicate(pairs):
    mapping = {}
    for key, value in pairs:
        require(key not in mapping, "duplicate JSON key")
        mapping[key] = value
    return mapping


def reject_constant(value):
    raise PhysicalGateError("nonfinite JSON token: " + value)


def read_file(path):
    path = Path(path)
    require(not path.is_symlink() and path.is_file(), "missing or symlink input")
    size = path.stat().st_size
    require(0 < size <= MAX_INPUT_BYTES, "input byte budget exceeded")
    return path.read_bytes()


def decode(raw):
    result = json.loads(raw, object_pairs_hook=reject_duplicate, parse_constant=reject_constant)

    def finite(value):
        if type(value) is float:
            require(math.isfinite(value), "overflow JSON float")
        elif type(value) is list:
            for item in value:
                finite(item)
        elif type(value) is dict:
            for item in value.values():
                finite(item)

    finite(result)
    require(type(result) is dict, "JSON root must be object")
    return result


def inspect(source_raw, prediction_raw, seal_raw, review_raw, *, source_head):
    """Verify source/fit/held digest consistency and nonauthorizing report flags.

    Does not trust or verify physical model forwards beyond reported counters;
    the GitHub workflow must *execute* both original model and review steps.
    """
    require(is_hex(source_head, 40), "nonimmutable CI source head")
    source, pred, review = map(decode, (source_raw, prediction_raw, review_raw))
    for name in ("source_sha256", "fit_labels_sha256", "private_test_labels_sha256"):
        require(is_hex(source.get(name), 64), "missing/invalid source digest: " + name)
    require(source.get("dataset_revision") == DATASET_REVISION, "wrong original dataset")
    require(pred.get("schema") == SCHEMA + ".sealed-predictions", "wrong prediction schema")
    require(review.get("schema") == SCHEMA + ".independent-heldout-review", "wrong reviewer schema")
    require(pred.get("source_sha256") == source["source_sha256"] == review.get("source_sha256"),
            "source provenance mismatch")
    require(pred.get("fit_labels_sha256") == source["fit_labels_sha256"], "fit-label source mismatch")
    require(review.get("holdout_targets_sha256") == source["private_test_labels_sha256"],
            "held-label seal mismatch")
    pred_digest = digest(prediction_raw)
    require(seal_raw.decode("ascii").split()[0] == pred_digest, "prediction stage seal mismatch")
    require(review.get("sealed_predictions_sha256") == pred_digest, "reviewed different predictions")
    require(pred.get("arms") == list(ARMS), "missing/extra prediction arm")
    for key, model in (("stem_model", GRANITE), ("vision_model", DINO)):
        obj = pred.get(key)
        require(type(obj) is dict and (obj.get("repo"), obj.get("revision")) == model,
                "unpinned model claim: " + key)
        require(is_hex(obj.get("sha256"), 64), "unsealed model identity: " + key)
    for name in ("physical_text_forward_batches", "physical_vision_forward_batches"):
        require(type(pred.get(name)) is int and pred[name] > 0, "absent physical forward counter: " + name)
    fit = pred.get("fit")
    require(type(fit) is dict, "no Head training evidence")
    for key, count in (("private_cell_head_parameters", 769), ("cell_optimizer_updates", 80),
                       ("train_cases", 96), ("calibration_cases", 32), ("holdout_cases", 64)):
        require(type(fit.get(key)) is int and fit[key] == count, "Head budget/count mismatch: " + key)
    require(pred.get("held_labels_visible_to_inference") is False, "target leakage claim")
    require(pred.get("production_accepted") is False and review.get("production_accepted") is False,
            "production authority claim")
    require(pred.get("independent_ground_truth_observer") is False, "false ground-truth authority")
    require(review.get("external_ground_truth_independent_owner") is False, "false label attestation")
    require(review.get("visual_necessity_ground_truth_adjudicated") is False,
            "false vision necessity adjudication")
    require(review.get("statistical_selection_authorized") is False, "unauthorized selection")
    require(review.get("stem_winner") is None and review.get("authority") == "DENY_ALL",
            "unauthorized model promotion")
    require(review.get("original_heldout_cases") == 64, "heldout inventory missing")
    metrics = review.get("arms")
    require(type(metrics) is dict and set(metrics) == set(ARMS), "held-out arm coverage wrong")
    for name, m in metrics.items():
        require(type(m) is dict and type(m.get("cases")) is int and m["cases"] == 64,
                "arm census wrong: " + name)
        require(type(m.get("correct")) is int and 0 <= m["correct"] <= 64,
                "invalid correct count: " + name)
        require(type(m.get("accuracy")) in (int, float) and
                abs(m["accuracy"] - m["correct"] / 64) < 1e-12,
                "invalid accuracy: " + name)
        for key in ("brier_4class_mean", "nll"):
            require(type(m.get(key)) in (int, float) and math.isfinite(m[key]) and m[key] >= 0,
                    "invalid metric: " + name + ":" + key)
    require(metrics["image_masked"] == metrics["text_only"], "masked-image control not identical")
    rows = pred.get("predictions")
    require(type(rows) is list and len(rows) == 64, "sealed rows missing")
    require(len({x.get("id") for x in rows if type(x) is dict}) == 64,
            "duplicate/incomplete prediction IDs")
    for row in rows:
        require(type(row) is dict and type(row.get("arms")) is dict and
                set(row["arms"]) == set(ARMS), "incomplete row arms")
        require(row["arms"]["image_masked"] == row["arms"]["text_only"],
                "nonidentical image-masked prediction")
        for values in row["arms"].values():
            require(type(values) is list and len(values) == 4, "four-class prediction required")
            require(all(type(v) in (int, float) and math.isfinite(v) and 0 <= v <= 1 for v in values),
                    "invalid prediction probability")
            require(abs(sum(values) - 1) <= 1e-4, "probabilities do not sum to one")
    return {
        "schema": "hepta.e3.physical-and-score-required.v1",
        "exact_source_sha": source_head,
        "source_sha256": source["source_sha256"],
        "sealed_predictions_sha256": pred_digest,
        "physical_text_forward_batches": pred["physical_text_forward_batches"],
        "physical_vision_forward_batches": pred["physical_vision_forward_batches"],
        "heldout_cases": 64,
        "completed_original_pretrained_stage_and_scoring": True,
        "signed_model_origin_authenticated": False,
        "natural_visual_necessity_adjudicated": False,
        "stem_winner": None,
        "authority": "DENY_ALL",
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-seals", type=Path, required=True)
    parser.add_argument("--predictions", type=Path, required=True)
    parser.add_argument("--prediction-seal", type=Path, required=True)
    parser.add_argument("--review", type=Path, required=True)
    parser.add_argument("--exact-head", required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    result = inspect(*(read_file(x) for x in
                       (args.source_seals, args.predictions, args.prediction_seal, args.review)),
                     source_head=args.exact_head)
    require(not args.out.is_symlink() and not args.out.exists(), "witness exists/unsafe")
    with args.out.open("x", encoding="utf-8") as fp:
        fp.write(json.dumps(result, sort_keys=True, separators=(",", ":")) + "\n")
        fp.flush()
        os.fsync(fp.fileno())
    print("E3_PHYSICAL_AND_SCORE_REQUIRED_PASS: model and labels not independently attested")


if __name__ == "__main__":
    main()
