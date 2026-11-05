"""Independent identities, behavioral failures and retained-record audits."""

from dataclasses import replace
from itertools import product
import json
import unittest
from unittest.mock import patch

import numpy as np

from . import structure as s


class StructureTests(unittest.TestCase):
    def setUp(self):
        self.p = s.Panel()
        self.cfg = {**s.protocol(), "train_n": 24, "test_n": 12, "neural_updates": 12}
        self.data = s.observations(self.p, 11, 24, self.cfg)
        self.x = np.asarray([[-0.8, 0.2], [0.3, -0.5], [0.4, 0.9]])

    def test_gaussian_expectation_and_gradient_have_independent_integral(self):
        nodes, weights = np.polynomial.hermite.hermgauss(12)
        p = replace(self.p, noise=0.7)

        def integrate(x):
            return sum(
                weights[i]
                * weights[j]
                / np.pi
                * s.quality(x + p.noise * np.sqrt(2) * np.asarray([nodes[i], nodes[j]]), p)
                for i, j in product(range(12), repeat=2)
            )

        v, g = s.exact_value_gradient(self.x, p)
        np.testing.assert_allclose(v, integrate(self.x), atol=1e-12, rtol=0)
        numerical = np.stack(
            [(integrate(self.x + e * 1e-5) - integrate(self.x - e * 1e-5)) / 2e-5 for e in np.eye(2)], axis=1
        )
        np.testing.assert_allclose(g, numerical, atol=2e-10, rtol=0)

    def test_critic_gradients_match_numerical_derivatives(self):
        for family in self.cfg["families"]:
            with self.subTest(family=family):
                model = s.fit(family, "value", self.data, self.p, 11, self.cfg)
                numerical = np.stack(
                    [
                        (s.predict(model, self.x + e * 1e-5)[:, 0] - s.predict(model, self.x - e * 1e-5)[:, 0]) / 2e-5
                        for e in np.eye(2)
                    ],
                    axis=1,
                )
                np.testing.assert_allclose(s.predict(model, self.x, True), numerical, atol=2e-9, rtol=0)

    def test_data_and_fitting_do_not_read_privileged_analytic_values(self):
        with patch.object(s, "exact_value_gradient", side_effect=AssertionError("oracle access")):
            data = s.observations(self.p, 17, 20, self.cfg)
            for family in self.cfg["families"]:
                for target in self.cfg["targets"]:
                    model = s.fit(family, target, data, self.p, 17, self.cfg)
                    self.assertEqual(model["fit"]["source_observations_sha256"], data["sha256"])

    def test_z_scaling_has_no_manufactured_advantage_at_small_noise(self):
        for sigma in (0.2, 1e-6):
            p = replace(self.p, noise=sigma)
            data = s.observations(p, 19, 24, self.cfg)
            for family in self.cfg["families"]:
                direct = s.fit(family, "direct_gradient", data, p, 19, self.cfg)
                z = s.fit(family, "z_gradient", data, p, 19, self.cfg)
                np.testing.assert_allclose(s.predict(direct, self.x), s.predict(z, self.x), atol=2e-12, rtol=0)
                self.assertEqual(
                    [s.select(direct, x, p, self.cfg) for x in self.x], [s.select(z, x, p, self.cfg) for x in self.x]
                )

    def test_zero_noise_keeps_the_unidentified_rows(self):
        case = s.run_case(replace(self.p, name="zero", noise=0), 23, self.cfg)
        rows = [r for r in case["records"] if r["kind"] == "z_gradient"]
        self.assertEqual([r["status"] for r in rows], ["unidentified"] * 3)
        self.assertEqual(len(case["records"]), 12)
        self.assertTrue(all("failed_cpu_ns" in r for r in rows))

    def test_failed_fit_is_retained_and_other_models_continue(self):
        original = s.fit

        def fail_quadratic(family, *args):
            if family == "quadratic":
                raise ValueError("deliberate failed fit")
            return original(family, *args)

        with patch.object(s, "fit", side_effect=fail_quadratic):
            result = s.run_case(self.p, 29, self.cfg)
        failed = [r for r in result["records"] if r["status"] == "failed"]
        self.assertEqual(len(result["records"]), 12)
        self.assertEqual(len(failed), 3)
        self.assertTrue(all(r["error"] == "deliberate failed fit" for r in failed))

    def test_resource_residency_and_reset_change_actual_actions_and_costs(self):
        p = replace(self.p, capacity=1, resident=1, load_cost=0.15, reset_probability=0.3)
        values, _, charges, names = s.action_values(self.x, p, self.cfg)
        self.assertNotIn("joint_plus", names)
        self.assertAlmostEqual(charges[names.index("adjust_1_plus")] - charges[names.index("adjust_0_plus")], 0.15)
        v0 = s.exact_value_gradient(np.zeros_like(self.x), p)[0]
        vx = s.exact_value_gradient(self.x, p)[0]
        np.testing.assert_allclose(values[:, -1], 0.3 * v0 + 0.7 * vx - self.cfg["reset_cost"], atol=1e-15)
        high = replace(self.p, adjustment=100, reset_probability=0)
        self.assertEqual(np.argmax(s.action_values(self.x, high, self.cfg)[0], axis=1).tolist(), [0, 0, 0])

    def test_model_error_is_a_shared_observation_shift(self):
        shifted = replace(self.p, model_bias=0.3)
        biased = s.observations(shifted, 11, 24, self.cfg)
        np.testing.assert_array_equal(self.data["x"], biased["x"])
        self.assertGreater(float(np.max(np.abs(self.data["values"] - biased["values"]))), 0.1)
        self.assertNotEqual(self.data["sha256"], biased["sha256"])

    def test_neural_training_changes_parameters_and_reduces_training_error(self):
        early = s.fit("neural", "direct_gradient", self.data, self.p, 11, {**self.cfg, "neural_updates": 1})
        late = s.fit("neural", "direct_gradient", self.data, self.p, 11, {**self.cfg, "neural_updates": 60})
        self.assertNotEqual(early["fit"]["parameter_sha256"], late["fit"]["parameter_sha256"])
        early_mse = np.mean((s.predict(early, self.data["x"]) - self.data["gradients"]) ** 2)
        late_mse = np.mean((s.predict(late, self.data["x"]) - self.data["gradients"]) ** 2)
        self.assertLess(late_mse, early_mse)

    def test_raw_records_reproduce_rewards_choices_and_checkpoints(self):
        case = s.run_case(self.p, 31, self.cfg)
        x = np.asarray(case["public_test_states"])
        eps, success = np.asarray(case["evaluation_noise"]), np.asarray(case["evaluation_reset_success"])
        targets = s.actions(x, self.p, self.cfg)[0]
        targets[:, -1, :] = np.where(success[:, None], 0, x)
        potential_quality = s.quality(targets + self.p.noise * eps[:, None, :], self.p)
        for record in case["records"]:
            raw = record["raw"]
            choices = np.asarray(raw["choices"])
            np.testing.assert_array_equal(potential_quality[np.arange(len(x)), choices], raw["observed_quality"])
            self.assertAlmostEqual(
                np.mean(np.asarray(raw["observed_quality"]) - raw["fees"]), record["metrics"]["observed_net_value"]
            )
            if "model" in record:
                model = {
                    **record["model"],
                    "mean": np.asarray(record["model"]["mean"]),
                    "scale": np.asarray(record["model"]["scale"]),
                    "parameters": [np.asarray(p) for p in record["model"]["parameters"]],
                }
                self.assertEqual([s.select(model, state, self.p, self.cfg) for state in x], raw["choices"])
                self.assertEqual(
                    s.array_digest(model["mean"], model["scale"], *model["parameters"]),
                    record["training"]["parameter_sha256"],
                )
        self.assertEqual(next(r for r in case["records"] if r["kind"] == "exact")["metrics"]["expected_regret"], 0)
        json.dumps(case, allow_nan=False)

    def test_invalid_roster_nonfinite_parameters_and_data_reject(self):
        for kwargs in (
            {"seeds": []},
            {"seeds": [1, 1]},
            {"panel_names": []},
            {"panel_names": ["missing"]},
            {"train_n": 0},
        ):
            with self.assertRaises(ValueError):
                s.run_study(**kwargs)
        with self.assertRaises(ValueError):
            replace(self.p, noise=float("nan"))
        bad = {**self.data, "gradients": np.full_like(self.data["gradients"], float("nan"))}
        with self.assertRaises(ValueError):
            s.fit("linear", "direct_gradient", bad, self.p, 11, self.cfg)


if __name__ == "__main__":
    unittest.main()
