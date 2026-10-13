"""Four matched existing-Encoder/Head execution controls, with no heldout gold.

The same frozen backend is reused, but every arm starts with a NEW empty cache.
This is a bounded offline comparison, not a trainer, owner or admission verdict.
"""

import hashlib
import json
import math

import torch

from development_ablation import PhaseClock
from development_learning import run_shared_learning, validate_rows
from shared_encoder_batch import SharedStemEngine


ARMS = (
    ("singleton", 1, 0, 1),
    ("batch", 32, 0, 1),
    ("cache", 32, 64 * 1024 * 1024, 1),
    ("grouped", 32, 64 * 1024 * 1024, 32),
)
ABS_TOLERANCE = 2e-5
REL_TOLERANCE = 2e-4


def encoded_json(value):
    return (json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False,
                       separators=(",", ":")) + "\n").encode("utf-8")


def write_new_json(path, value):
    raw = encoded_json(value)
    with path.open("xb") as stream:
        stream.write(raw)
    return hashlib.sha256(raw).hexdigest()


def _prediction_map(report, rows, classes):
    expected = {r.request.request_id: r for r in rows if r.split == "heldout"}
    predictions = report["predictions"]
    if type(predictions) is not list or len(predictions) != len(expected):
        raise ValueError("incomplete prediction census")
    result = {}
    for item in predictions:
        key = item["request_id"]
        if key not in expected or key in result:
            raise ValueError("unknown or repeated prediction")
        row = expected[key]
        if (item["cell_id"], item["source_group"], item["input_digest"]) != (
                row.request.cell_id, row.source_group, row.request.input_digest):
            raise ValueError("prediction identity mismatch")
        for field in ("frozen_logits", "trained_logits"):
            values = item[field]
            if (type(values) is not list or len(values) != classes
                    or any(type(v) not in (int, float) or not math.isfinite(v) for v in values)):
                raise ValueError("invalid prediction values")
        result[key] = item
    return result


def compare_reports(reports, rows, *, classes):
    """Report negative parity results too. Timing never chooses a model/winner."""
    if set(reports) != {a[0] for a in ARMS}:
        raise ValueError("all four independently executed arms required")
    maps = {name: _prediction_map(report, rows, classes) for name, report in reports.items()}
    base = reports["singleton"]
    expected_cells = {row.request.cell_id for row in rows}
    # Equal labels alone are insufficient: initialization and actual work must match.
    for report in reports.values():
        if (set(report["cells"]) != expected_cells or report["head_kind"] != base["head_kind"]
                or report["head_hidden_size"] != base["head_hidden_size"]):
            raise ValueError("incomparable Head census")
        for cell in expected_cells:
            left, right = base["cells"][cell], report["cells"][cell]
            if left["initial_sha256"] != right["initial_sha256"] or any(
                    left["training"][field] != right["training"][field]
                    for field in ("steps", "examples_processed", "trainable_parameters")):
                raise ValueError("different initial parameters or training work")
    ids = sorted(maps["singleton"])
    comparisons = {}
    # Adjacent comparisons isolate backend batching, caching and grouped fitting.
    for name, reference in (("batch", "singleton"), ("cache", "batch"), ("grouped", "cache")):
        result = {"reference": reference, "fields": {}, "feature_digest_differences": sum(
            maps[name][i]["feature_digest"] != maps[reference][i]["feature_digest"] for i in ids)}
        for field in ("frozen_logits", "trained_logits"):
            left = torch.tensor([maps[reference][i][field] for i in ids], dtype=torch.float64)
            right = torch.tensor([maps[name][i][field] for i in ids], dtype=torch.float64)
            result["fields"][field] = {
                "maximum_absolute_error": float((left - right).abs().max()),
                "within_tolerance": bool(torch.allclose(left, right, atol=ABS_TOLERANCE,
                                                         rtol=REL_TOLERANCE)),
                "classification_disagreements": int((left.argmax(1) != right.argmax(1)).sum()),
            }
        comparisons[name] = result
    return {"comparisons": comparisons, "absolute_tolerance": ABS_TOLERANCE,
            "relative_tolerance": REL_TOLERANCE,
            "logical_heldout_predictions": len(ids),
            "distinct_heldout_inputs": len({r.request.input_digest for r in rows if r.split == "heldout"}),
            "distinct_heldout_source_groups": len({r.source_group for r in rows if r.split == "heldout"}),
            "execution_equivalent": all(field["within_tolerance"] and not field["classification_disagreements"]
                                        for c in comparisons.values() for field in c["fields"].values()),
            "selected_arm": None, "scored_heldout_labels": False, "production_authorized": False}


def run_comparison(backend, rows, training_labels, *, classes, steps=80, seed=1414,
                   head_kind="swiglu", head_hidden_size=8):
    """Independent full calls; arm order is a seed-bound rotation, not score-bound.

    `whole_call` includes the consumer's preflight (its older `total` did not).
    Four-arm wall time also includes comparison/JSON hashing overhead. This does
    not measure separate-process RSS, network acquisition, or cold model loading.
    """
    clock = PhaseClock()
    validate_rows(rows, training_labels, classes=classes)
    if (type(seed) is not int or not 0 <= seed < 2**31
            or type(steps) is not int or not 1 <= steps <= 1000
            or type(head_kind) is not str or head_kind not in ("linear", "swiglu")
            or type(head_hidden_size) is not int or not 1 <= head_hidden_size <= 256):
        raise ValueError("invalid matched execution envelope")
    selected = (backend.encoder_digest, backend.preprocessor_digest, backend.runtime_digest)
    if any((r.request.encoder_digest, r.request.preprocessor_digest, r.request.runtime_digest) != selected
           for r in rows):
        raise ValueError("unselected backend in full comparison census")
    order = ARMS[seed % len(ARMS):] + ARMS[:seed % len(ARMS)]
    reports = {}
    for name, batch, cache_bytes, group in order:
        engine = SharedStemEngine(backend, max_cache_bytes=cache_bytes)
        arm_clock = PhaseClock()
        report = run_shared_learning(engine, rows, training_labels, classes=classes, steps=steps,
                                     seed=seed, head_kind=head_kind, head_hidden_size=head_hidden_size,
                                     head_batch_size=group, encoder_batch_size=batch)
        report["whole_call"] = arm_clock.finish()
        report["cache_capacity_bytes"] = cache_bytes
        report["started_with_empty_feature_cache"] = True
        reports[name] = report
    comparison = compare_reports(reports, rows, classes=classes)
    comparison.update({"seed": seed, "order": [a[0] for a in order],
                       "prediction_sha256": {name: hashlib.sha256(encoded_json(r["predictions"])).hexdigest()
                                             for name, r in reports.items()},
                       "simulated_encoder": any(r["simulated_encoder"] for r in reports.values()),
                       "full_comparison": clock.finish(), "reports": reports})
    return comparison


def score_saved_predictions(predictions, rows, heldout_labels, *, classes):
    """A separate post-prediction operation; never called by run_comparison."""
    mapped = _prediction_map({"predictions": predictions}, rows, classes)
    if (type(heldout_labels) is not dict or set(heldout_labels) != set(mapped)
            or any(type(v) is not int or not 0 <= v < classes for v in heldout_labels.values())):
        raise ValueError("exact heldout-only score map required")
    scores = {}
    for field in ("frozen_logits", "trained_logits"):
        correct = sum(max(range(classes), key=lambda k: row[field][k]) == heldout_labels[key]
                      for key, row in mapped.items())
        scores[field] = {"correct": correct, "total": len(mapped)}
    return scores
