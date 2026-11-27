"""Behavioral controls for orthogonal credit factors and failure accounting."""

import copy
import json
import unittest
from unittest import mock

import numpy as np

from . import credit, credit_axes as axes


class CreditAxesTests(unittest.TestCase):
    def specs(self, **conditions):
        return [
            s
            for s in axes.credit_axes_specs((11,), updates=2)
            if all(s[k] == v for k, v in conditions.items())
        ]

    def test_pairing_preserves_examples_labels_and_initialization(self):
        specs = self.specs(horizon=4, timing="terminal", coverage="sparse")
        rows = [axes.run_credit_axes_attempt(spec) for spec in specs]
        self.assertTrue(all(r["status"] == "completed" for r in rows))
        self.assertEqual(len({r["comparison_id"] for r in rows}), 1)
        self.assertEqual(len({r["data_digest"] for r in rows}), 1)
        self.assertEqual(len({r["initial_model_digest"] for r in rows}), 1)
        self.assertEqual(len({r["supervision_digest"] for r in rows}), 1)
        for row in rows:
            self.assertEqual(row["counts"]["training_observations"], 8)
            self.assertEqual(row["counts"]["optimizer_updates"], 2)
            self.assertEqual(len(row["evaluation_rows"]), 12)
            self.assertEqual(
                row["step_receipts"][0]["selected_digest"], row["initial_model_digest"]
            )
            self.assertEqual(
                row["step_receipts"][1]["selected_digest"],
                row["step_receipts"][0]["candidate_digest"],
            )
            self.assertEqual(
                row["step_receipts"][-1]["candidate_digest"], row["final_model_digest"]
            )
            train = {r["task_id"] for r in row["data_manifest"]["train"]}
            self.assertTrue(
                train.isdisjoint(
                    r["task_id"] for r in row["data_manifest"]["evaluation"]
                )
            )
        json.dumps(rows, allow_nan=False)

    def test_spatial_and_temporal_factors_do_not_change_raw_data(self):
        rows = [
            axes.run_credit_axes_attempt(s)
            for s in self.specs(horizon=4, method="type_specific")
        ]
        self.assertEqual(len({r["data_digest"] for r in rows}), 1)
        self.assertEqual(len({r["supervision_digest"] for r in rows}), 2)
        for row in rows:
            self.assertEqual(
                row["counts"]["supervised_events"], 8 if row["timing"] == "dense" else 2
            )
            self.assertEqual(
                sum(row["feedback_mask"]), 7 if row["coverage"] == "all" else 3
            )

    def test_shared_scalar_is_unit_broadcast_without_signed_cancellation(self):
        model = credit.make_model(11)
        method, rule = axes.credit_axes_rule(model, "shared_scalar", "all")
        np.testing.assert_array_equal(rule.group_map, np.ones((7, 1)))
        self.assertEqual(method, "three_factor")
        self.assertEqual(float(rule.group_map.mean()), 1)
        self.assertLess(abs(float(credit.make_rule(model).group_map.mean())), 1 / 7)
        episode = credit.copy_episode(np.random.default_rng(4), 4)
        result = credit.gradient(model, *episode[:3], method, rule, episode[3])
        self.assertGreater(np.linalg.norm(credit.flatten(result["gradients"])), 0)

    def test_route_shuffle_changes_mapping_not_transport_or_execution(self):
        model = credit.make_model(11)
        _, correct = axes.credit_axes_rule(model, "type_specific", "all")
        kernel, shuffled = axes.credit_axes_rule(model, "shuffled_routing", "all")
        np.testing.assert_array_equal(correct.credit_graph, shuffled.credit_graph)
        np.testing.assert_array_equal(
            shuffled.group_map, correct.group_map[list(axes.ROUTING_PERMUTATION)]
        )
        np.testing.assert_array_equal(
            np.abs(correct.group_map), np.abs(shuffled.group_map)
        )
        episode = credit.copy_episode(np.random.default_rng(4), 4)
        a = credit.gradient(model, *episode[:3], "type_specific", correct, episode[3])
        b = credit.gradient(model, *episode[:3], kernel, shuffled, episode[3])
        c = credit.gradient(
            model, *episode[:3], "shuffled_diffusion", correct, episode[3]
        )
        np.testing.assert_array_equal(a["outputs"], b["outputs"])
        self.assertEqual(a["credit_transport_digest"], b["credit_transport_digest"])
        self.assertNotEqual(a["credit_transport_digest"], c["credit_transport_digest"])
        self.assertGreater(
            np.linalg.norm(
                credit.flatten(a["gradients"]) - credit.flatten(b["gradients"])
            ),
            0,
        )

    def test_zero_feedback_is_no_update_and_inputs_remain_immutable(self):
        spec = self.specs(
            horizon=16, timing="dense", coverage="all", method="zero_feedback"
        )[0]
        before = copy.deepcopy(spec)
        row = axes.run_credit_axes_attempt(spec)
        self.assertEqual(spec, before)
        self.assertEqual(row["status"], "completed")
        self.assertEqual(row["initial_model_digest"], row["final_model_digest"])
        self.assertEqual(row["counts"]["changed_updates"], 0)
        self.assertTrue(all(x["no_update"] for x in row["step_receipts"]))
        self.assertEqual(row["mean_evaluation_loss_change"], 0)
        model = credit.make_model(11)
        episode = credit.copy_episode(np.random.default_rng(3), 4)
        original = [a.copy() for a in episode]
        digest = model.digest
        method, rule = axes.credit_axes_rule(model, "shared_scalar", "sparse")
        credit.gradient(model, *episode[:3], method, rule, episode[3])
        self.assertEqual(digest, model.digest)
        for actual, expected in zip(episode, original):
            np.testing.assert_array_equal(actual, expected)

    def test_failure_preserves_consumed_observations_and_unchanged_parent(self):
        spec = self.specs(
            horizon=4, timing="terminal", coverage="all", method="shared_scalar"
        )[0]
        with mock.patch.object(
            axes.credit, "propose", side_effect=ArithmeticError("injected")
        ):
            row = axes.run_credit_axes_attempt(spec)
        self.assertEqual(row["status"], "failed")
        self.assertEqual(row["counts"]["gradient_calls_completed"], 1)
        self.assertEqual(row["counts"]["training_observations"], 4)
        self.assertEqual(row["counts"]["optimizer_updates"], 0)
        self.assertEqual(row["initial_model_digest"], row["final_model_digest"])
        self.assertEqual(len(row["training_rows"]), 1)

    def test_invalid_or_altered_specs_are_refused_before_training(self):
        for seeds in ((1, 1), (True,), (), (2**32,)):
            with self.assertRaises(ValueError):
                axes.credit_axes_specs(seeds)
        spec = self.specs()[0]
        spec["budget"]["optimizer_updates"] = 999
        with mock.patch.object(axes.credit, "gradient") as grad:
            with self.assertRaises(ValueError):
                axes.run_credit_axes_attempt(spec)
            grad.assert_not_called()

    def test_incomplete_gradient_and_interrupts_keep_honest_coverage(self):
        spec = self.specs()[0]
        with mock.patch.object(
            axes.credit, "gradient", side_effect=RuntimeError("injected")
        ):
            row = axes.run_credit_axes_attempt(spec)
        self.assertEqual(row["counts"]["gradient_calls_started"], 1)
        self.assertEqual(row["counts"]["training_observations"], 0)
        self.assertEqual(
            row["counts"]["observation_coverage"],
            "lower_bound_incomplete_gradient_call",
        )
        with mock.patch.object(axes.credit, "gradient", side_effect=KeyboardInterrupt):
            with self.assertRaises(KeyboardInterrupt):
                axes.run_credit_axes_attempt(spec)


if __name__ == "__main__":
    unittest.main()
