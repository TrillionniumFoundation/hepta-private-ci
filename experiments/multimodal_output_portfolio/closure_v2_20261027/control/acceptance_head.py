"""Supervised quality head using public readback probabilities and embeddings."""

import argparse
import json
from pathlib import Path

import numpy as np
import torch

from ...continuation_20261027.joint.run import reference_observer
from .protocol import preserve_sources, sha, write
from .verify_media import read_outputs


SPEC = {
    "schema": "hepta.ndu.selective-public-outcome-head.v1",
    "data": "Only the previous historical fit and validation actual candidates; no new test outputs",
    "features": "Frozen public reward CNN probabilities and 128 image embedding values, arrived-scalar inferred digit one-hots, caption/recognizer agreement",
    "supervision": "Frozen audit CNN strict semantic outcome on historical fit candidates; audit CNN never becomes a runtime input",
    "fit": "Standardized ridge least squares proper Bernoulli-mean regression; clamp probability to[0.001,0.999]",
    "ridge_candidates": [0.1, 1.0, 10.0, 100.0, 1000.0],
    "probability_thresholds": [round(value, 3) for value in np.arange(.75, 1.0, .01)],
    "selection": "Highest validation coverage subject to zero validation incorrect commits, fit incorrect-commit-rate<=.004999, validation IDcoverage>=.25; ties lower validation Brier then larger ridge then higher threshold",
    "calibration_still_required": True,
    "qualification_outcomes_used": False,
}


def public_vector(delivery, features, observer):
    pixels, _ = read_outputs(delivery)
    with torch.inference_mode():
        halves = torch.cat((torch.from_numpy(pixels[:, :, :, :28]), torch.from_numpy(pixels[:, :, :, 28:])), dim=0)
        embeddings = observer.net[:-1](halves)
        probabilities = observer.net[-1](embeddings).softmax(-1)
    inferred = features["inferred_order_from_arrived_scalar"]
    indicators = np.zeros((2, 10))
    if inferred:
        indicators[0, inferred[0]] = indicators[1, inferred[1]] = 1.0
    return np.r_[float(features["feedback_known"]), float(features["caption_matches_inferred_order"]),
        float(features["public_image_argmax_agrees"]), features["minimum_inferred_digit_probability"],
        indicators.ravel(), probabilities.numpy().ravel(), embeddings.numpy().ravel()]


def predicted(model, feature_matrix):
    normalized = (feature_matrix - np.asarray(model["mean"])) / np.asarray(model["scale"])
    return np.clip(normalized @ np.asarray(model["weights"]) + model["intercept"], .001, .999)


def run(assets, development, acceptance_development, output):
    output.mkdir(parents=True, exist_ok=False)
    torch.set_num_threads(1)
    torch.use_deterministic_algorithms(True)
    write(output / "PROTOCOL.json", SPEC)
    preserve_sources(output / "executed-source")
    observer = reference_observer(assets, "reward")
    declared = json.loads((acceptance_development / "FEATURE_ROWS.json").read_text())
    data = {split: json.loads((development / filename).read_text()) for split, filename in (("fit", "FIT.json"), ("validation", "VALIDATION.json"))}
    x, y, eligible, roles = [], [], [], []
    for row in declared:
        raw = data[row["split"]][row["index"]]
        delivery = raw["alternate_delivery"] if row["actual_native_continuation_choice"] else raw["initial_delivery"]
        x.append(public_vector(delivery, row["features"], observer))
        y.append(row["strict_success"])
        eligible.append(row["features"]["feedback_known"] and row["features"]["caption_matches_inferred_order"]
                        and row["features"]["public_image_argmax_agrees"])
        roles.append(row["split"])
    x, y, eligible, roles = np.asarray(x), np.asarray(y), np.asarray(eligible), np.asarray(roles)
    fitting = (roles == "fit") & eligible
    mean, scale = x[fitting].mean(0), np.maximum(x[fitting].std(0), .001)
    normalized = (x - mean) / scale
    features = np.c_[np.ones(fitting.sum()), normalized[fitting]]
    candidates, models = [], {}
    for ridge in SPEC["ridge_candidates"]:
        regularization = np.eye(features.shape[1]) * ridge
        regularization[0, 0] = 1e-8
        weights = np.linalg.solve(features.T @ features + regularization, features.T @ y[fitting])
        model = {"ridge": ridge, "mean": mean.tolist(), "scale": scale.tolist(),
            "intercept": float(weights[0]), "weights": weights[1:].tolist()}
        probability = predicted(model, x)
        models[str(ridge)] = model
        for threshold in SPEC["probability_thresholds"]:
            row = {"ridge": ridge, "threshold": threshold}
            for split in ("fit", "validation"):
                chosen = roles == split
                accepted = chosen & eligible & (probability >= threshold)
                errors = int(np.sum(accepted & (y == 0)))
                row[split] = {"n": int(chosen.sum()), "accepted": int(accepted.sum()), "incorrect_commits": errors,
                    "coverage": float(accepted.sum() / chosen.sum()), "incorrect_commit_rate": float(errors / chosen.sum()),
                    "eligible_brier": float(np.mean((probability[chosen & eligible] - y[chosen & eligible]) ** 2))}
            candidates.append(row)
    feasible = [r for r in candidates if r["fit"]["incorrect_commit_rate"] <= .004999
        and r["validation"]["incorrect_commits"] == 0 and r["validation"]["coverage"] >= .25]
    selected = min(feasible, key=lambda r: (-r["validation"]["coverage"], r["validation"]["eligible_brier"], -r["ridge"], -r["threshold"])) if feasible else None
    write(output / "MODELS.json", models)
    np.savez_compressed(output / "PUBLIC_FEATURES.npz", features=x, outcome=y, eligible=eligible, role=roles)
    if selected:
        write(output / "SELECTED_MODEL.json", {**models[str(selected["ridge"])], "threshold": selected["threshold"],
            "source_feature_rows_sha256": sha(acceptance_development / "FEATURE_ROWS.json"),
            "public_feature_dimension": x.shape[1], "calibrated": False})
    result = {"feasible_for_separate_calibration": selected is not None, "selected": selected,
        "all_candidates": candidates, "models_sha256": sha(output / "MODELS.json"),
        "public_features_sha256": sha(output / "PUBLIC_FEATURES.npz"), "source_pairs_fit": int(np.sum(roles == "fit")),
        "source_pairs_validation": int(np.sum(roles == "validation")), "qualifications_consumed": 0}
    write(output / "RESULT.json", result)
    print(json.dumps({k: v for k, v in result.items() if k != "all_candidates"}), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    for name in ("assets", "development", "acceptance-development", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    args = parser.parse_args()
    run(args.assets, args.development, args.acceptance_development, args.output)
