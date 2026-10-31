"""Focused pre-access checks; only synthetic and already historical public inputs."""

import argparse
import copy
import json
from pathlib import Path

import numpy as np

from ...abc_recovery.training_run import file_sha, write_json
from .analysis import paired_intervals
from .boundaries import check_arrays
from .protocol import forecasts, heads, segments, verify
from ..native.forecast import Q


def synthetic():
    pair = np.repeat(np.arange(1000), 2)
    action = np.tile(np.arange(2), 1000)
    view = np.repeat(np.concatenate([np.repeat(v, n) for v, _, n in segments()]), 2)
    x = np.zeros((2000, 478), dtype=np.int64)
    x[:, 476:478] = np.eye(2, dtype=np.int64)[action] * Q
    x[pair >= 500, 460] = Q; x[pair >= 500, 471] = Q
    return {"x_q24": x, "past_q24": np.zeros((2000, 32), dtype=np.int64),
        "future_q24": np.zeros((2000, 32), dtype=np.int64),
        "future_tokens": np.zeros((2000, 8), dtype=np.int64),
        "forecast": np.zeros((2000, 3, 32)), "raw_probability": np.full((2000, 3), .5),
        "calibrated_probability": np.full((2000, 3), .5),
        "calibration_group": np.zeros((2000, 3), dtype=np.int64),
        "y": np.zeros(2000, dtype=np.int64), "pair": pair, "action": action,
        "ood": pair >= 500, "view": view}


def check(protocol, output):
    spec = verify(protocol); valid = synthetic(); check_arrays(valid)
    cases = {
        "duplicate_source_action": ("pair", 0, 1),
        "action_input_identity": ("action", 0, 1),
        "view_relabel": ("view", 0, "both_missing"),
        "absence_relabel": ("ood", 0, True),
        "nonbinary_label": ("y", 0, 2),
        "out_of_domain_token": ("future_tokens", (0, 0), 24),
        "invalid_frozen_bin": ("calibration_group", (0, 0), 8),
        "nonfinite_prediction": ("raw_probability", (0, 0), np.nan),
        "missing_action_feature": ("x_q24", (0, 476), 0),
    }
    passed = ["complete_synthetic_census"]
    for name, (key, index, value) in cases.items():
        damaged = copy.deepcopy(valid); damaged[key][index] = value
        try:
            check_arrays(damaged)
        except ValueError:
            passed.append(name)
        else:
            raise AssertionError("Boundary accepted " + name)
    # Anticorrelated branches cancel inside every source. Resampling rows would
    # invent variance and pseudo-replication; source-pair resampling must not.
    advantage = np.tile([[.2, -.3], [-.2, .3]], (1000, 1))
    paired, interval = paired_intervals(advantage, valid["pair"])
    if np.any(paired) or np.any(interval):
        raise AssertionError("Within-source dependence was lost")
    passed.append("paired_bootstrap_preserves_opposite_branch_dependence")
    historical = Path(spec["paths"]["historical_public_inputs"])
    with np.load(historical, allow_pickle=False) as data:
        x = data["x_q24"][:32]
    models, calibration = heads(spec); prediction = forecasts(models, calibration, x)
    changes = np.max(np.abs(prediction["raw_probability"][:, 1:] - prediction["raw_probability"][:, :1]), axis=0)
    if not (changes > 0).all():
        raise AssertionError("Real frozen proposals did not change actual forward probabilities")
    passed.append("actual_fixed_candidates_change_only_correctness_forward_on_historical_inputs")
    result = {"schema": "hepta.abc4.native-candidate-focused-checks.v1",
        "protocol_sha256": file_sha(protocol), "passed": passed, "count": len(passed),
        "historical_data_sha256": file_sha(historical), "max_raw_probability_changes": changes.tolist(),
        "repair_sources_materialized": False, "new_future_outcomes_opened": False}
    write_json(output, result)
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--protocol", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(); check(args.protocol, args.output)
