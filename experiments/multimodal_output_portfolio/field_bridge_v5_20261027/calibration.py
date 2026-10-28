"""Old-fit diagnostics and an empirical baseline-preserving action gate.

The threshold pools saved, selected-ridge trajectory-OOF advantage residuals
from field and richer heads. It is an observed maximum, not a coverage bound.
Labels follow V3's frozen reference continuation, not this deployed policy.
This module reads no new holdout and neither fits nor selects a ridge.
"""

import argparse
import gzip
import hashlib
import json
from pathlib import Path

import numpy as np


BASELINE_ACTIONS = {17: 2, 29: 3, 43: 3}
MODES = ("field", "richer")
DEFAULT_EVIDENCE = Path(__file__).resolve().parents[1] / "field_bridge_v3_20261027" / "evidence"


def _require(condition, message):
    if not condition:
        raise ValueError(message)


def _array(value, shape, label):
    result = np.asarray(value, dtype=np.float64)
    _require(result.shape == shape and np.isfinite(result).all(), f"Invalid {label}")
    return result


def predict4(head, raw30):
    """Replay the saved V3 linear predictor, for one state or a batch, using numpy."""
    raw = np.asarray(raw30, dtype=np.float64)
    _require(raw.ndim in (1, 2) and raw.shape[-1] == 30 and np.isfinite(raw).all(), "Invalid raw30")
    dimension = int(head["dimension"])
    _require(1 <= dimension <= 30 and head["prediction_clipping"] is False, "Invalid saved head")
    mean = _array(head["raw_mean"], (30,), "raw mean")
    scale = _array(head["raw_scale"], (30,), "raw scale")
    projection = _array(head["projection"], (30, dimension), "projection")
    projected_mean = _array(head["projected_mean"], (dimension,), "projected mean")
    projected_scale = _array(head["projected_scale"], (dimension,), "projected scale")
    coefficients = _array(head["coefficients"], (dimension + 1, 4), "coefficients")
    _require((scale > 0).all() and (projected_scale > 0).all(), "Nonpositive saved scale")
    projected = ((raw - mean) / scale) @ projection
    projected = (projected - projected_mean) / projected_scale
    design = np.concatenate((np.ones((*projected.shape[:-1], 1)), projected), axis=-1)
    output = design @ coefficients
    _require(np.isfinite(output).all(), "Nonfinite terminal prediction")
    return output


def choose(predictions, baseline_action, tau):
    """Override only on a strict empirical-margin exceedance; equality keeps baseline."""
    values = _array(predictions, (4,), "predictions")
    _require(isinstance(baseline_action, (int, np.integer)) and not isinstance(baseline_action, bool)
             and 0 <= baseline_action < 4, "Invalid baseline action")
    tau = float(tau)
    _require(np.isfinite(tau) and tau >= 0, "Invalid empirical threshold")
    baseline_action = int(baseline_action)
    greedy = int(np.argmax(values))
    greedy_tied = int(np.sum(values == values[greedy])) > 1
    margin = float(values[greedy] - values[baseline_action])
    chosen = greedy if margin > tau and not greedy_tied else baseline_action
    return {"predictions": values.tolist(), "chosen": chosen, "greedy": greedy,
            "greedy_tied": greedy_tied,
            "baseline_action": baseline_action, "ref": baseline_action,
            "margin": margin, "tau": tau, "override": chosen != baseline_action,
            "certificate": False}


def decision(head, raw30, baseline_action, tau):
    """Return prediction and gate receipt for a full closed-loop caller.

    `ref` is an API alias for `baseline_action`, not the bank label continuation.
    """
    return choose(predict4(head, raw30), baseline_action, tau)


def _replay_oof(bank, controllers, mode):
    rows = bank["records"]
    raw = _array([row["state"] for row in rows], (24, 30), "bank states")
    target = _array([row["action_values"] for row in rows], (24, 4), "bank labels")
    groups = np.asarray([row["trajectory"] for row in rows])
    _require(set(groups.tolist()) == {0, 1, 2, 3}, "Incomplete trajectory groups")
    for group in range(4):
        _require(sorted(row["step"] for row in rows if row["trajectory"] == group)
                 == list(range(0, 288, 48)), "Incomplete trajectory decision times")
    choices = controllers["all_candidates"][mode]
    selected = choices["candidates"][choices["selected_index"]]
    _require(selected["full_fit_head"] == controllers["controllers"][mode], "Saved selected head changed")
    _require(selected["full_fit_head"]["fit_rows"] == 24, "Invalid full-fit row count")
    predictions, visited, replay_errors = np.empty_like(target), set(), []
    for fold in selected["folds"]:
        held_out, head = fold["held_out_trajectory"], fold["head"]
        _require(held_out in range(4) and held_out not in visited, "Invalid held-out trajectory")
        _require(fold["training_trajectories"] == sorted({0, 1, 2, 3} - {held_out}), "Trajectory leakage")
        _require(head["fit_rows"] == 18 and head["ridge"] == selected["ridge"]
                 and head["mode"] == mode, "Saved fold configuration changed")
        mask = groups == held_out
        replay = predict4(head, raw[mask])
        saved = _array(fold["predictions"], (6, 4), "saved fold predictions")
        error = float(np.max(np.abs(replay - saved)))
        _require(error <= 1e-14, "Saved OOF predictions do not replay")
        predictions[mask] = replay
        visited.add(held_out)
        replay_errors.append(error)
    _require(visited == {0, 1, 2, 3}, "Missing OOF trajectory")
    return target, predictions, selected, max(replay_errors)


def _policy_summary(target, actions, baseline_action):
    actions = np.asarray(actions, dtype=np.int64)
    chosen = target[np.arange(len(target)), actions]
    regret = target.max(axis=1) - chosen
    return {"rows": len(target), "mean_terminal_value": float(chosen.mean()),
            "mean_regret": float(regret.mean()), "max_regret": float(regret.max()),
            "mean_advantage_over_baseline": float((chosen - target[:, baseline_action]).mean()),
            "override_count": int(np.sum(actions != baseline_action)),
            "override_rate": float(np.mean(actions != baseline_action)),
            "action_counts": np.bincount(actions, minlength=4).tolist()}


def calibrate_saved(bank, controllers, baseline_action=None):
    """Audit saved old-fit folds; return a JSON-safe calibration and descriptive report."""
    seed = int(bank["seed"])
    _require(seed in BASELINE_ACTIONS and controllers["seed"] == seed, "Unknown or mismatched seed")
    baseline_action = BASELINE_ACTIONS[seed] if baseline_action is None else baseline_action
    _require(baseline_action == BASELINE_ACTIONS[seed], "Frozen ordinary baseline changed")
    _require(controllers["development_or_audit_rows_used"] == 0, "Controller used non-fit rows")
    for key in ("reference_sha256", "training_configuration_sha256"):
        _require(bank[key] == controllers[key], f"Mismatched {key}")
    replays, residuals = {}, {}
    for mode in MODES:
        replays[mode] = _replay_oof(bank, controllers, mode)
        target, predicted, _, _ = replays[mode]
        residuals[mode] = ((predicted - predicted[:, [baseline_action]])
                           - (target - target[:, [baseline_action]]))
    tau = max(float(np.max(np.abs(residuals[mode]))) for mode in MODES)
    result = {"schema": "hepta.field-bridge.v5.old-fit-empirical-gate.1", "seed": seed,
              "baseline_action": baseline_action, "label_reference_action": bank["reference_action_index"],
              "label_continuation_matches_baseline": bank["reference_action_index"] == baseline_action,
              "tau": tau, "threshold_pool": "field+richer; selected-ridge trajectory OOF; all action-baseline residuals",
              "certificate": False, "coverage_claim": False, "ridge_reselected": False,
              "fit_performed": False, "new_holdout_rows_read": 0,
              "evaluation_scope": "descriptive old calibration rows; tau uses these labels; not independent evaluation",
              "target_scope": "first action followed by frozen V3 Qref continuation, not the deployed gate policy",
              "baseline_origin": "previously selected strong ordinary action; unchanged",
              "selection_caveat": "ridge was already selected on these OOF folds; folds are not nested validation",
              "rule": "unique greedy action overrides baseline iff predicted advantage > tau; ties/equality keep baseline",
              "modes": {}}
    actions_by_mode = {}
    for mode in MODES:
        target, predicted, selected, replay_error = replays[mode]
        receipts = [choose(values, baseline_action, tau) for values in predicted]
        greedy = np.asarray([item["greedy"] for item in receipts])
        gated = np.asarray([item["chosen"] for item in receipts])
        actions_by_mode[mode] = {"greedy": greedy, "gated": gated}
        result["modes"][mode] = {
            "ridge": selected["ridge"], "dimension": selected["full_fit_head"]["dimension"],
            "prediction_replay_max_abs_error": replay_error,
            "oof_terminal_mse": float(np.square(predicted - target).mean()),
            "mode_max_abs_advantage_residual": float(np.max(np.abs(residuals[mode]))),
            "advantage_residual_rmse": float(np.sqrt(np.square(residuals[mode]).mean())),
            "reference": _policy_summary(target, np.full(len(target), baseline_action), baseline_action),
            "greedy": _policy_summary(target, greedy, baseline_action),
            "gated": _policy_summary(target, gated, baseline_action),
            "rows": [{"trajectory": row["trajectory"], "step": row["step"],
                      "target4": target[index].tolist(),
                      "advantage_residual4": residuals[mode][index].tolist(), **receipts[index]}
                     for index, row in enumerate(bank["records"])],
        }
    result["representation_comparison"] = {
        "prediction_max_abs_difference": float(np.max(np.abs(replays["field"][1] - replays["richer"][1]))),
        **{f"{policy}_disagreement_count": int(np.sum(actions_by_mode["field"][policy]
                                                      != actions_by_mode["richer"][policy]))
           for policy in ("greedy", "gated")},
    }
    return result


def load_saved(evidence_root, seed):
    """Load only the two known V3 fit artifacts; return bank, controllers, file identities."""
    _require(seed in BASELINE_ACTIONS, "Unknown seed")
    root = Path(evidence_root)
    paths = {"bank": root / "training_bank" / str(seed) / "BANK.json",
             "controllers": root / "training_fit" / str(seed) / "CONTROLLERS.json.gz"}
    raw = {name: path.read_bytes() for name, path in paths.items()}
    bank = json.loads(raw["bank"])
    decoded_controllers = gzip.decompress(raw["controllers"])
    controllers = json.loads(decoded_controllers)
    digest = lambda value: hashlib.sha256(value).hexdigest()
    _require(digest(raw["bank"]) == controllers["bank_sha256"], "Bank bytes differ from fitted identity")
    _require(bank["seed"] == seed and controllers["seed"] == seed, "Artifact seed mismatch")
    identities = {name + "_sha256": digest(value) for name, value in raw.items()}
    identities["controllers_uncompressed_sha256"] = digest(decoded_controllers)
    return bank, controllers, identities


def calibrate_all(evidence_root=DEFAULT_EVIDENCE):
    """Produce the three frozen-baseline calibrations without reading evaluation sources."""
    result = {"schema": "hepta.field-bridge.v5.empirical-calibration-suite.1", "seeds": {}}
    for seed in BASELINE_ACTIONS:
        bank, controllers, identities = load_saved(evidence_root, seed)
        result["seeds"][str(seed)] = {**calibrate_saved(bank, controllers), "source_identities": identities}
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--v3-evidence", type=Path, default=DEFAULT_EVIDENCE)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--include-rows", action="store_true", help="Include reproducible per-row OOF receipts")
    args = parser.parse_args()
    result = calibrate_all(args.v3_evidence)
    if not args.include_rows:
        for report in result["seeds"].values():
            for mode in MODES:
                del report["modes"][mode]["rows"]
        result["row_records_omitted_from_artifact"] = True
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x") as output:
        json.dump(result, output, indent=2, sort_keys=True, allow_nan=False)
        output.write("\n")
    print(json.dumps({seed: {"tau": value["tau"], "modes": {
        mode: {policy: value["modes"][mode][policy] for policy in ("reference", "greedy", "gated")}
        for mode in MODES}} for seed, value in result["seeds"].items()}, sort_keys=True))


if __name__ == "__main__":
    main()
