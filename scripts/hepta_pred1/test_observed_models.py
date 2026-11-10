"""Behavioral checks on declared fixtures; these are not native-owner evidence."""

import copy
from hashlib import sha256
import json
from pathlib import Path
import tempfile
import unittest

import numpy as np

from .observed_models import ObservedModel, _canonical, _loss_grad, fit_observed_model


def row(index, action="fast", **changes):
    value = {
        "sample_id": str(index), "task_group": "group-" + str(index),
        "split": "train", "action_id": action, "features": [float(index), 0.0],
        "outcome_quality": index % 2, "duration_seconds": 0.125 + index * 0.25,
        "action_cost": 0.007 + index * 0.004, "outcome_status": "terminal",
        "time_status": "exact", "cost_status": "observed", "source": "fixture",
    }
    value.update(changes)
    return value


def fit(rows, kind="empirical", **options):
    settings = dict(kind=kind, feature_names=["x", "x_squared"],
                    action_ids=["fast", "slow", "unseen"],
                    success_definition="fixture terminal success", cost_unit="fixture credits",
                    hidden_size=8, seed=17, epochs=200, learning_rate=0.03)
    settings.update(options)
    return fit_observed_model(rows, **settings)


class ObservedModelTests(unittest.TestCase):
    def test_empirical_preserves_continuous_chosen_action_targets(self):
        model = fit([row(0), row(1), row(2, "slow", outcome_quality=1)])
        self.assertEqual(model.predict([100.0, -100.0], "fast"), {
            "success_probability": 0.5,
            "duration_values": [0.125, 0.375], "duration_probabilities": [0.5, 0.5],
            "cost_values": [0.007, 0.011], "cost_probabilities": [0.5, 0.5],
        })
        self.assertEqual(model.predict([0.0, 0.0], "slow")["success_probability"], 1.0)
        for features, action in (([0.0, 0.0], "unseen"), ([0.0], "fast"),
                                 ([float("nan"), 0.0], "fast")):
            with self.subTest(features=features, action=action), self.assertRaises(ValueError):
                model.predict(features, action)

    def test_unknown_cancel_censor_keep_exclusions_and_input_identity(self):
        rows = [row(0), row(1),
                row(2, outcome_status="unknown", time_status="unobserved", cost_status="unknown",
                    outcome_quality=None, duration_seconds=None, action_cost=None, features=[99999.0, 0.0]),
                row(3, outcome_status="cancel_requested", outcome_quality=None),
                row(4, outcome_status="right_censored", time_status="interval", outcome_quality=None)]
        model = fit(rows)
        self.assertEqual(model.predict([0.0, 0.0], "fast"), fit(rows[:2]).predict([0.0, 0.0], "fast"))
        report = model.metadata["training"]
        self.assertEqual((report["input_rows"], report["complete_case_rows"], report["excluded_rows"]), (5, 2, 3))
        self.assertEqual(report["exclusion_reason_counts"], {
            "outcome_unknown": 1, "time_unobserved": 1, "cost_unknown": 1,
            "outcome_cancel_requested": 1, "outcome_right_censored": 1, "time_interval": 1,
        })
        np.testing.assert_array_equal(model.center, [0.5, 0.0])
        self.assertEqual(report["used_task_groups"], ["group-0", "group-1"])
        rows[-1]["duration_seconds"] += 0.01
        self.assertNotEqual(report["input_sha256"], fit(rows).metadata["training"]["input_sha256"])
        with self.assertRaisesRegex(ValueError, "no complete-case"):
            fit(rows[2:])

    def test_split_identity_and_invalid_labels_are_refused_before_fit(self):
        cases = [
            [row(0), row(1, split="dev")],
            [row(0), row(1, split="confirm", task_group="group-0")],
            [row(0), row(0)],
            [row(0, outcome_quality=None)],
            [row(0, action_cost=-0.1)],
            [row(0, duration_seconds=float("nan"))],
            [row(0, features=[True, 0.0])],
        ]
        for rows in cases:
            with self.subTest(rows=rows), self.assertRaises(ValueError):
                fit(rows, "mlp")

    def test_analytic_gradient_matches_finite_differences(self):
        rng = np.random.default_rng(4)
        parameters = {"w1": rng.normal(0, 0.2, (3, 2)), "b1": rng.normal(0, 0.2, 2),
                      "w2": rng.normal(0, 0.2, (2, 3)), "b2": rng.normal(0, 0.2, 3)}
        inputs = rng.normal(size=(5, 3))
        targets = rng.uniform(size=(5, 3))
        targets[:, 0] = [0, 1, 0, 1, 0]
        _, gradient = _loss_grad(parameters, inputs, targets)
        for name, values in parameters.items():
            numerical = np.empty_like(values)
            for index in np.ndindex(values.shape):
                original = values[index]
                values[index] = original + 1e-6
                plus = _loss_grad(parameters, inputs, targets)[0]
                values[index] = original - 1e-6
                minus = _loss_grad(parameters, inputs, targets)[0]
                values[index] = original
                numerical[index] = (plus - minus) / 2e-6
            np.testing.assert_allclose(gradient[name], numerical, rtol=1e-6, atol=1e-9)

    def test_mlp_learns_actions_and_preserves_prediction_state(self):
        rows = []
        for x in np.linspace(-1, 1, 24):
            for action in ("fast", "slow"):
                slow = action == "slow"
                rows.append(row(len(rows), action, features=[float(x), float(x * x)],
                                outcome_quality=int(x + (-0.4 if slow else 0.4) > 0),
                                duration_seconds=float(0.12 + 0.02 * x + 0.03 * slow),
                                action_cost=float(0.005 + 0.001 * x + 0.002 * slow)))
        model = fit(rows, "mlp", epochs=600)
        self.assertLess(model.loss_history[-1], model.loss_history[0] * 0.1)
        before = {k: v.copy() for k, v in model.parameters.items()}
        fast, slow = model.predict([0.0, 0.0], "fast"), model.predict([0.0, 0.0], "slow")
        self.assertGreater(fast["success_probability"], 0.9)
        self.assertLess(slow["success_probability"], 0.1)
        for prediction, expected_duration, expected_cost in ((fast, 0.12, 0.005), (slow, 0.15, 0.007)):
            self.assertAlmostEqual(np.dot(prediction["duration_values"], prediction["duration_probabilities"]), expected_duration, delta=0.01)
            self.assertAlmostEqual(np.dot(prediction["cost_values"], prediction["cost_probabilities"]), expected_cost, delta=0.002)
        for name, value in before.items():
            np.testing.assert_array_equal(model.parameters[name], value)
        with self.assertRaisesRegex(ValueError, "unavailable"):
            model.predict([0.0, 0.0], "unseen")

    def test_pinned_checkpoint_replay_and_exact_adam_resume(self):
        rows = [row(i, "fast" if i % 2 else "slow") for i in range(8)]
        with tempfile.TemporaryDirectory() as directory:
            for kind in ("empirical", "mlp"):
                model = fit(rows, kind, epochs=10)
                path = Path(directory) / (kind + ".json")
                digest = model.save(path)
                restored = ObservedModel.load(path, expected_sha256=digest)
                self.assertEqual(restored.predict([1.25, 0.0], "fast"), model.predict([1.25, 0.0], "fast"))
                self.assertEqual(restored.save(path.with_suffix(".copy.json")), digest)
                with self.assertRaises(FileExistsError):
                    model.save(path)
                with self.assertRaises(ValueError):
                    ObservedModel.load(path, expected_sha256="0" * 64)
                if kind == "mlp":
                    with self.assertRaisesRegex(ValueError, "identity differs"):
                        restored.continue_fit(list(reversed(rows)), epochs=1)
                    restored.continue_fit(rows, epochs=10)
                    whole = fit(rows, "mlp", epochs=20)
                    for name in whole.parameters:
                        for left, right in ((restored.parameters, whole.parameters),
                                            (restored.m, whole.m), (restored.v, whole.v)):
                            np.testing.assert_array_equal(left[name], right[name])
                    self.assertEqual(restored.loss_history, whole.loss_history)
                    self.assertEqual(restored.predict([1.25, 0.0], "fast"), whole.predict([1.25, 0.0], "fast"))

    def test_rehashed_checkpoint_still_requires_source_and_shapes(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "model.json"
            fit([row(0), row(1)], "mlp", epochs=1).save(path)
            original = json.loads(path.read_bytes())
            for change in ("source", "shape", "numpy"):
                data = copy.deepcopy(original)
                if change == "source":
                    data["payload"]["metadata"]["source_sha256"] = "0" * 64
                elif change == "numpy":
                    data["payload"]["metadata"]["numpy_version"] = "different"
                else:
                    data["payload"]["parameters"]["w1"].pop()
                data["payload_sha256"] = sha256(_canonical(data["payload"])).hexdigest()
                encoded = _canonical(data)
                corrupted = path.with_name(change + ".json")
                corrupted.write_bytes(encoded)
                with self.subTest(change=change), self.assertRaises(ValueError):
                    ObservedModel.load(corrupted, expected_sha256=sha256(encoded).hexdigest())

    def test_rehashed_checkpoint_rejects_learning_rate_and_work_ledger_drift(self):
        mutations = [
            (("metadata", "learning_rate"), -1.0),
            (("metadata", "learning_rate"), 0.0),
            (("metadata", "learning_rate"), 1.01),
            (("metadata", "optimizer_calls"), 0),
            (("metadata", "sample_presentations"), 0),
            (("metadata", "training", "complete_case_rows"), 1),
            (("metadata", "training", "input_rows"), 3),
            (("metadata", "training", "excluded_rows"), 1),
        ]
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "original.json"
            fit([row(0), row(1)], "mlp", epochs=2).save(path)
            original = json.loads(path.read_bytes())
            for index, (keys, value) in enumerate(mutations):
                data = copy.deepcopy(original)
                target = data["payload"]
                for key in keys[:-1]:
                    target = target[key]
                target[keys[-1]] = value
                data["payload_sha256"] = sha256(_canonical(data["payload"])).hexdigest()
                encoded = _canonical(data)
                corrupted = path.with_name(f"corrupt-{index}.json")
                corrupted.write_bytes(encoded)
                with self.subTest(keys=keys, value=value), self.assertRaisesRegex(ValueError, "learning rate|ledger"):
                    ObservedModel.load(corrupted, expected_sha256=sha256(encoded).hexdigest())
