"""Causality, feedback, information masks and parameter accounting tests."""

from dataclasses import replace
import unittest

import numpy as np

from experiments.continuous_boundary_flow.math_model import (
    build_model,
    readout,
    solve_dp,
)
from experiments.continuous_boundary_flow.models import (
    ARMS,
    BOUNDARY_FEATURE_NAMES,
    FEATURE_NAMES,
    ActorAdapter,
    boundary_features,
    fit_boundary,
)


class GridOnly(dict):
    """Fail immediately if a fixed/direct adapter accesses DP information."""

    def __getitem__(self, key):
        if key != "x":
            raise AssertionError(f"Forbidden DP execution dependency: {key}")
        return super().__getitem__(key)


class AdapterContract(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.model = build_model(n_grid=64)
        cls.dp = solve_dp(cls.model)
        cls.fit = fit_boundary([(cls.model, cls.dp)])
        cls.candidate = {
            "decay": 0.6,
            "gain_c": 0.4,
            "gain_p": 0.7,
            "fixed_boundary": 0.65,
        }

    def actor(self, arm, candidate=None, dp=None, seed=55):
        return ActorAdapter(
            self.model.spec,
            self.dp if dp is None else dp,
            arm,
            self.candidate if candidate is None else candidate,
            seed,
            boundary_weights=self.fit,
        )

    def test_fixed_and_direct_execution_never_read_dp_values(self):
        grid_only = GridOnly(x=self.model.x.copy())
        for arm in ["fixed_margin", "learned_margin"]:
            actor = self.actor(arm, dp=grid_only)
            output = actor.step([3, 8, 16], 9, [0, 1, 0], [0.2, 0.5, 0.1])
            self.assertEqual(output["raw"].shape, (3, 17))
            self.assertFalse(actor.metadata()["uses_dp_boundary"])
            self.assertFalse(actor.metadata()["uses_dp_continuation"])

    def test_boundary_panel_differs_only_by_boundary_source(self):
        remaining = 7
        boundary = self.dp["boundaries"][remaining - 1]["boundary"]
        weights = np.zeros(len(BOUNDARY_FEATURE_NAMES))
        weights[0] = boundary
        candidate = {**self.candidate, "fixed_boundary": boundary}
        actors = [
            ActorAdapter(self.model.spec, self.dp, arm, candidate, 4, weights)
            for arm in ["fixed_margin", "learned_margin", "value_margin"]
        ]
        for _ in range(3):
            results = [
                actor.step([2, 9, 20], remaining, [0, 1, 0], [0.2, 0.6, 0.1])
                for actor in actors
            ]
            for result in results[1:]:
                for key in ["raw", "margin", "risk", "flow", "boundary"]:
                    np.testing.assert_allclose(result[key], results[0][key], atol=1e-13)

    def test_channels_are_explicitly_masked_and_flow_is_past_only(self):
        previous = np.array([0.17, 0.17])
        for arm in ["fixed_margin", "learned_margin", "value_margin", "value_call"]:
            output = self.actor(arm).step([0, 40], 9, [0, 0], previous)
            np.testing.assert_array_equal(output["risk"], [0, 0])
            np.testing.assert_array_equal(output["P"], [0, 0])
            np.testing.assert_array_equal(output["raw"][:, 13:15], np.zeros((2, 2)))
            np.testing.assert_allclose(output["flow"], previous / self.model.spec.dt)
            if arm != "value_call":
                np.testing.assert_array_equal(output["C"], [0, 0])
                np.testing.assert_array_equal(output["raw"][:, 12], [0, 0])

    def test_C_P_match_production_continuation_and_discounted_loss(self):
        remaining = 7
        indices = np.array([1, 7, 20])
        source = readout(self.model, self.dp["value"][remaining - 1])
        result = self.actor("value_dual").step(indices, remaining, 0, 0)
        scale = 1 + remaining * self.model.spec.dt * self.model.spec.production_rate
        np.testing.assert_allclose(
            result["C"], source["C"][indices] / scale, atol=1e-14
        )
        np.testing.assert_allclose(
            result["P"], source["P"][indices] / scale, atol=1e-14
        )
        np.testing.assert_allclose(result["risk"], source["F"][indices], atol=1e-14)
        self.assertFalse(
            np.allclose(
                source["P"],
                self.dp["q_reset"][remaining - 1] - self.dp["q_keep"][remaining - 1],
            )
        )

    def test_C_P_feedback_changes_actual_typed_margin_and_drive(self):
        index = int(np.argmin(abs(self.model.x - 0.4)))
        neutral = self.actor("value_dual", {**self.candidate, "gain_c": 0, "gain_p": 0})
        restoring = self.actor(
            "value_dual", {**self.candidate, "gain_c": 1.2, "gain_p": 0}
        )
        regenerative = self.actor(
            "value_dual", {**self.candidate, "gain_c": 0, "gain_p": 2}
        )
        first = [a.step([index], 10, 0, 0) for a in [neutral, restoring, regenerative]]
        np.testing.assert_allclose(first[0]["margin"], first[1]["margin"])
        self.assertFalse(np.allclose(first[0]["raw"][:, 16], first[1]["raw"][:, 16]))
        second = [
            a.step([index], 10, 0, 0.1) for a in [neutral, restoring, regenerative]
        ]
        self.assertGreater(second[1]["margin"][0], second[0]["margin"][0])
        self.assertLess(second[2]["margin"][0], second[0]["margin"][0])

    def test_actual_and_expected_events_have_distinct_causal_traces(self):
        flow_a, flow_b = self.actor("value_dual"), self.actor("value_dual")
        event_a, event_b = self.actor("event_reset"), self.actor("event_reset")
        for actor in [flow_a, flow_b, event_a, event_b]:
            actor.step([4, 12], 10, 0, 0)
        a = flow_a.step([4, 12], 9, [0, 0], [0.2, 0.2])
        b = flow_b.step([4, 12], 9, [1, 1], [0.2, 0.2])
        np.testing.assert_array_equal(a["raw"], b["raw"])
        ea = event_a.step([4, 12], 9, [0, 0], [0.2, 0.2])
        eb = event_b.step([4, 12], 9, [1, 1], [0.2, 0.2])
        self.assertFalse(np.allclose(ea["raw"], eb["raw"]))
        np.testing.assert_array_equal(ea["flow"], eb["flow"])
        self.assertTrue(np.all(eb["raw"][:, 15] > ea["raw"][:, 15]))

    def test_stopped_rows_are_zero_and_recycled_rows_reset_cleanly(self):
        actor = self.actor("value_dual")
        actor.step([4, 12], 10, 0, 0)
        result = actor.step([-1, 12], 9, [1, 0], [0.9, 0.1])
        np.testing.assert_array_equal(result["raw"][0], np.zeros(17))
        np.testing.assert_array_equal(actor.state[0], np.zeros(6))
        self.assertEqual(result["margin"][0], 0)
        actor.reset(mask=[True, False])
        fresh = self.actor("value_dual")
        recycled = actor.step([4, 12], 8, 0, 0)
        expected = fresh.step([4, 12], 8, 0, 0)
        np.testing.assert_array_equal(recycled["raw"][0], expected["raw"][0])
        self.assertFalse(np.allclose(recycled["raw"][1], expected["raw"][1]))

    def test_native_sparse_has_no_additional_temporal_state(self):
        actor = self.actor("native_sparse")
        a = actor.step([4, 12], 9, [0, 0], [0.2, 0.2])
        b = actor.step([4, 12], 9, [0, 0], [0.2, 0.2])
        np.testing.assert_array_equal(a["raw"], b["raw"])
        np.testing.assert_array_equal(a["margin"], b["margin"])
        self.assertEqual(actor.metadata()["adapter_state_dims"], 0)

    def test_generic_controls_receive_same_derived_information(self):
        reference = self.actor("value_dual").step([4, 12], 9, 0, [0.2, 0.3])
        for arm in ["generic_gate", "dense_recurrent"]:
            actor = self.actor(arm)
            out = actor.step([4, 12], 9, 0, [0.2, 0.3])
            for key in ["C", "P", "risk", "boundary", "flow"]:
                np.testing.assert_array_equal(reference[key], out[key])
            self.assertFalse(np.allclose(reference["raw"][:, 11:], out["raw"][:, 11:]))
            self.assertEqual(actor.metadata()["external_head_parameter_count"], 42)
            self.assertIn(actor.metadata()["mixing_coefficient_count"], [42, 78])

    def test_seeded_mixing_is_replayable_and_bounded(self):
        for arm in ARMS:
            one, two = self.actor(arm), self.actor(arm)
            for remaining in [10, 9, 8]:
                a = one.step([0, 7, 63], remaining, [1, 0, 0], [0.9, 0.2, 0.01])
                b = two.step([0, 7, 63], remaining, [1, 0, 0], [0.9, 0.2, 0.01])
                np.testing.assert_array_equal(a["raw"], b["raw"])
                self.assertTrue(np.isfinite(a["raw"]).all())
                self.assertLessEqual(abs(a["raw"]).max(), 4)
                self.assertEqual(a["raw"].shape[-1], len(FEATURE_NAMES))

    def test_direct_boundary_training_reports_extra_parameters(self):
        varied = [
            build_model(replace(self.model.spec, maintenance_cost=cost), n_grid=64)
            for cost in [0.2, 0.38, 0.6]
        ]
        fitted = fit_boundary(varied)
        self.assertEqual(fitted["training_tasks"], 3)
        self.assertEqual(fitted["training_rows"], 3 * self.model.spec.horizon)
        self.assertEqual(fitted["weights"].shape, (20,))
        targets = np.concatenate(
            [
                [row["boundary"] for row in solve_dp(model)["boundaries"]]
                for model in varied
            ]
        )
        constant_baseline_rmse = float(np.std(targets))
        self.assertLess(fitted["training_rmse"], constant_baseline_rmse)
        features = boundary_features(self.model.spec, [1, 5, 10])
        self.assertEqual(features.shape, (3, 20))
        actor = self.actor("learned_margin")
        self.assertEqual(actor.metadata()["boundary_parameter_count"], 20)
        self.assertEqual(actor.metadata()["trainable_adapter_parameters"], 0)

    def test_batch_change_requires_explicit_reset(self):
        actor = self.actor("value_dual")
        actor.step([4, 12], 10, 0, 0)
        with self.assertRaises(ValueError):
            actor.step([4], 9, 0, 0)
        actor.reset(batch_size=1)
        self.assertEqual(actor.step([4], 9, 0, 0)["raw"].shape, (1, 17))


if __name__ == "__main__":
    unittest.main()
