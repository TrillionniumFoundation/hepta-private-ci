"""Paired natural modality counterfactual evaluation after prediction sealing.

Validates comparable SAME-model media changes with independently supplied
answers; never infers new gold labels from a shuffled image/clip. The inputs
must be produced from real source-bound media; fixtures have no capability value.
"""
from __future__ import annotations

import hashlib
import json
import math
from collections import defaultdict


class InvalidModalityPair(ValueError):
    pass


def _sha(s):
    return type(s) is str and len(s) == 64 and all(c in "0123456789abcdef" for c in s)


def _id(s):
    return type(s) is str and 1 <= len(s) <= 128


def _canonical(v):
    return json.dumps(v, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def _probabilities(p, classes):
    if type(p) is not list or len(p) != classes or any(
        type(x) not in (int, float) or not math.isfinite(x) or x < 0 or x > 1 for x in p
    ) or abs(math.fsum(p) - 1.0) > 1e-6:
        raise InvalidModalityPair("invalid complete class probability vector")


def _temporal(v):
    if type(v) is not list or not 2 <= len(v) <= 16 or any(
        type(x) is not int or x < 0 or x > 2**63 - 1 for x in v
    ) or any(b <= a for a, b in zip(v, v[1:])):
        raise InvalidModalityPair("temporal contrast requires ordered real timestamps")


def evaluate(predictions, labels):
    if type(predictions) is not dict or set(predictions) != {
        "schema", "scope", "model_sha256", "preprocessor_sha256", "source_sha256",
        "classes", "pairs"
    } or predictions["schema"] != "hepta.stem.paired-modality-predictions.v1":
        raise InvalidModalityPair("exact sealed prediction payload required")
    if not _id(predictions["scope"]) or any(
        not _sha(predictions[k]) for k in ("model_sha256", "preprocessor_sha256", "source_sha256")
    ):
        raise InvalidModalityPair("unbound inference scope/model/source")
    classes = predictions["classes"]
    if type(classes) is not int or not 2 <= classes <= 16:
        raise InvalidModalityPair("bounded output classes required")
    pairs = predictions["pairs"]
    if type(pairs) is not list or not 1 <= len(pairs) <= 2048:
        raise InvalidModalityPair("bounded paired cohort required")
    expected, splits, summaries = {}, {}, defaultdict(lambda: {
        "pairs": 0, "both_correct": 0, "original_correct": 0,
        "changed_correct": 0, "prediction_changed": 0,
        "unresponsive_to_truth_flip": 0, "source_groups": set(),
        "known_formula_flops": 0, "flop_coverage_complete": True,
        "pair_wall_ns": 0
    })
    for pair in pairs:
        if type(pair) is not dict or set(pair) != {
            "pair_id", "source_group", "split", "modality", "contrast_kind",
            "prompt_sha256", "original_source_sha256", "changed_source_sha256",
            "original_probabilities", "changed_probabilities", "original_timestamps_us",
            "changed_timestamps_us", "original_frames", "changed_frames",
            "pair_wall_ns", "pair_formula_flops"
        }:
            raise InvalidModalityPair("exact paired media record required")
        ident, group = pair["pair_id"], pair["source_group"]
        if not _id(ident) or not _id(group) or ident in expected:
            raise InvalidModalityPair("duplicate or invalid independent pair")
        if pair["split"] not in ("holdout", "retention"):
            raise InvalidModalityPair("training/calibration examples cannot qualify")
        if group in splits and splits[group] != pair["split"]:
            raise InvalidModalityPair("source-family crosses protected split")
        splits[group] = pair["split"]
        if pair["modality"] not in ("image", "audio", "video") or pair["contrast_kind"] not in (
            "media_substitution", "temporal_reordering"
        ):
            raise InvalidModalityPair("unknown modality/contrast")
        if any(not _sha(pair[k]) for k in (
            "prompt_sha256", "original_source_sha256", "changed_source_sha256"
        )) or pair["original_source_sha256"] == pair["changed_source_sha256"]:
            raise InvalidModalityPair("counterfactual must change actual media, not prompt")
        _probabilities(pair["original_probabilities"], classes)
        _probabilities(pair["changed_probabilities"], classes)
        if pair["modality"] == "video":
            _temporal(pair["original_timestamps_us"])
            _temporal(pair["changed_timestamps_us"])
        elif pair["original_timestamps_us"] is not None or pair["changed_timestamps_us"] is not None:
            raise InvalidModalityPair("nonvideo has no frame timestamps")
        if pair["contrast_kind"] == "temporal_reordering":
            if pair["modality"] != "video" or type(pair["original_frames"]) is not list or (
                type(pair["changed_frames"]) is not list
            ):
                raise InvalidModalityPair("only video has registered frame-order contrast")
            a, b = pair["original_frames"], pair["changed_frames"]
            if (len(a) != len(pair["original_timestamps_us"]) or
                    len(b) != len(pair["changed_timestamps_us"]) or
                    not all(_sha(v) for v in a + b) or
                    sorted(a) != sorted(b) or a == b):
                raise InvalidModalityPair("must reorder the same real frames without adding content")
        elif pair["original_frames"] is not None or pair["changed_frames"] is not None:
            raise InvalidModalityPair("unregistered frame substitution metadata")
        if type(pair["pair_wall_ns"]) is not int or pair["pair_wall_ns"] < 0:
            raise InvalidModalityPair("actual pair duration required")
        flops = pair["pair_formula_flops"]
        if flops is not None and (type(flops) is not int or flops < 0):
            raise InvalidModalityPair("no estimated/negative fake FLOPs allowed")
        expected[ident] = pair

    digest = hashlib.sha256(_canonical(predictions)).hexdigest()
    if type(labels) is not dict or set(labels) != {
        "schema", "prediction_sha256", "observer_receipt_sha256", "labels"
    } or labels["schema"] != "hepta.stem.paired-modality-labels.v1":
        raise InvalidModalityPair("external truth manifest required")
    if labels["prediction_sha256"] != digest or not _sha(labels["observer_receipt_sha256"]):
        raise InvalidModalityPair("labels do not bind exact sealed predictions and observer reference")
    source_labels = labels["labels"]
    if type(source_labels) is not list or len(source_labels) != len(expected):
        raise InvalidModalityPair("complete original/contrast label cohort required")
    adjudicated = {}
    for row in source_labels:
        if type(row) is not dict or set(row) != {"pair_id", "original_label", "changed_label"}:
            raise InvalidModalityPair("typed external pair truth required")
        ident = row["pair_id"]
        if ident not in expected or ident in adjudicated:
            raise InvalidModalityPair("unmatched/duplicate external pair label")
        a, b = row["original_label"], row["changed_label"]
        if (type(a) is not int or type(b) is not int or
                not 0 <= a < classes or not 0 <= b < classes or a == b):
            raise InvalidModalityPair("independent contrast must change the correct answer")
        adjudicated[ident] = (a, b)
    for ident, pair in expected.items():
        a, b = adjudicated[ident]
        observed = max(range(classes), key=pair["original_probabilities"].__getitem__)
        changed = max(range(classes), key=pair["changed_probabilities"].__getitem__)
        group = summaries[(pair["split"], pair["modality"], pair["contrast_kind"])]
        group["pairs"] += 1
        group["original_correct"] += int(observed == a)
        group["changed_correct"] += int(changed == b)
        group["both_correct"] += int(observed == a and changed == b)
        group["prediction_changed"] += int(observed != changed)
        group["unresponsive_to_truth_flip"] += int(observed == changed)
        group["source_groups"].add(pair["source_group"])
        group["pair_wall_ns"] += pair["pair_wall_ns"]
        if pair["pair_formula_flops"] is None:
            group["flop_coverage_complete"] = False
        else:
            group["known_formula_flops"] += pair["pair_formula_flops"]
    return {
        "schema": "hepta.stem.paired-modality-audit.v1",
        "prediction_sha256": digest, "observer_receipt_sha256": labels["observer_receipt_sha256"],
        "groups": {"/".join(key): {
            **{k: v for k, v in value.items() if k not in ("source_groups", "known_formula_flops")},
            "distinct_source_groups": len(value["source_groups"]),
            "pair_formula_flops": value["known_formula_flops"] if value["flop_coverage_complete"] else None
        } for key, value in sorted(summaries.items())},
        "actual_independent_observer_verified": False,
        "cross_modal_generalization_proven": False,
        "physical_energy_verified": False,
        "production_accepted": False
    }
