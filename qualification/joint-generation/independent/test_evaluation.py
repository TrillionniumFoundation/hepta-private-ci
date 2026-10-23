"""Hand-authored arrays only: service accounting, net definitions and bootstrap."""

import base64
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import numpy as np

from control import Controller
from model import JointModel
from independent.accounting import BudgetExceeded
from independent.evaluation import measure, paired_interval, run_evaluation


class EvaluationTests(unittest.TestCase):
    def setUp(self):
        self.model = JointModel(202, 12, 192, hidden=4, seed=71)
        full = np.zeros((4, 202))
        full[:, :192] = np.random.default_rng(27).uniform(0, 1, (4, 192))
        full[:, 192] = full[:, 196] = full[:, 199] = 1
        self.data = {"full": full, "labels": np.array([0, 1, 2, 3]),
                     "source_ids": ["hand-a", "hand-a", "hand-b", "hand-b"]}
        self.plan = {"rho": 1.5, "compute_price": 0.02, "service_horizon": 100000,
                     "runtime_backend": "python", "inference_cap_full_equivalents": 2,
                     "random_full_probability": 0.5}

    def critic(self):
        return Controller(12, np.zeros(31), np.ones(31), np.zeros(31), 1., np.array([1., 1.]))

    def test_actual_output_and_cpu_net_include_build_without_changing_weights(self):
        before = self.model.digest()
        plan = {**self.plan, "build_cpu_ns": 1000000000, "build_work_units": 2000000}
        result = measure(self.model, None, "full", self.data, plan, 100000, seed=17)
        self.assertEqual(before, self.model.digest())
        self.assertEqual(result["model_forwards"], 4)
        self.assertEqual(result["budget_violations"], 0)
        self.assertTrue(base64.b64decode(result["sampled_output"]["png_base64"]).startswith(b"\x89PNG\r\n\x1a\n"))
        self.assertNotIn("labels", json.dumps(result["sampled_output"]))
        expected_cpu_penalty = .02 * 1000000000 / 100000 / 100000
        np.testing.assert_allclose(np.asarray(result["per_row"]["runtime_cpu_net_utility"])
                                   - np.asarray(result["per_row"]["cpu_net_utility"]), expected_cpu_penalty, atol=1e-15)
        self.assertGreater(result["cost"]["cpu_ns"], 0)
        self.assertGreater(result["cost"]["operator_totals"]["serialized_requests"], 0)

    def test_static_modes_do_not_execute_critic_and_random_does_one_real_view(self):
        critic = self.critic()
        with patch.object(Controller, "decide", side_effect=AssertionError("unused critic")):
            for mode, expected in (("full", 4), ("low", 4), ("ensemble", 8), ("random", 4)):
                result = measure(self.model, critic, mode, self.data, self.plan, 100000)
                self.assertEqual(result["model_forwards"], expected)
                self.assertNotIn("critic_decisions", result["cost"]["operator_totals"])

    def test_low_is_genuinely_cheaper_and_ensemble_uses_both_predictions(self):
        full = measure(self.model, None, "full", self.data, self.plan, 100000)
        low = measure(self.model, None, "low", self.data, self.plan, 100000)
        ensemble = measure(self.model, None, "ensemble", self.data, self.plan, 100000)
        self.assertLess(sum(low["per_row_cost"]["work_units"]), sum(full["per_row_cost"]["work_units"]))
        self.assertEqual(ensemble["maximum_forwards_per_request"], 2)
        self.assertGreater(low["cost"]["prepare"]["consumed_units"], 0)
        self.assertEqual(full["cost"]["prepare"]["consumed_units"], 0)

    def test_continuation_replays_content_with_bounded_forwards(self):
        first = measure(self.model, self.critic(), "continuation", self.data, self.plan, 100000, seed=6)
        second = measure(self.model, self.critic(), "continuation", self.data, self.plan, 100000, seed=6)
        self.assertEqual(first["sampled_output"], second["sampled_output"])
        self.assertEqual(first["maximum_forwards_per_request"], 2)
        self.assertEqual(first["model_forwards"], 8)
        self.assertEqual(first["cost"]["operator_totals"]["critic_decisions"], 4)

    def test_observer_is_outside_service_timers(self):
        observed = []
        from independent import evaluation
        original = evaluation.outcome_table
        def observer(model):
            observed.append(model.params["decoder"].copy())
            return original(model)
        with patch.object(evaluation, "outcome_table", observer):
            result = measure(self.model, None, "full", self.data, self.plan, 100000)
        self.assertEqual(len(observed), 2)
        np.testing.assert_array_equal(observed[0], self.model.params["decoder"])
        np.testing.assert_array_equal(observed[1], np.roll(self.model.params["decoder"], 1, axis=0))
        self.assertTrue(np.isfinite(result["decoder_corruption_score_drop"]))
        self.assertGreater(result["cost"]["observer_cpu_ns"], 0)
        self.assertEqual(len(result["per_row_cost"]["cpu_ns"]), 4)
        with patch.object(evaluation, "outcome_table", side_effect=AssertionError("unfunded scoring")):
            with self.assertRaises(BudgetExceeded):
                measure(self.model, None, "full", self.data,
                        {**self.plan, "inference_cap_full_equivalents": .01}, 100000)

    def test_cost_only_calibration_ignores_labels_and_never_scores(self):
        class InputsOnly(dict):
            def __getitem__(self, key):
                if key != "full":
                    raise AssertionError("calibration accessed ground truth")
                return super().__getitem__(key)

        inputs = InputsOnly(full=self.data["full"])
        with patch("independent.evaluation.outcome_table", side_effect=AssertionError("scoring")) as table:
            with patch("independent.evaluation.decoded_metrics", side_effect=AssertionError("scoring")) as metrics:
                result = measure(self.model, None, "low", inputs, self.plan, 100000,
                                 seed=19, observe=False)
                table.assert_not_called()
                metrics.assert_not_called()
        self.assertEqual(result["means"], {})
        self.assertEqual(result["per_row"], {})
        self.assertIsNone(result["decoder_corruption_score_drop"])
        self.assertEqual(result["cost"]["observer_cpu_ns"], 0)
        self.assertEqual(result["model_forwards"], 4)
        self.assertEqual(len(result["per_row_cost"]["work_units"]), 4)
        self.assertGreater(result["cost"]["cpu_ns"], 0)
        self.assertTrue(base64.b64decode(result["sampled_output"]["png_base64"]).startswith(b"\x89PNG\r\n\x1a\n"))
        scored = measure(self.model, None, "low", self.data, self.plan, 100000, seed=19)
        self.assertEqual(result["sampled_output"], scored["sampled_output"])
        self.assertEqual(result["per_row_cost"]["work_units"], scored["per_row_cost"]["work_units"])

    def test_random_probability_is_frozen_not_selected_on_scoring_labels(self):
        for probability, mode in ((0., "low"), (1., "full")):
            result = measure(self.model, None, "random", self.data,
                             {**self.plan, "random_full_probability": probability}, 100000, seed=27)
            static = measure(self.model, None, mode, self.data, self.plan, 100000, seed=27)
            self.assertEqual(result["sampled_output"], static["sampled_output"])
        with self.assertRaises(ValueError):
            measure(self.model, None, "random", self.data,
                    {**self.plan, "random_full_probability": 1.1}, 100000)

    def test_saved_array_bootstrap_pairs_physical_sources(self):
        left = np.array([[1., 1., 2., 2.], [3., 3., 4., 4.]])
        result = paired_interval(left, left - .25, self.data["source_ids"], seeds=[11, 23], replicates=50)
        self.assertEqual(result["physical_source_groups"], 2)
        np.testing.assert_allclose([result["mean"], *result["ci95"]], .25, atol=1e-15)
        reverse = paired_interval(left - .25, left, self.data["source_ids"], seeds=[11, 23], replicates=50)
        self.assertLess(reverse["ci95"][1], 0)
        with self.assertRaises(ValueError):
            paired_interval(left, left[:, :3], self.data["source_ids"], seeds=[11, 23])

    def test_shared_cpu_cohorts_are_not_treated_as_independent_sources(self):
        left = np.asarray([[0.] * 4 + [2.] * 4] * 2)
        right = np.zeros_like(left)
        physical = paired_interval(left, right, ["source" + str(i) for i in range(8)],
                                   seeds=[11, 23], replicates=400)
        cohort = paired_interval(left, right, ["batch0"] * 4 + ["batch1"] * 4,
                                 seeds=[11, 23], replicates=400,
                                 cluster_kind="fixed_service_batch_cohort")
        self.assertEqual(cohort["clusters"], 2)
        self.assertEqual(cohort["cluster_kind"], "fixed_service_batch_cohort")
        self.assertIsNone(cohort["physical_source_groups"])
        self.assertGreater(np.ptp(cohort["ci95"]), np.ptp(physical["ci95"]))

    def test_global_opening_marker_blocks_before_any_dataset_call(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            marker = root / "global-opened.json"
            marker.write_text("{}\n")
            with patch("independent.evaluation.GLOBAL_MARKER", marker):
                with patch("independent.evaluation.dataset", side_effect=AssertionError("test must remain sealed")) as data:
                    with self.assertRaises(ValueError):
                        run_evaluation(root)
                    data.assert_not_called()

    def test_frozen_preflight_failure_does_not_open_either_marker(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            marker = root / "global-opened.json"
            with patch("independent.evaluation.GLOBAL_MARKER", marker):
                with patch("independent.evaluation._frozen", side_effect=ValueError("changed source")):
                    with patch("independent.evaluation.dataset") as data:
                        with self.assertRaises(ValueError):
                            run_evaluation(root)
                        data.assert_not_called()
            self.assertFalse(marker.exists())
            self.assertFalse((root / "test-opened.json").exists())

    def test_unready_or_cpu_over_budget_selection_rejects_before_all_data(self):
        from independent.evaluation import SYSTEMS
        for ready, over, expected in ((False, False, "readiness"), (True, True, "CPU budget")):
            with self.subTest(ready=ready, over=over), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                marker = root / "global-opened.json"
                selection = {"selection_ready": ready, "cpu_budget_violations": [],
                             "plan": {"cpu_seconds_per_system": 1.0},
                             "system_cost": {name: {"cpu_seconds": 1.1 if over else .1} for name in SYSTEMS}}
                (root / "selection.json").write_text(json.dumps(selection))
                with patch("independent.evaluation.GLOBAL_MARKER", marker):
                    with patch("independent.evaluation.dataset") as data:
                        with self.assertRaisesRegex(ValueError, expected):
                            run_evaluation(root)
                        data.assert_not_called()
                self.assertFalse(marker.exists())
                self.assertFalse((root / "test-opened.json").exists())

    def test_equal_but_wrong_build_caps_reject_before_all_data(self):
        from independent.evaluation import SYSTEMS
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            marker, plan_path = root / "global-opened.json", root / "plan.json"
            plan = {"cpu_seconds_per_system": 1.0, "operator_units_per_system": 100}
            plan_path.write_text(json.dumps(plan))
            selection = {"selection_ready": True, "cpu_budget_violations": [], "plan": plan,
                         "plan_sha256": hashlib.sha256(plan_path.read_bytes()).hexdigest(),
                         "system_cost": {name: {"cpu_seconds": .1} for name in SYSTEMS},
                         "budgets": {name: {"total_cap": 200} for name in SYSTEMS}}
            (root / "selection.json").write_text(json.dumps(selection))
            with patch("independent.evaluation.GLOBAL_MARKER", marker), patch("independent.evaluation.PLAN_PATH", plan_path):
                with patch("independent.evaluation.dataset", side_effect=AssertionError("sealed")) as data:
                    with self.assertRaisesRegex(ValueError, "cap must equal the frozen plan"):
                        run_evaluation(root)
                    data.assert_not_called()
            self.assertFalse(marker.exists())
            self.assertFalse((root / "test-opened.json").exists())

    def test_truncated_actual_source_inventory_rejects_before_all_data(self):
        from independent.evaluation import SYSTEMS
        names = {"model.py", "utility.py", "data.py", "control.py", "independent/inference.py",
                 "independent/accounting.py", "independent/evaluation.py", "independent/data_v2.py",
                 "independent/run.py", "independent/learning.py", "independent/native.py",
                 "independent/native.c", "independent/additional_runtime.py"}
        for omitted in ("independent/run.py", "independent/learning.py", "independent/native.c",
                        "independent/additional_runtime.py"):
            with self.subTest(omitted=omitted), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                source_root = root / "source"
                (source_root / "independent").mkdir(parents=True)
                for name in names:
                    (source_root / name).write_text("# hand-authored inventory fixture\n")
                marker, plan_path = root / "global-opened.json", root / "plan.json"
                plan = {"cpu_seconds_per_system": 1.0, "operator_units_per_system": 100,
                        "runtime_backend": "native"}
                plan_path.write_text(json.dumps(plan))
                selection = {"selection_ready": True, "cpu_budget_violations": [], "plan": plan,
                             "plan_sha256": hashlib.sha256(plan_path.read_bytes()).hexdigest(),
                             "system_cost": {name: {"cpu_seconds": .1} for name in SYSTEMS},
                             "budgets": {name: {"total_cap": 100} for name in SYSTEMS},
                             "sources": {name: hashlib.sha256((source_root / name).read_bytes()).hexdigest()
                                         for name in names if name != omitted}}
                (root / "selection.json").write_text(json.dumps(selection))
                with patch("independent.evaluation.GLOBAL_MARKER", marker), patch("independent.evaluation.ROOT", source_root), patch("independent.evaluation.PLAN_PATH", plan_path):
                    with patch("independent.evaluation.dataset", side_effect=AssertionError("sealed")) as data:
                        with self.assertRaisesRegex(ValueError, "source inventory"):
                            run_evaluation(root)
                        data.assert_not_called()
                self.assertFalse(marker.exists())
                self.assertFalse((root / "test-opened.json").exists())

    def test_common_native_backend_preserves_the_measured_service_law(self):
        from independent.native import compile_native
        with tempfile.TemporaryDirectory() as temporary:
            library = Path(temporary) / "libtest.so"
            compile_native(library)
            plan = {**self.plan, "runtime_backend": "native", "native_library": str(library)}
            for mode in ("full", "low", "ensemble", "continuation", "random"):
                critic = self.critic() if mode == "continuation" else None
                expected = measure(self.model, critic, mode, self.data, self.plan, 100000, seed=91)
                actual = measure(self.model, critic, mode, self.data, plan, 100000, seed=91)
                for key in ("task_utility", "joint_success", "greedy_joint_success", "net_utility"):
                    np.testing.assert_allclose(actual["per_row"][key], expected["per_row"][key], atol=1e-12, rtol=1e-12)
                self.assertEqual(actual["model_forwards"], expected["model_forwards"])
                self.assertEqual(actual["sampled_output"], expected["sampled_output"])

    def test_actual_native_batch_path_shares_cpu_and_retains_batch_latency(self):
        from independent.native import compile_native
        with tempfile.TemporaryDirectory() as temporary:
            library = Path(temporary) / "libbatchtest.so"
            compile_native(library)
            plan = {**self.plan, "runtime_backend": "native", "native_library": str(library),
                    "runtime_batch_size": 2}
            for mode in ("full", "low", "ensemble", "continuation", "random"):
                critic = self.critic() if mode == "continuation" else None
                result = measure(self.model, critic, mode, self.data, plan, 100000, seed=91)
                batches = result["cost"]["batches"]
                self.assertEqual(len(batches), 2)
                self.assertTrue(all(row["native_batch"] and row["rows"] == 2 for row in batches))
                for batch in batches:
                    components = [batch[key] for key in ("native_generation_and_ledger_cpu_ns",
                                  "output_encoding_and_ledger_cpu_ns", "remaining_service_cpu_ns")]
                    self.assertTrue(all(value >= 0 for value in components))
                    self.assertEqual(sum(components), batch["cpu_ns"])
                    self.assertGreater(batch["native_generation_and_ledger_cpu_ns"], 0)
                    self.assertGreater(batch["output_encoding_and_ledger_cpu_ns"], 0)
                self.assertEqual(result["per_row_cost"]["batch_index"], [0, 0, 1, 1])
                self.assertEqual(result["per_row_cost"]["cpu_ns"][0], batches[0]["cpu_ns"] / 2)
                self.assertEqual(result["per_row_cost"]["cpu_ns"][1], batches[0]["cpu_ns"] / 2)
                self.assertEqual(sum(result["per_row_cost"]["work_units"]), result["cost"]["operator_totals"]["consumed_units"])
                self.assertEqual(result["budget_violations"], 0)
            manual64 = {"full": np.tile(self.data["full"], (16, 1)),
                        "labels": np.tile(self.data["labels"], 16)}
            for mode in ("full", "low", "ensemble", "continuation", "random"):
                critic = self.critic() if mode == "continuation" else None
                result = measure(self.model, critic, mode, manual64,
                                 {**plan, "runtime_batch_size": 64}, 100000)
                self.assertEqual(len(result["cost"]["batches"]), 1)
                batch = result["cost"]["batches"][0]
                self.assertEqual(batch["rows"], 64)
                self.assertTrue(batch["native_batch"])
                self.assertEqual(result["per_row_cost"]["cpu_ns"], [batch["cpu_ns"] / 64] * 64)
                self.assertEqual(result["model_forwards"], 128 if mode in ("ensemble", "continuation") else 64)
                self.assertEqual(result["budget_violations"], 0)


if __name__ == "__main__":
    unittest.main()
