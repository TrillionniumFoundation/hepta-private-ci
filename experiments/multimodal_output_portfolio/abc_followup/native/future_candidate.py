"""Evaluate typed future-correctness perturbations on reused development only.

This evaluates actual generated parameters without retraining or calibration.
The already used selection group is deliberately ineligible for independent
candidate acceptance, signed qualification, or causal generation-utility claims.
"""

import argparse
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import re
import time

import numpy as np

from ...abc_recovery.training_run import file_sha, write_json
from .boundaries import verified_data
from .forecast import HIDDEN, INPUT_DIM, Q, STATE_DIM, groups, predict
from .qualify import check_freeze, ece


Q32 = 1 << 32
DELTA_BOUND_Q32 = 429497  # round(.0001 * Q32), exactly the registered Rust bound.
DIGEST = re.compile(r"[0-9a-f]{64}")
PARAMETER = re.compile(r"w2\.32\.(0|[1-9][0-9]*)")


def checked_digest(value):
    if not isinstance(value, str) or not DIGEST.fullmatch(value) or value == "0" * 64:
        raise ValueError("Missing or malformed candidate/evidence digest")
    return value


def check_weights(weights):
    shapes = {"w1": (HIDDEN, INPUT_DIM), "b1": (HIDDEN,),
              "w2": (STATE_DIM + 1, HIDDEN), "b2": (STATE_DIM + 1,), "token_state": (24, 8)}
    if weights.get("schema") != "hepta.abc4.prospective-output-head.v1":
        raise ValueError("Not the frozen causal future-output architecture")
    for key, shape in shapes.items():
        value = np.asarray(weights[key], dtype=np.float64)
        if value.shape != shape or not np.isfinite(value).all():
            raise ValueError("Invalid future-head tensor: " + key)


def apply_candidate(weights, candidate):
    """The sole writable surface is output row32, hidden columns0 through32."""
    if (not isinstance(candidate.get("id"), str) or not candidate["id"]
            or candidate.get("kind") not in {"NoChange", "Update"}
            or not isinstance(candidate.get("deltas"), list)):
        raise ValueError("Invalid generated candidate schema")
    if candidate["kind"] == "NoChange" and candidate["deltas"]:
        raise ValueError("NoChange contains a mutation")
    updated, seen = deepcopy(weights), set()
    for delta in candidate["deltas"]:
        parameter = delta.get("parameter")
        match = PARAMETER.fullmatch(parameter) if isinstance(parameter, str) else None
        amount = delta.get("delta_q32")
        if (match is None or int(match[1]) >= 33 or parameter in seen
                or type(amount) is not int or abs(amount) > DELTA_BOUND_Q32):
            raise ValueError("Mutation outside the registered typed/Q32 surface")
        checked_digest(delta.get("evidence"))
        seen.add(parameter)
        updated["w2"][32][int(match[1])] += amount / Q32
    check_weights(updated)
    return updated


def probability_metrics(probability, labels):
    if (not np.isfinite(probability).all() or np.any(probability < 0)
            or np.any(probability > 1) or not np.isin(labels, (0, 1)).all()):
        raise ValueError("Invalid probability or observed correctness")
    bounded = np.clip(probability, 1e-15, 1 - 1e-15)
    return {"brier": float(np.mean((probability - labels) ** 2)),
        "bce": float(-np.mean(labels * np.log(bounded) + (1 - labels) * np.log1p(-bounded))),
        "bce_probability_clip": 1e-15, "ece10": ece(probability, labels),
        "mean_probability": float(probability.mean())}


def evaluate(candidates, protocol, model, data, output):
    if output.exists():
        raise FileExistsError("Candidate evaluations cannot overwrite prior evidence")
    started, cpu = time.perf_counter_ns(), time.process_time_ns()
    check_freeze(protocol, model, "predictor-freeze.json")
    check_freeze(protocol, model, "calibrator-freeze.json")
    generation = json.loads(candidates.read_text())
    generator_digest = checked_digest(generation.get("generator_digest"))
    weights_sha = file_sha(model / "weights.json")
    if generation.get("baseline_weights_sha256") != weights_sha:
        raise ValueError("Typed candidates refer to another frozen baseline")
    candidates_sha = file_sha(candidates)
    weights = json.loads((model / "weights.json").read_text()); check_weights(weights)
    calibration = json.loads((model / "calibration.json").read_text())
    collected = verified_data(data, protocol, "development")
    selected = collected["group"] == "selection"
    if not selected.any():
        raise ValueError("Historical selection group is missing")
    x, labels = collected["x_q24"][selected] / Q, collected["y"][selected]
    pair = collected["pair"][selected]
    base_state, base_raw = predict(weights, x)
    base_groups = groups(x, base_raw, calibration["cuts"])
    base_calibrated = np.asarray(calibration["probabilities"])[base_groups]
    baseline = {"raw": probability_metrics(base_raw, labels),
                "frozen_calibration": probability_metrics(base_calibrated, labels)}
    rows, seen, unchanged = [], set(), 0
    for candidate in generation["candidates"]:
        updated = apply_candidate(weights, candidate)
        if candidate["id"] in seen:
            raise ValueError("Duplicate generated candidate identity")
        seen.add(candidate["id"]); unchanged += candidate["kind"] == "NoChange"
        forecast, raw = predict(updated, x)
        if not np.array_equal(forecast, base_state):
            raise ValueError("Correctness-only update changed the future-state forecast")
        group = groups(x, raw, calibration["cuts"])
        calibrated = np.asarray(calibration["probabilities"])[group]
        raw_metrics, calibrated_metrics = probability_metrics(raw, labels), probability_metrics(calibrated, labels)
        rows.append({"candidate": candidate["id"], "kind": candidate["kind"],
            "number_of_parameter_updates": len(candidate["deltas"]),
            "raw": raw_metrics, "frozen_calibration": calibrated_metrics,
            "raw_brier_difference_from_baseline": raw_metrics["brier"] - baseline["raw"]["brier"],
            "raw_bce_difference_from_baseline": raw_metrics["bce"] - baseline["raw"]["bce"],
            "raw_probability_change_max": float(np.max(np.abs(raw - base_raw))),
            "frozen_calibration_group_changes": int(np.count_nonzero(group != base_groups)),
            "future_state_forecast_unchanged": True,
            "candidate_parameter_bytes_sha256": hashlib.sha256(
                json.dumps(updated, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()})
    if not rows or unchanged != 1:
        raise ValueError("The generated set must retain exactly one actual NoChange baseline")
    check_freeze(protocol, model, "predictor-freeze.json")
    check_freeze(protocol, model, "calibrator-freeze.json")
    if file_sha(candidates) != candidates_sha or file_sha(data / "data.npz") != json.loads((data / "cost.json").read_text())["data_sha256"]:
        raise ValueError("Candidate/data identity changed during evaluation")
    report = {"schema": "hepta.abc4.future-candidate-development-evaluation.v1",
        "generator_digest": generator_digest, "candidates_file_sha256": candidates_sha,
        "weights_sha256": weights_sha, "protocol_sha256": file_sha(protocol),
        "predictor_freeze_sha256": file_sha(model / "predictor-freeze.json"),
        "calibrator_freeze_sha256": file_sha(model / "calibrator-freeze.json"),
        "development_data_sha256": file_sha(data / "data.npz"),
        "source_role": "development", "source_group": "selection",
        "source_pairs": len(np.unique(pair)), "future_rows": len(labels),
        "paired_action_rows_are_independent_n": False, "actual_correctness_rate": float(labels.mean()),
        "baseline": baseline, "rows": rows, "writable_surface": "w2[32][0:33] only",
        "maximum_absolute_delta_q32": DELTA_BOUND_Q32,
        "eligible_for_independent_acceptance": False, "production_signed_qualification": False,
        "development_observed_before_candidate_construction": True, "new_source_outcomes_opened": False,
        "refit_or_recalibration": False, "candidate_selected_or_applied": False,
        "interpretation": "Functional historical diagnostic of generated future-correctness parameters; negative Brier/BCE differences are better. No independent efficacy, candidate acceptance, or generation-utility causal claim.",
        "wall_ns": time.perf_counter_ns() - started, "cpu_ns": time.process_time_ns() - cpu,
        "timing_scope": "Whole evaluator entry through checks/predictions/summary; excludes final JSON write; not per-tick latency"}
    write_json(output, report)
    print(json.dumps({"output": str(output), "sha256": file_sha(output), "candidates": len(rows),
        "future_rows": len(labels), "eligible_for_independent_acceptance": False}))


def self_test():
    """Exercise the quantized boundary and an actual future-head forward path."""
    weights = {"schema": "hepta.abc4.prospective-output-head.v1",
        "w1": np.zeros((HIDDEN, INPUT_DIM)).tolist(), "b1": np.ones(HIDDEN).tolist(),
        "w2": np.zeros((STATE_DIM + 1, HIDDEN)).tolist(), "b2": np.zeros(STATE_DIM + 1).tolist(),
        "token_state": np.zeros((24, 8)).tolist()}
    candidate = {"id": "synthetic.update", "kind": "Update", "deltas": [
        {"parameter": "w2.32.32", "delta_q32": DELTA_BOUND_Q32, "evidence": "1" * 64}]}
    updated = apply_candidate(weights, candidate)
    assert updated["w2"][32][32] == DELTA_BOUND_Q32 / Q32 and weights["w2"][32][32] == 0
    x = np.zeros((2, INPUT_DIM)); x[:, 476] = 1
    before, p = predict(weights, x); after, q = predict(updated, x)
    assert np.array_equal(before, after) and np.all(q > p)
    assert apply_candidate(weights, {"id": "baseline", "kind": "NoChange", "deltas": []}) == weights
    rejected = 0
    for parameter, amount in (("w2.31.32", 1), ("w2.32.33", 1), ("w1.32.0", 1),
                              ("w2.32.00", 1), ("w2.32.0", DELTA_BOUND_Q32 + 1),
                              ("w2.32.0", 1.), ("w2.32.0", True)):
        bad = deepcopy(candidate); bad["deltas"][0].update(parameter=parameter, delta_q32=amount)
        try:
            apply_candidate(weights, bad)
        except ValueError:
            rejected += 1
        else:
            raise AssertionError("Invalid typed mutation accepted")
    assert rejected == 7
    return {"status": "passed", "typed_boundary_refusals": rejected,
            "actual_forward_probability_changed": True, "state_forecast_unchanged": True}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("candidates", "protocol", "model", "data", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    args = parser.parse_args()
    evaluate(args.candidates, args.protocol, args.model, args.data, args.output)
