"""Separately registered native carrier for a genuine future-correctness forecast.

The32 observed coordinates cancel in this confidence carrier. They are not a
future-state prediction. The original state forecast and residual contract are
retained and evaluated independently by the unchanged primary study.
"""

import argparse
import json
from pathlib import Path

import numpy as np
from scipy.stats import beta

from ...abc_recovery.training_run import file_sha, write_json
from .analysis import ece_interval, interval, source_mean
from .boundaries import verified_data
from .forecast import Q, groups, predict, quantize
from .qualify import check_freeze, ece


def predictions(weights, calibration, x, observed):
    forecast, raw = predict(weights, x)
    group = groups(x, raw, calibration["cuts"])
    probability = np.asarray(calibration["probabilities"])[group]
    prediction = quantize(np.column_stack((probability, observed)))
    drive = quantize(np.column_stack((np.ones(len(x)), observed)))
    error = np.abs(drive - prediction).max(1)
    ood = np.minimum(error * 1_000_000 // Q, 1_000_000)
    return forecast, probability, prediction, drive, 1_000_000 - ood, ood


def statistics(weights, calibration, data, bootstrap):
    _, probability, _, _, cp, op = predictions(weights, calibration, data["x_q24"] / Q,
                                              data["future_q24"] / Q)
    y, pair, ood = data["y"], data["pair"], data["ood"]
    accepted = (cp >= 750000) & (op <= 500000)
    ood_ids = np.unique(pair[ood])
    false_pairs = int(sum(accepted[pair == key].any() for key in ood_ids))
    upper = 1.0 if false_pairs == len(ood_ids) else float(beta.ppf(.95, false_pairs + 1,
                                                               len(ood_ids) - false_pairs))
    result = {"rows": len(y), "source_pairs": len(np.unique(pair)),
        "id_source_pairs": len(np.unique(pair[~ood])), "ood_source_pairs": len(ood_ids),
        "native_ece_id": ece(cp[~ood] / 1e6, y[~ood]), "native_ece_full": ece(cp / 1e6, y),
        "prospective_brier": float(np.mean((probability - y) ** 2)),
        "id_accepted_rows": int(accepted[~ood].sum()),
        "id_acceptance_fraction": float(accepted[~ood].mean()),
        "ood_false_accepted_rows": int(accepted[ood].sum()),
        "ood_false_accepted_source_pairs": false_pairs,
        "ood_false_acceptance_pair_rate": false_pairs / len(ood_ids),
        "ood_false_acceptance_pair_upper95": upper}
    if bootstrap:
        rng = np.random.default_rng(194018)
        result["ece_source_bootstrap_descriptive95"] = {
            "id": ece_interval(cp[~ood] / 1e6, y[~ood], pair[~ood], rng),
            "full": ece_interval(cp / 1e6, y, pair, rng)}
        result["id_acceptance_source_bootstrap_descriptive95"] = interval(
            source_mean(accepted[~ood], pair[~ood]), rng)
    return result


def verify(protocol, supplement, data, calibration_data, model, output):
    registration = json.loads(supplement.read_text())
    if registration["original_protocol_sha256"] != file_sha(protocol):
        raise ValueError("Supplement refers to another primary protocol")
    for name, digest in registration["source_pins"].items():
        if file_sha(Path(__file__).parent / name) != digest:
            raise ValueError("Supplement implementation changed: " + name)
    if registration["calibrator_freeze_sha256"] != file_sha(model / "calibrator-freeze.json"):
        raise ValueError("Supplement calibrator changed")
    check_freeze(protocol, model, "calibrator-freeze.json")
    weights = json.loads((model / "weights.json").read_text())
    calibration = json.loads((model / "calibration.json").read_text())
    before = statistics(weights, calibration, verified_data(calibration_data, protocol, "calibration"), False)
    result = statistics(weights, calibration, verified_data(data, protocol, "verification"), True)
    result["native_measured_ece_ppm"] = int(np.ceil(max(before["native_ece_id"],
        before["native_ece_full"], result["native_ece_id"], result["native_ece_full"]) * 1e6))
    result["native_measured_false_acceptance_ppm"] = int(np.ceil(max(
        before["ood_false_acceptance_pair_rate"], result["ood_false_acceptance_pair_rate"]) * 1e6))
    result["gates"] = {
        "calibration_and_verification_point_ece": result["native_measured_ece_ppm"] <= 30000,
        "calibration_and_verification_point_far": result["native_measured_false_acceptance_ppm"] <= 4999,
        "calibration_and_verification_id_nonvacuity": min(before["id_acceptance_fraction"],
                                                           result["id_acceptance_fraction"]) >= .25,
        "verification_ood_source_pair_upper95": result["ood_false_acceptance_pair_upper95"] <= .004999}
    result.update({"schema": "hepta.abc4.future-correctness-verification.v1",
        "supplement_sha256": file_sha(supplement), "original_protocol_sha256": file_sha(protocol),
        "calibrator_freeze_sha256": file_sha(model / "calibrator-freeze.json"),
        "data_sha256": file_sha(data / "data.npz"), "calibration": before,
        "study_qualified": all(result["gates"].values()),
        "native_config_point_qualified": result["gates"]["calibration_and_verification_point_ece"]
            and result["gates"]["calibration_and_verification_point_far"],
        "new_independent_samples_beyond_primary": 0,
        "scope": "same frozen genuine future-correctness probability; observed state cancels only in confidence carrier; no future-latent forecast claim for copied coordinates"})
    output.mkdir(parents=True, exist_ok=False)
    write_json(output / "verification.json", result)
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("protocol", "supplement", "data", "calibration-data", "model", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    args = parser.parse_args()
    verify(args.protocol, args.supplement, args.data, args.calibration_data, args.model, args.output)
