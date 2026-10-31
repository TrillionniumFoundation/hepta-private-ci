"""Independent algebra, public-information and preparation contract checks."""

import argparse
from copy import deepcopy
import hashlib
import json
from pathlib import Path

import numpy as np
from scipy.special import expit

from .. import learners, retention, task
from ..round2 import adaptation
from . import calibration, calibration_study


def validate():
    checks, maxima = [], {}

    def require(name, value, detail=None):
        checks.append({"name": name, "passed": bool(value), "detail": detail})

    anchor = {"kind": "filter", "parameters": [.12, .18, 1.0],
              "planning_q": .18, "planning_noise_scale": 1.0}
    adaptive = {**anchor, "parameters": [.32, .21, .9]}
    old = task.build_dataset(91001001, 96, "train", "gaussian")
    new = task.build_dataset(91001002, 96, "retention_train", "drift_shift")
    history = task.history(new)
    component = calibration.components(anchor, adaptive, history)
    target = task.targets(new)
    raw = np.array([-.2, .8, .03, -.02, .04, .1])
    objective, gradient = calibration.objective_gradient(raw, component, target)
    numerical = []
    for j in range(6):
        delta = np.zeros(6)
        delta[j] = 1e-5
        plus = calibration.objective_gradient(raw + delta, component, target)[0]
        minus = calibration.objective_gradient(raw - delta, component, target)[0]
        numerical.append((plus - minus) / 2e-5)
    maxima["gradient_central_difference_error"] = float(np.max(abs(gradient - numerical)))
    require("analytic_gradient_vs_central_difference", maxima["gradient_central_difference_error"] < 2e-9)
    m0, v0, m1, v1, features = component
    gate = expit(features @ raw[:2])[:, None]
    # Independent E[X^2]-E[X]^2 expression, instead of implementation's stable identity.
    expected_mean = (1 - gate) * m0 + gate * m1
    expected_variance = ((1 - gate) * (v0 + m0 * m0) + gate * (v1 + m1 * m1)
                         - expected_mean * expected_mean) * np.exp(raw[2:])
    expected_objective = float(np.mean(.5 * (np.log(2 * np.pi * expected_variance)
        + (target - expected_mean) ** 2 / expected_variance)) + .001 * np.sum(raw ** 2))
    require("independent_second_moment_objective", abs(objective - expected_objective) < 1e-13)

    sequential_ll = adaptation.public_log_likelihood(adaptive, history)
    dense_ll = calibration.dense_log_likelihood(adaptive, history)
    maxima["dense_vs_innovation_log_likelihood"] = float(np.max(abs(sequential_ll - dense_ll)))
    require("dense_covariance_vs_innovation_likelihood", maxima["dense_vs_innovation_log_likelihood"] < 1e-12)
    model, fit = calibration.fit_model(anchor, adaptive, [old, new])
    require("six_parameters_actually_optimized", fit["optimizer_success"] and fit["parameter_l2_change"] > 1e-6,
            {key: fit[key] for key in ("optimizer_iterations", "parameter_l2_change", "optimizer_message")})
    mean, variance = calibration.predict(model, history)
    dense = {**deepcopy(model), "classical": True}
    dm, dv = calibration.predict(dense, history)
    maxima["dense_vs_sequential_forecast"] = max(float(np.max(abs(dm - mean))), float(np.max(abs(dv - variance))))
    require("independent_classical_forecast", maxima["dense_vs_sequential_forecast"] < 1e-12)

    tampered = {key: np.array(value, copy=True) for key, value in history.items()}
    unseen = ~(tampered["mask"] & tampered["occupied"])
    tampered["obs"][unseen] = np.nan
    tampered["obs_var"][unseen] = np.nan
    tampered.update({"future": np.full((96, 6), 1e99), "law": "anything", "window": 999})
    tampered["ids"] = np.array(["arbitrary"] * 96)
    tm, tv = calibration.predict(model, tampered)
    require("no_private_or_missing_storage_feature", np.array_equal(tm, mean) and np.array_equal(tv, variance))
    same_time = task.append_observation(history, np.zeros(96), task.latest_time(history), .04, "validation")
    ll_error = np.max(abs(calibration.dense_log_likelihood(adaptive, same_time)
                          - adaptation.public_log_likelihood(adaptive, same_time)))
    require("simultaneous_sensors_count_once", ll_error < 1e-11, float(ll_error))

    old_dev = task.build_dataset(91001003, 128, "calibration_development", "gaussian")
    new_dev = task.build_dataset(91001004, 128, "calibration_development", "drift_shift")
    selected, selection = calibration.select_model(model, old_dev, new_dev)
    require("all_55_selection_candidates_retained", len(selection["candidates"]) == 55)
    candidates = selection["candidates"]
    eligible = [i for i, row in enumerate(candidates) if row["old"]["selection_upper_heuristic"] <= .02]
    independent_choice = min(eligible, key=lambda i: (candidates[i]["new"]["gaussian_nll"], i))
    require("selector_eligibility_and_global_grid_argmin", independent_choice == selection["selected_index"]
            and all(row["eligible"] == (i in eligible) for i, row in enumerate(candidates)))
    selected_mean, selected_variance = calibration.predict(selected, task.history(old_dev))
    old_mean, old_variance = learners.predict(anchor, task.history(old_dev))
    target = task.targets(old_dev)[:, 1:]
    losses = .5 * (np.log(selected_variance[:, 1:] / old_variance[:, 1:])
        + (target - selected_mean[:, 1:]) ** 2 / selected_variance[:, 1:]
        - (target - old_mean[:, 1:]) ** 2 / old_variance[:, 1:])
    require("selected_loss_independently_recomputed",
            abs(float(losses.mean()) - candidates[independent_choice]["old"]["paired_nll_change"]) < 1e-13)
    fallback = {**deepcopy(model), "strength": 0.0, "variance_inflation": 1.0}
    fm, fv = calibration.predict(fallback, history)
    am, av = learners.predict(anchor, history)
    require("exact_anchor_feasible_fallback", np.array_equal(fm, am) and np.array_equal(fv, av))

    quantized = {**deepcopy(selected), "output_quantization": "q24_parameters_nearest"}
    qm, qv, details = calibration.predict_details(quantized, history)
    require("q24_parameters_are_exact_integer_grid", np.array_equal(qm * (1 << 24), details["mean_q24"])
            and np.array_equal(qv * (1 << 24), details["variance_q24"]) and np.all(qv > 0))
    qdense = {**deepcopy(quantized), "classical": True}
    qdm, qdv = calibration.predict(qdense, history)
    require("q24_classical_exact_fixture_parity", np.array_equal(qm, qdm) and np.array_equal(qv, qdv))
    roundtrip = json.loads(json.dumps(quantized))
    rm, rv = calibration.predict(roundtrip, history)
    require("serialized_model_recovers_exactly", np.array_equal(rm, qm) and np.array_equal(rv, qv))
    require("empirical_profile_never_claims_universal_bound",
            quantized["universal_pointwise_retention_guarantee"] is False
            and details["pointwise_retention_certificate"] is None)
    protected = adaptation.make_model(anchor, adaptive, epsilon=.02)
    pm, pv, pd = calibration.predict_details(protected, history)
    direct = adaptation.predict_details(protected, history)
    require("inherited_pointwise_profile_unchanged", np.array_equal(pm, direct[0]) and np.array_equal(pv, direct[1])
            and np.max(pd["pointwise_nll_bound"]) <= .02)

    rejected = 0
    for operation in (
        lambda: calibration.fit_model(anchor, adaptive, [{**old, "split": "confirmation"}, new]),
        lambda: calibration.select_model(model, {**old_dev, "split": "confirmation"}, new_dev),
        lambda: calibration.select_model(model, old_dev, new_dev, .03),
        lambda: calibration.predict({**model, "universal_pointwise_retention_guarantee": True}, history),
    ):
        try:
            operation()
        except ValueError:
            rejected += 1
    require("holdout_fit_and_false_guarantee_rejected", rejected == 4)
    reg = calibration_study.registration()
    planned = [calibration_study.data_seed(reg, seed, window, code)
               for seed in reg["seeds"] for window in range(12) for code in (1, 2, 3, 4)]
    planned += [calibration_study.data_seed(reg, seed, 12, 5) for seed in reg["seeds"]]
    require("all_245_registered_dataset_seeds_distinct", len(planned) == len(set(planned)) == 245)
    root = Path(__file__).resolve().parent
    sources = {path.name: hashlib.sha256(path.read_bytes()).hexdigest()
               for path in [root / "calibration.py", root / "calibration_study.py", Path(__file__).resolve()]}
    return {"schema": "hepta.analytic-event.calibration-validation.v1", "passed": all(row["passed"] for row in checks),
            "checks": checks, "maxima": maxima, "source_sha256": sources,
            "fixtures_are_separate_train_and_development_data": True, "confirmation_generated": False,
            "validation_fit_receipt": fit, "validation_selection": selection}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = validate()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, sort_keys=True, indent=2, allow_nan=False) + "\n")
    print(json.dumps({"passed": result["passed"], "checks": len(result["checks"]), "maxima": result["maxima"]}))
    if not result["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
