"""Independent numerical and missing-evidence tests for research diagnostics."""

import json
import hashlib
import math
import unittest
from unittest import mock

import numpy as np

try:
    from .plasticity import (
        array_digest,
        continual_plasticity_probe,
        feature_metrics,
        learning_speed,
        maintenance_gate,
        rank_l2_candidate,
        rank_l2_objective,
        representation_drift,
        retention_metrics,
        run_plasticity_pilot,
        stability_metrics,
        update_metrics,
    )
except ImportError:
    from plasticity import (
        array_digest,
        continual_plasticity_probe,
        feature_metrics,
        learning_speed,
        maintenance_gate,
        rank_l2_candidate,
        rank_l2_objective,
        representation_drift,
        retention_metrics,
        run_plasticity_pilot,
        stability_metrics,
        update_metrics,
    )


class RankTests(unittest.TestCase):
    def test_entropy_uses_singular_values(self):
        measured = feature_metrics(np.diag([3.0, 1.0]), probe_id="diagonal")
        expected = math.exp(-0.75 * math.log(0.75) - 0.25 * math.log(0.25))
        self.assertAlmostEqual(measured["effective_rank"], expected, places=13)
        # Squared singular values would give a different statistic.
        wrong = math.exp(-0.9 * math.log(0.9) - 0.1 * math.log(0.1))
        self.assertGreater(abs(expected - wrong), 0.2)

    def test_zero_degeneracy_and_declared_centering(self):
        zero = feature_metrics(np.zeros((5, 3)), probe_id="zero")
        self.assertEqual(
            (
                zero["effective_rank"],
                zero["numerical_rank"],
                zero["dead_unit_fraction"],
            ),
            (0.0, 0, 1.0),
        )
        self.assertEqual(zero["low_utilization_fraction"], 1.0)
        self.assertTrue(zero["degenerate"])
        constant = np.ones((5, 3))
        self.assertAlmostEqual(
            feature_metrics(constant, probe_id="a")["effective_rank"], 1
        )
        self.assertEqual(
            feature_metrics(constant, probe_id="a", centered=True)["effective_rank"], 0
        )

    def test_rotation_scale_and_low_utilization(self):
        rng = np.random.default_rng(91)
        features = rng.normal(size=(30, 4))
        rotation, _ = np.linalg.qr(rng.normal(size=(4, 4)))
        left = feature_metrics(features, probe_id="a")
        right = feature_metrics(3.7 * features @ rotation, probe_id="a")
        self.assertAlmostEqual(
            left["effective_rank"], right["effective_rank"], places=12
        )
        dead = feature_metrics(
            np.column_stack((np.ones(5), np.zeros(5))),
            probe_id="b",
            activation_semantics="relu_nonnegative",
        )
        self.assertEqual(dead["low_utilization_fraction"], 0.5)
        with self.assertRaises(ValueError):
            feature_metrics(
                [[-1, 1]], probe_id="c", activation_semantics="relu_nonnegative"
            )
        with self.assertRaises(ValueError):
            feature_metrics(
                [[0.1, 1]], probe_id="c", activation_semantics="spike_count"
            )

    def test_gradient_matches_finite_difference(self):
        rng = np.random.default_rng(7)
        x, w = rng.normal(size=(11, 4)), rng.normal(size=(4, 3))
        for centered in (False, True):
            info, analytic = rank_l2_objective(
                x, w, rank_weight=0.23, l2_weight=0.07, centered=centered
            )
            finite = np.empty_like(w)
            for index in np.ndindex(w.shape):
                plus, minus = w.copy(), w.copy()
                plus[index] += 1e-6
                minus[index] -= 1e-6
                fplus = rank_l2_objective(
                    x, plus, rank_weight=0.23, l2_weight=0.07, centered=centered
                )[0]["objective"]
                fminus = rank_l2_objective(
                    x, minus, rank_weight=0.23, l2_weight=0.07, centered=centered
                )[0]["objective"]
                finite[index] = (fplus - fminus) / 2e-6
            np.testing.assert_allclose(analytic, finite, rtol=2e-6, atol=3e-9)
            self.assertEqual(info["rank_gradient_status"], "available")

    def test_candidate_improves_objective_without_mutating_selected(self):
        x, selected = np.eye(3), np.diag([3.0, 1.1, 0.5])
        saved = selected.copy()
        candidate = rank_l2_candidate(
            x,
            selected,
            probe_id="analytic",
            rank_weight=0.5,
            l2_weight=0.02,
            learning_rate=0.05,
            maximum_relative_norm=0.01,
        )
        after = rank_l2_objective(
            x, candidate.weights, rank_weight=0.5, l2_weight=0.02
        )[0]
        self.assertLess(
            after["objective"], candidate.receipt["objective_before"]["objective"]
        )
        self.assertGreater(
            after["effective_rank"],
            candidate.receipt["objective_before"]["effective_rank"],
        )
        np.testing.assert_array_equal(selected, saved)
        self.assertFalse(candidate.weights.flags.writeable)
        self.assertFalse(candidate.receipt["runtime_authority"])
        self.assertIsNone(candidate.receipt["production_retention"])
        self.assertTrue(candidate.receipt["update"]["within_bound"])

    def test_rank_boundary_does_not_invent_gradient(self):
        x, w = np.eye(3), np.diag([3.0, 1.0, 0.0])
        info, gradient = rank_l2_objective(x, w, rank_weight=1, l2_weight=0.02)
        self.assertIsNone(gradient)
        self.assertEqual(info["rank_gradient_status"], "unavailable_rank_boundary")
        result = rank_l2_candidate(
            x, w, probe_id="singular", rank_weight=1, l2_weight=0.02, learning_rate=0.1
        )
        self.assertEqual(result.receipt["status"], "no_update")
        np.testing.assert_array_equal(result.weights, w)
        _, l2_gradient = rank_l2_objective(x, w, rank_weight=0, l2_weight=0.02)
        np.testing.assert_allclose(l2_gradient, 0.02 * w)

    def test_trust_projection_binds_total_update(self):
        x, w = np.eye(3), np.diag([3.0, 1.1, 0.5])
        candidate = rank_l2_candidate(
            x,
            w,
            probe_id="trust",
            rank_weight=1,
            l2_weight=0.3,
            learning_rate=100,
            maximum_relative_norm=0.0025,
        )
        self.assertTrue(candidate.receipt["trust_region_projected"])
        self.assertAlmostEqual(candidate.receipt["update"]["relative_l2"], 0.0025)
        self.assertFalse(update_metrics(np.zeros(2), np.ones(2))["within_bound"])

    def test_tiny_parameter_update_is_projected_and_reported_accurately(self):
        selected = np.diag([1e-200, 2e-200])
        unconstrained = update_metrics(selected, 0.9 * selected)
        self.assertAlmostEqual(unconstrained["relative_l2"], 0.1)
        self.assertFalse(unconstrained["within_bound"])
        candidate = rank_l2_candidate(
            np.eye(2),
            selected,
            probe_id="tiny",
            rank_weight=0,
            l2_weight=1,
            learning_rate=0.1,
            maximum_relative_norm=0.0025,
        )
        actual_relative = math.hypot(
            *(candidate.weights - selected).ravel()
        ) / math.hypot(*selected.ravel())
        self.assertAlmostEqual(actual_relative, 0.0025, places=14)
        self.assertAlmostEqual(
            candidate.receipt["update"]["relative_l2"], actual_relative
        )
        self.assertTrue(candidate.receipt["trust_region_projected"])
        self.assertTrue(candidate.receipt["update"]["within_bound"])
        self.assertGreater(candidate.receipt["update"]["absolute_l2"], 0)
        np.testing.assert_array_equal(selected, np.diag([1e-200, 2e-200]))
        json.dumps(candidate.receipt, allow_nan=False)

    def test_norms_handle_large_values_and_reject_unrepresentable_results(self):
        selected = np.diag([1e200, 2e200])
        metrics = update_metrics(selected, 0.9 * selected)
        self.assertAlmostEqual(metrics["relative_l2"], 0.1)
        self.assertFalse(metrics["within_bound"])
        for before, after in (
            ([1e308], [-1e308]),
            ([1e308] * 4, [1e308] * 4),
            ([1e-300], [1e300]),
            ([1e200, 1e-200], [1e200, 2e-200]),
        ):
            with self.subTest(before=before, after=after):
                with self.assertRaises(ValueError):
                    update_metrics(before, after)
        with self.assertRaises(ValueError):
            rank_l2_candidate(
                np.eye(1),
                np.ones((1, 1)),
                probe_id="overflow",
                rank_weight=0,
                l2_weight=2,
                learning_rate=1e308,
            )
        self.assertFalse(
            update_metrics([1.0], [np.nextafter(1.0, 2.0)], maximum_relative_norm=0)[
                "within_bound"
            ]
        )


class MonitoringTests(unittest.TestCase):
    def test_paired_drift_and_degeneracy(self):
        before = np.array([[1.0, 2.0], [3.0, 2.0], [2.0, 6.0]])
        result = representation_drift(
            before, 2 * before, before_probe_id="same", after_probe_id="same"
        )
        self.assertAlmostEqual(result["relative_frobenius"], 1.0)
        self.assertAlmostEqual(result["linear_cka"], 1.0)
        with self.assertRaises(ValueError):
            representation_drift(
                before, before, before_probe_id="old", after_probe_id="new"
            )
        zeros = representation_drift(
            np.zeros((3, 2)),
            np.ones((3, 2)),
            before_probe_id="zero",
            after_probe_id="zero",
        )
        self.assertIsNone(zeros["relative_frobenius"])
        self.assertIsNone(zeros["linear_cka"])

    def test_retention_fails_one_bad_slice_even_with_good_mean(self):
        report = retention_metrics(
            {"a": 0.8, "b": 0.9}, {"a": 0.99, "b": 0.84}, panel_id="retention"
        )
        self.assertLess(report["mean_drop"], 0)
        self.assertFalse(report["passed"])
        missing = retention_metrics({}, {}, panel_id="unmeasured")
        self.assertIsNone(missing["passed"])
        with self.assertRaises(ValueError):
            retention_metrics({"a": 0.8}, {}, panel_id="wrong")

    def test_speed_censoring_and_auc(self):
        report = learning_speed(
            [0, 2, 5], [1, 0.6, 0.3], target_loss=0.5, task_id="task"
        )
        self.assertAlmostEqual(report["loss_auc"], 2 * 0.8 + 3 * 0.45)
        self.assertEqual(report["first_observed_target_step"], 5)
        censored = learning_speed([0, 3], [1, 0.7], target_loss=0.5, task_id="task")
        self.assertTrue(censored["target_censored"])
        self.assertIsNone(censored["first_observed_target_step"])
        with self.assertRaises(ValueError):
            learning_speed([0, 0], [1, 0.1], target_loss=0.5, task_id="task")

    def test_nonfinite_stability_remains_json_safe(self):
        report = stability_metrics(
            [0.0, float("nan"), float("inf"), 10.0], declared_absolute_bound=8
        )
        self.assertFalse(report["passed"])
        self.assertEqual(report["nonfinite_count"], 2)
        self.assertEqual(report["bound_exceedance_count"], 1)
        json.dumps(report, allow_nan=False)


class MaintenanceTests(unittest.TestCase):
    def valid_gate(self, *, retention=None, extra_costs=None, comparison=None):
        costs = {
            "training_seconds": 1,
            "tuning_seconds": 0,
            "evaluation_seconds": 1,
            "peak_memory_bytes": 1000,
        }
        costs.update(extra_costs or {})
        return maintenance_gate(
            "rank_l2",
            measured_costs=costs,
            budget={"total_seconds": 20, "peak_memory_bytes": 2000},
            retention=(
                retention
                if retention is not None
                else retention_metrics({"a": 0.9}, {"a": 0.9}, panel_id="old")
            ),
            fixed_graph_comparison=(
                comparison
                if comparison is not None
                else {"candidate_net_utility": 2, "baseline_net_utility": 1}
            ),
        )

    def test_retention_flag_without_complete_panel_cannot_pass(self):
        self.assertTrue(self.valid_gate()["research_eligible"])
        for evidence in (
            {"status": "observed", "passed": True},
            {
                "status": "observed",
                "passed": True,
                "panel_id": "old",
                "per_slice": {},
                "threshold": 0.02,
                "worst_drop": 0,
                "mean_drop": 0,
                "threshold_units": "absolute_score_difference",
            },
        ):
            with self.subTest(evidence=evidence):
                report = self.valid_gate(retention=evidence)
                self.assertFalse(report["research_eligible"])
                self.assertIn("retention_not_passed", report["reasons"])

    def test_retention_decision_is_recomputed_and_metadata_is_validated(self):
        failed = retention_metrics({"a": 0.9}, {"a": 0.5}, panel_id="old")
        failed["passed"] = True
        self.assertFalse(self.valid_gate(retention=failed)["research_eligible"])
        for key, value in (
            ("panel_id", ""),
            ("threshold", float("nan")),
            ("threshold_units", "relative_percent"),
            ("worst_drop", -0.4),
        ):
            with self.subTest(key=key):
                changed = retention_metrics({"a": 0.9}, {"a": 0.9}, panel_id="old")
                changed[key] = value
                self.assertFalse(
                    self.valid_gate(retention=changed)["research_eligible"]
                )

    def test_failed_attempt_and_retry_time_enter_the_total(self):
        retry = self.valid_gate(extra_costs={"retry_seconds": 1e6})
        self.assertEqual(retry["measured_costs"]["total_seconds"], 1000002)
        self.assertFalse(retry["research_eligible"])
        self.assertIn("budget_exceeded:total_seconds", retry["reasons"])
        both = self.valid_gate(
            extra_costs={"failed_attempt_seconds": 17, "retry_seconds": 13}
        )
        self.assertEqual(both["measured_costs"]["total_seconds"], 32)
        self.assertFalse(both["research_eligible"])
        unknown = self.valid_gate(extra_costs={"retry_seconds": None})
        self.assertIsNone(unknown["measured_costs"]["total_seconds"])
        self.assertIn("missing_cost:retry_seconds", unknown["reasons"])
        with self.assertRaises(ValueError):
            self.valid_gate(extra_costs={"unregistered_phase_seconds": 1e6})

    def test_overflowing_derived_cost_or_net_utility_is_rejected(self):
        with self.assertRaises(ValueError):
            self.valid_gate(
                comparison={
                    "candidate_net_utility": 1e308,
                    "baseline_net_utility": -1e308,
                }
            )
        with self.assertRaises(ValueError):
            self.valid_gate(
                extra_costs={"training_seconds": 1e308, "evaluation_seconds": 1e308}
            )

    def test_migration_relearning_and_energy_cannot_be_free(self):
        retention = retention_metrics({"a": 0.9}, {"a": 0.9}, panel_id="a")
        costs = {
            "training_seconds": 1,
            "tuning_seconds": 2,
            "evaluation_seconds": 3,
            "peak_memory_bytes": 1000,
            "energy_joules": None,
        }
        report = maintenance_gate(
            "split",
            measured_costs=costs,
            budget={
                "total_seconds": 20,
                "peak_memory_bytes": 2000,
                "energy_joules": 10,
            },
            retention=retention,
            fixed_graph_comparison={
                "candidate_net_utility": 2,
                "baseline_net_utility": 1,
            },
        )
        self.assertFalse(report["research_eligible"])
        self.assertIn("missing_cost:migration_seconds", report["reasons"])
        self.assertIn("missing_cost:relearning_seconds", report["reasons"])
        self.assertIn("unmeasured_budget_axis:energy_joules", report["reasons"])
        self.assertIsNone(report["measured_costs"]["total_seconds"])

    def test_total_budget_counts_every_measured_phase(self):
        costs = {
            "training_seconds": 1,
            "tuning_seconds": 2,
            "evaluation_seconds": 3,
            "migration_seconds": 4,
            "relearning_seconds": 5,
            "peak_memory_bytes": 1000,
        }
        retention = retention_metrics({"a": 0.9}, {"a": 0.9}, panel_id="a")
        report = maintenance_gate(
            "regenerate",
            measured_costs=costs,
            budget={"total_seconds": 14, "peak_memory_bytes": 2000},
            retention=retention,
            fixed_graph_comparison={
                "candidate_net_utility": 2,
                "baseline_net_utility": 1,
            },
        )
        self.assertEqual(report["measured_costs"]["total_seconds"], 15)
        self.assertIn("budget_exceeded:total_seconds", report["reasons"])
        self.assertFalse(report["runtime_authority"])

    def test_unknown_baseline_and_retention_withhold_candidate(self):
        report = maintenance_gate(
            "rank_l2",
            measured_costs={
                "training_seconds": 1,
                "tuning_seconds": 0,
                "evaluation_seconds": 1,
                "peak_memory_bytes": 1000,
            },
            budget={"total_seconds": 20, "peak_memory_bytes": 2000},
            retention=retention_metrics({}, {}, panel_id="unknown"),
            fixed_graph_comparison=None,
        )
        self.assertFalse(report["research_eligible"])
        self.assertIn("retention_not_passed", report["reasons"])
        self.assertIn("fixed_graph_scheduler_comparison_unknown", report["reasons"])
        self.assertIsNone(report["energy_joules"])


class ContinualProbeTests(unittest.TestCase):
    def test_data_manifest_binds_inputs_teachers_targets_and_order(self):
        report = run_plasticity_pilot(seeds=(5,), steps_per_task=2)
        left, right = [row["result"] for row in report["raw_rows"]]
        manifest = left["data_manifest"]
        self.assertEqual(manifest, right["data_manifest"])
        digest = hashlib.sha256(
            json.dumps(
                manifest, sort_keys=True, separators=(",", ":"), allow_nan=False
            ).encode()
        ).hexdigest()
        self.assertEqual(left["data_digest"], digest)
        self.assertEqual(right["data_digest"], digest)
        # Independently reconstruct the seeded supervised split, including labels.
        rng = np.random.default_rng(5)
        train, probe = rng.normal(size=(32, 3)), rng.normal(size=(40, 3))
        teachers = [np.eye(3) + 0.25 * rng.normal(size=(3, 3)) for _ in range(3)]
        self.assertEqual(
            manifest["input_splits"]["train"]["sha256"], array_digest(train)
        )
        self.assertEqual(
            manifest["input_splits"]["held_out_probe"]["sha256"], array_digest(probe)
        )
        self.assertEqual(
            manifest["task_order"], [task["task_id"] for task in manifest["tasks"]]
        )
        self.assertEqual(len(manifest["tasks"]), 3)
        for task, teacher in zip(manifest["tasks"], teachers):
            self.assertEqual(task["teacher"]["sha256"], array_digest(teacher))
            self.assertEqual(
                task["target_splits"]["train"]["sha256"], array_digest(train @ teacher)
            )
            self.assertEqual(
                task["target_splits"]["held_out_probe"]["sha256"],
                array_digest(probe @ teacher),
            )

    def test_attempt_callbacks_wrap_each_raw_row(self):
        events = []
        report = run_plasticity_pilot(
            seeds=(3,),
            steps_per_task=2,
            on_attempt=lambda event, row: events.append((event, row.copy())),
        )
        self.assertEqual(
            [event for event, _ in events],
            ["started", "finished", "started", "finished"],
        )
        for index, row in enumerate(report["raw_rows"]):
            started, finished = events[2 * index][1], events[2 * index + 1][1]
            self.assertEqual(started["attempt_id"], row["attempt_id"])
            self.assertEqual(started["status"], "running")
            self.assertEqual(started["planned_steps"], 6)
            self.assertEqual(started["actual_steps"], 0)
            self.assertEqual(finished, row)

    def test_callback_failures_are_not_recorded_as_training_failures(self):
        import importlib

        module = importlib.import_module(run_plasticity_pilot.__module__)
        for fail_at in ("started", "finished"):
            with self.subTest(fail_at=fail_at):

                def callback(event, row):
                    if event == fail_at:
                        raise OSError("persistence unavailable")

                with mock.patch.object(
                    module,
                    "_continual_plasticity_probe",
                    wraps=module._continual_plasticity_probe,
                ) as train:
                    with self.assertRaisesRegex(OSError, "persistence unavailable"):
                        run_plasticity_pilot(
                            seeds=(3,), steps_per_task=2, on_attempt=callback
                        )
                    self.assertEqual(train.call_count, 0 if fail_at == "started" else 1)

    def test_finite_probe_reproducibility_matching_and_unknown_production(self):
        first = continual_plasticity_probe(seed=5, steps_per_task=4)
        second = continual_plasticity_probe(seed=5, steps_per_task=4)
        variants = first["variants"]
        self.assertEqual(len(variants), 2)
        self.assertEqual(first["data_digest"], second["data_digest"])
        plain = variants["fixed_graph_scheduler_l2"]
        regularized = variants["fixed_graph_scheduler_l2_er"]
        for key in first["matched_budget_axes"]:
            self.assertEqual(plain["costs"][key], regularized["costs"][key])
        self.assertEqual(plain["costs"]["er_gradient_evaluations"], 0)
        self.assertGreater(regularized["costs"]["er_gradient_evaluations"], 0)
        self.assertNotEqual(plain["candidate_digest"], regularized["candidate_digest"])
        for name, report in variants.items():
            self.assertEqual(
                report["candidate_digest"], second["variants"][name]["candidate_digest"]
            )
            self.assertEqual(
                report["training_losses"], second["variants"][name]["training_losses"]
            )
            self.assertTrue(report["all_step_bounds_pass"])
            self.assertTrue(report["stability"]["passed"])
            self.assertIsNone(report["production_retention"])
            self.assertIsNone(report["costs"]["energy_joules"])
            self.assertIsNone(report["costs"]["migration_seconds"])
            self.assertIsNone(report["costs"]["peak_memory_bytes"])
            self.assertFalse(report["runtime_authority"])
        json.dumps(first, allow_nan=False)

    def test_pilot_preserves_failed_method_denominator_and_actual_steps(self):
        import importlib

        module = importlib.import_module(run_plasticity_pilot.__module__)
        original = module._continual_plasticity_probe

        def one_failure(seed, steps, methods, progress):
            if seed == 7 and methods == ("fixed_graph_scheduler_l2_er",):
                progress["actual_steps"] = 2
                raise FloatingPointError("injected failure after two updates")
            return original(seed, steps, methods, progress)

        with mock.patch.object(
            module, "_continual_plasticity_probe", side_effect=one_failure
        ):
            report = run_plasticity_pilot(seeds=(3, 7), steps_per_task=3)
        self.assertEqual(len(report["raw_rows"]), 4)
        self.assertEqual(report["summary"]["planned_attempts"], 4)
        self.assertEqual(report["summary"]["counts"]["failed"], 1)
        self.assertEqual(report["summary"]["counts"]["completed"], 3)
        self.assertFalse(report["summary"]["complete"])
        failed = [row for row in report["raw_rows"] if row["status"] == "failed"][0]
        self.assertEqual(failed["actual_steps"], 2)
        self.assertEqual(failed["planned_steps"], 9)
        self.assertIsNone(failed["result"])
        self.assertIn("injected failure", failed["reason"])
        for row in report["raw_rows"]:
            self.assertIsNone(row["cost"]["energy_joules"])
        json.dumps(report, allow_nan=False)

    def test_budget_is_required_and_candidate_bytes_remain_read_only(self):
        report = maintenance_gate(
            "rank_l2",
            measured_costs={
                "training_seconds": 1,
                "tuning_seconds": 0,
                "evaluation_seconds": 1,
                "peak_memory_bytes": 1000,
            },
            budget={},
            retention=retention_metrics({"a": 0.9}, {"a": 0.9}, panel_id="a"),
            fixed_graph_comparison={
                "candidate_net_utility": 2,
                "baseline_net_utility": 1,
            },
        )
        self.assertFalse(report["research_eligible"])
        self.assertIn("missing_budget:total_seconds", report["reasons"])
        self.assertIn("missing_budget:peak_memory_bytes", report["reasons"])
        candidate = rank_l2_candidate(
            np.eye(2),
            np.diag([2.0, 1.0]),
            probe_id="immutable",
            rank_weight=1,
            l2_weight=0.1,
            learning_rate=0.1,
        )
        with self.assertRaises(ValueError):
            candidate.weights.setflags(write=True)


if __name__ == "__main__":
    unittest.main()
