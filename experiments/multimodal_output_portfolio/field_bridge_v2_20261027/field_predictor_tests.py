"""Small statistical/interface contracts for frozen branch-delta predictors."""

import argparse
from copy import deepcopy
import json
from pathlib import Path
import time

import numpy as np

from . import field_predictor as fp


def fixture():
    rng = np.random.default_rng(271031)
    records = []
    for trajectory in range(8):
        for step in range(4):
            state = rng.normal(size=10)
            current = .55 + .03 * state[0]
            state[0] = current
            delta = np.array([.025 * state[1], -.02 * state[2], .015 * state[3]])
            values = np.r_[current, current + delta]
            records.append(dict(state=state.tolist(), current_value=current, action_values=values.tolist(),
                                trajectory=trajectory, step=8 * step, partition="fit"))
    return records


def rejected(callback):
    try:
        callback()
    except (ValueError, TypeError):
        return
    raise AssertionError("Invalid fitting/prediction input was accepted")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    if args.out.exists():
        raise ValueError("Refusing to overwrite predictor contract evidence")
    started = time.perf_counter_ns()
    records = fixture()
    controllers, budgets = {}, {}
    original_fit = fp._fit_family
    calls = []
    def tracked_fit(x, target, candidate):
        calls.append((len(x), fp.content_hash(candidate)))
        return original_fit(x, target, candidate)
    fp._fit_family = tracked_fit
    try:
        for mode in fp.MODES:
            calls.clear()
            controllers[mode] = fp.fit(records, mode)
            budgets[mode] = len(calls)
            assert len(calls) == 161
            assert all(rows == 28 for rows, _ in calls[:-1]) and calls[-1][0] == 32
            counts = {}
            for _, candidate in calls[:-1]:
                counts[candidate] = counts.get(candidate, 0) + 1
            assert len(counts) == 20 and set(counts.values()) == {8}
    finally:
        fp._fit_family = original_fit
    assert len({c["fit_content_sha256"] for c in controllers.values()}) == 1
    assert np.array_equal(controllers["generic"]["projection"], fp._projection(10, "generic"))

    field = controllers["field"]
    # Independently solve each first-candidate fold with augmented least squares,
    # rather than the production centered primal/dual normal equations.
    maximum_cv_difference = 0.
    for fold_index, fold in enumerate(field["cv"]["folds"]):
        train = [records[i] for i in fold["train_indices"]]
        held = [records[i] for i in fold["heldout_indices"]]
        assert all(r["trajectory"] != fold["heldout_trajectory"] for r in train)
        assert all(r["trajectory"] == fold["heldout_trajectory"] for r in held)
        raw = np.asarray([r["state"] for r in train])
        mean, scale = raw.mean(0), np.maximum(raw.std(0), fp.STD_FLOOR)
        assert np.array_equal(mean, fold["normalizer"]["mean"])
        assert np.array_equal(scale, fold["normalizer"]["scale"])
        train_x = np.clip((raw - mean) / scale, -10, 10)[:, :7]
        held_x = np.clip((np.asarray([r["state"] for r in held]) - mean) / scale, -10, 10)[:, :7]
        train_y = np.asarray([r["action_values"][1:] for r in train]) - np.asarray([r["current_value"] for r in train])[:, None]
        design = np.column_stack((train_x, np.ones(len(train_x))))
        penalty = np.diag(np.r_[np.full(7, .1), 0.])
        coefficient = np.linalg.lstsq(np.vstack((design, penalty)),
                                     np.vstack((train_y, np.zeros((8, 3)))), rcond=None)[0]
        current = np.asarray([r["current_value"] for r in held])
        delta = np.clip(np.column_stack((held_x, np.ones(len(held_x)))) @ coefficient, -2, 2)
        absolute = np.clip(current[:, None] + delta, -1.004, .998)
        expected = np.asarray([r["action_values"][1:] for r in held])
        mse = float(np.mean((absolute - expected) ** 2))
        recorded = field["cv"]["candidates"][0]["trajectory_mse"][fold_index]
        maximum_cv_difference = max(maximum_cv_difference, abs(mse-recorded))
    assert maximum_cv_difference < 1e-15
    no_change_mse = float(np.mean([(np.asarray(r["action_values"][1:])-r["current_value"])**2 for r in records]))
    selected_mse = field["cv"]["candidates"][field["selected_index"]]["mean_mse"]
    assert selected_mse < .1 * no_change_mse

    # A very large held-out feature cannot contaminate its fold normalizer.
    sentinel = deepcopy(records)
    for record in sentinel:
        if record["trajectory"] == 7:
            record["state"][9] = 1e8
    changed = fp.fit(sentinel, "field")
    before = next(f for f in field["cv"]["folds"] if f["heldout_trajectory"] == 7)
    after = next(f for f in changed["cv"]["folds"] if f["heldout_trajectory"] == 7)
    assert before["normalizer"] == after["normalizer"]
    assert before["train_record_sha256"] == after["train_record_sha256"]

    serialization_cases = 0
    for mode, controller in controllers.items():
        restored = json.loads(json.dumps(controller))
        for record in records[:4]:
            actual = fp.predict(controller, record["state"], record["current_value"])
            assert actual == fp.predict(restored, record["state"], record["current_value"])
            assert actual[0] == record["current_value"]
            serialization_cases += 1
    saved = fp.content_hash(field)
    original_normalizer, public_fit = fp._normalizer, fp.fit
    def forbidden(*args, **kwargs):
        raise AssertionError("Prediction attempted to fit a statistic")
    fp._fit_family, fp._normalizer, fp.fit = forbidden, forbidden, forbidden
    try:
        for record in records:
            fp.predict(field, record["state"], record["current_value"])
    finally:
        fp._fit_family, fp._normalizer, fp.fit = original_fit, original_normalizer, public_fit
    assert fp.content_hash(field) == saved

    invalid_count = 0
    for key, value in (("partition", "audit"), ("partition", "test"),
                       ("partition", "retention"), ("role", "audit")):
        invalid = deepcopy(records)
        invalid[0][key] = value
        rejected(lambda rows=invalid: fp.fit(rows, "field"))
        invalid_count += 1
    rejected(lambda: fp.fit(records[:-4], "field"))
    rejected(lambda: fp.fit(records + [records[0]], "field"))
    invalid = deepcopy(records)
    invalid[0]["action_values"][0] += .01
    rejected(lambda: fp.fit(invalid, "field"))
    rejected(lambda: fp.predict(field, records[0]["state"], records[0]["current_value"] + .1))
    invalid_count += 4

    clipped = deepcopy(field)
    clipped["fitted"]["coefficient"] = np.zeros_like(clipped["fitted"]["coefficient"]).tolist()
    clipped["fitted"]["target_mean"] = [100., -100., 100.]
    row = deepcopy(records[0]["state"])
    row[0] = .997
    np.testing.assert_allclose(fp.predict(clipped, row, .997), [.997, .998, -1.003, .998], rtol=0, atol=1e-15)
    row[0] = -.5
    assert fp.predict(clipped, row, -.5) == [-.5, .998, -1.004, .998]
    flat = deepcopy(records)
    for record in flat:
        record["action_values"] = [record["current_value"]] * 4
    tied = fp.fit(flat, "field")
    assert tied["selected_index"] == 0
    assert all(c["mean_mse"] == 0 for c in tied["cv"]["candidates"])
    report = dict(schema="hepta.field-bridge-v2.field-predictor-contract.v1", passed=True,
                  actual_fits_by_mode=budgets, complete_trajectory_exclusion=True,
                  fold_normalization_independent_least_squares_max_mse_difference=maximum_cv_difference,
                  heldout_sentinel_normalizer_unchanged=True, serialization_exact_cases=serialization_cases,
                  prediction_fit_calls_forbidden_and_passed=True, prediction_controller_unchanged=True,
                  invalid_inputs_rejected=invalid_count, exact_no_change=True, clipping_order_verified=True,
                  tied_candidate_first_selected=True, synthetic_linear_fixture_cv_mse=selected_mse,
                  synthetic_linear_fixture_no_change_mse=no_change_mse,
                  fixture_is_scientific_efficacy_evidence=False, wall_ns=time.perf_counter_ns()-started)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, sort_keys=True, indent=2)+"\n")
    print(json.dumps(report, sort_keys=True))


if __name__ == "__main__":
    main()
