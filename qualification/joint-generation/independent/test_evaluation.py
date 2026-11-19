"""Hand-authored arrays only: service accounting, net definitions and bootstrap."""

import base64
import copy
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

    def affine_fixture(self):
        from independent.accounting import WorkLedger
        from independent.gain_head import AffineGainHead, KIND
        _, hidden, _, _ = self.model._forward(self.data["full"])
        config = {"gain_head": KIND, "ridge_regularization": .001}
        head, fitted = AffineGainHead.fit(hidden, self.data["full"][:, 192:], np.full(4, .1),
                                         config, 11, WorkLedger("handmade-affine-fit"))
        selection = self.decision_fixture()
        selection["plan"].update(hidden=4)
        selection["plan"]["controller"].update(config)
        selection["datasets"] = {"train": {"rows": 4}}
        row = selection["selected"][0]
        row.update(critic_kind=KIND, gain_head_kind=KIND)
        row["controller_calibration"].update(critic_kind=KIND, gain_head_fit=fitted,
            raw_target={"rows": 4, "values_sha256": fitted["target"]["sha256"]})
        return head, selection

    def test_affine_artifact_dispatch_binds_fit_and_actual_parameters(self):
        from independent.evaluation import _controller, _controller_decision_binding, _gain_head_binding
        from independent.gain_head import AffineGainHead
        head, selection = self.affine_fixture()
        row = selection["selected"][0]
        _controller_decision_binding(row, selection)
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "head.npz"
            np.savez_compressed(path, **head.to_arrays())
            loaded = _controller(path)
            _gain_head_binding(loaded, row["controller_calibration"], hidden_dim=4, seed=11,
                               config=selection["plan"]["controller"], training_rows=4)
            self.assertIsInstance(loaded, AffineGainHead)
            changed = AffineGainHead(4, loaded.mean, loaded.scale, loaded.weights + .01,
                                     loaded.intercept, loaded.bounds)
            with self.assertRaisesRegex(ValueError, "fitted parameters"):
                _gain_head_binding(changed, row["controller_calibration"], hidden_dim=4, seed=11)
            arrays = dict(head.to_arrays()); arrays["gh_hidden_dim"] = np.array([5], dtype=np.int64)
            np.savez_compressed(path, **arrays)
            with self.assertRaises(ValueError):
                _controller(path)

    def test_affine_fit_spec_tampering_rejects_before_any_dataset(self):
        for field in ("row_kind", "receipt_kind", "ridge", "work", "hidden", "seed"):
            with self.subTest(field=field), tempfile.TemporaryDirectory() as temporary:
                _, selection = self.affine_fixture()
                row = selection["selected"][0]
                receipt = row["controller_calibration"]
                if field == "row_kind": row["gain_head_kind"] = "probability-ridge-v1"
                elif field == "receipt_kind": receipt["critic_kind"] = "probability-ridge-v1"
                elif field == "ridge": receipt["gain_head_fit"]["ridge_regularization"] = .01
                elif field == "work": receipt["gain_head_fit"]["work"]["macs"] += 1
                elif field == "hidden": receipt["gain_head_fit"]["hidden_dim"] = 5
                else: receipt["gain_head_fit"]["seed"] = 23
                root = Path(temporary)
                plan_path, marker = root / "plan.json", root / "opened.json"
                plan_path.write_text(json.dumps(selection["plan"]))
                selection["plan_sha256"] = hashlib.sha256(plan_path.read_bytes()).hexdigest()
                (root / "selection.json").write_text(json.dumps(selection))
                with patch("independent.evaluation.PLAN_PATH", plan_path), patch("independent.evaluation.GLOBAL_MARKER", marker):
                    with patch("independent.evaluation.dataset", side_effect=AssertionError("sealed")) as data:
                        with self.assertRaisesRegex(ValueError, "gain-head|critic kind"):
                            run_evaluation(root)
                        data.assert_not_called()
                self.assertFalse(marker.exists())
                self.assertFalse((root / "test-opened.json").exists())

    def test_affine_native_measure_matches_python_routes_and_head_specific_work(self):
        from independent.native import compile_native
        head, _ = self.affine_fixture()
        before = self.model.digest()
        with tempfile.TemporaryDirectory() as temporary:
            library = Path(temporary) / "affine.so"
            compile_native(library)
            for price, forwards in ((.02, 8), (.2, 4)):
                plan = {**self.plan, "decision_price": price}
                python = measure(self.model, head, "continuation", self.data, plan, 100000, seed=11)
                native = measure(self.model, head, "continuation", self.data,
                    {**plan, "runtime_backend": "native", "native_library": str(library), "runtime_batch_size": 4},
                    100000, seed=11)
                self.assertEqual((native["model_forwards"], python["model_forwards"]), (forwards, forwards))
                self.assertEqual(native["sampled_output"], python["sampled_output"])
                self.assertEqual(native["per_row_cost"]["work_units"], python["per_row_cost"]["work_units"])
                self.assertEqual(native["cost"]["operator_totals"]["critic_decisions"], 4)
                self.assertEqual(native["cost"]["compute_price"], .02)
                self.assertEqual(native["budget_violations"], 0)
        self.assertEqual(before, self.model.digest())

    def decision_fixture(self, deltas=(-1000., 2000., 3000.), *, seed=11):
        from independent.evaluation import SYSTEMS
        target = "raw-decoded-task-utility"
        ratio = max(0., float(np.median(deltas))) / 100000
        seed_index = [11, 23, 47].index(seed)
        pairs = [{"repeat": index, "order": ["stop", "continue"] if (index + seed_index) % 2 == 0 else ["continue", "stop"],
                  "sample_seed": seed + 1009 * index, "stop": {"rows": 72, "cpu_ns": 7200000},
                  "continue": {"rows": 72, "cpu_ns": 7200000 + 72 * delta}}
                 for index, delta in enumerate(deltas)]
        calibration = {"schema": "hepta.joint-generation.controller-cost-calibration.v1",
                       "gain_objective": target, "model_digest": "a" * 64, "seed": seed,
                       "calibration_inputs_sha256": "b" * 64,
                       "paired_cpu_deltas_ns_per_request": list(deltas), "pairs": pairs,
                       "median_incremental_cpu_ns_per_request": float(np.median(deltas)),
                       "nonnegative_incremental_cpu_ns_per_request": max(0., float(np.median(deltas))),
                       "reference_full_cpu_ns": 100000, "cost_ratio": ratio,
                       "compute_price": .02, "decision_price": .02 * ratio}
        row = {"system": "ndu_control", "seed": seed, "model_digest": "a" * 64,
               "reference_full_cpu_ns": 100000, "gain_objective": target,
               "cost_ratio": ratio, "decision_price": .02 * ratio,
               "controller_calibration": calibration}
        return {"plan": {"controller": {"gain_target": target}, "compute_price": .02,
                         "calibration_rows": 72, "calibration_repeats": 3, "model_seeds": [11, 23, 47],
                         "cpu_seconds_per_system": 1.0, "operator_units_per_system": 1000},
                "common": {"calibration_identity": {"inputs_sha256": "b" * 64}},
                "selection_ready": True, "cpu_budget_violations": [], "selected": [row],
                "system_cost": {name: {"cpu_seconds": .1} for name in SYSTEMS},
                "budgets": {name: {"total_cap": 1000} for name in SYSTEMS}}

    def test_controller_cost_binding_recomputes_paired_median_and_zero_clamp(self):
        from independent.evaluation import _controller_decision_binding
        for deltas, decision in (((-1000., 2000., 3000.), .0004), ((-4000., -3000., -2000.), 0.)):
            selection = self.decision_fixture(deltas)
            row = selection["selected"][0]
            _controller_decision_binding(row, selection)
            self.assertEqual(row["decision_price"], decision)

    def test_controller_cost_binding_accepts_counterbalanced_seed23(self):
        from independent.evaluation import _controller_decision_binding
        selection = self.decision_fixture(seed=23)
        row = selection["selected"][0]
        self.assertEqual([pair["order"] for pair in row["controller_calibration"]["pairs"]],
                         [["continue", "stop"], ["stop", "continue"], ["continue", "stop"]])
        _controller_decision_binding(row, selection)

    def test_tampered_controller_cost_binding_rejects_before_all_data(self):
        changes = [("decision_price", .02), ("gain_objective", "entropic"), ("seed", 23),
                   ("model_digest", "c" * 64), ("calibration_inputs_sha256", "c" * 64),
                   ("cost_ratio", .5), ("reference_full_cpu_ns", 200000),
                   ("median_incremental_cpu_ns_per_request", 2001.),
                   ("paired_cpu_deltas_ns_per_request", [1000., 2000., 3000.])]
        for name, value in changes:
            with self.subTest(field=name), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                selection = copy.deepcopy(self.decision_fixture())
                row = selection["selected"][0]
                target = row if name in ("decision_price", "gain_objective") else row["controller_calibration"]
                target[name] = value
                marker, plan_path = root / "global-opened.json", root / "plan.json"
                plan_path.write_text(json.dumps(selection["plan"]))
                selection["plan_sha256"] = hashlib.sha256(plan_path.read_bytes()).hexdigest()
                (root / "selection.json").write_text(json.dumps(selection))
                with patch("independent.evaluation.GLOBAL_MARKER", marker), patch("independent.evaluation.PLAN_PATH", plan_path):
                    with patch("independent.evaluation.dataset", side_effect=AssertionError("sealed")) as data:
                        with self.assertRaises(ValueError):
                            run_evaluation(root)
                        data.assert_not_called()
                self.assertFalse(marker.exists())
                self.assertFalse((root / "test-opened.json").exists())

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

    def test_decision_price_changes_routes_without_changing_net_price(self):
        from independent.native import compile_native
        critic = Controller(12, np.zeros(31), np.ones(31), np.zeros(31), .01, np.array([.01, .01]))
        with tempfile.TemporaryDirectory() as temporary:
            library = Path(temporary) / "libprice.so"
            compile_native(library)
            for backend in ("python", "native"):
                plan = {**self.plan, "runtime_backend": backend, "runtime_batch_size": 4,
                        "native_library": str(library)}
                for decision_price, forwards in ((.001, 8), (.02, 4)):
                    result = measure(self.model, critic, "continuation", self.data,
                                     {**plan, "decision_price": decision_price}, 100000)
                    self.assertEqual(result["model_forwards"], forwards)
                    self.assertEqual(result["cost"]["decision_price"], decision_price)
                    self.assertEqual(result["cost"]["compute_price"], .02)
                    self.assertEqual(result["cost"]["operator_totals"]["critic_decisions"], 4)
                    self.assertEqual(sum(result["per_row_cost"]["work_units"]),
                                     result["cost"]["operator_totals"]["consumed_units"])
                    task = np.asarray(result["per_row"]["task_utility"])
                    expected_cpu_penalty = .02 * (np.asarray(result["per_row_cost"]["cpu_ns"])
                        + result["cost"]["prepare_cpu_ns"] / plan["service_horizon"]) / 100000
                    np.testing.assert_allclose(task - np.asarray(result["per_row"]["runtime_cpu_net_utility"]),
                                               expected_cpu_penalty, atol=1e-15)
                    expected_work_penalty = .02 * (np.asarray(result["per_row_cost"]["work_units"])
                        + result["cost"]["prepare"]["consumed_units"] / plan["service_horizon"]) / result["cost"]["reference_full_work_units"]
                    np.testing.assert_allclose(task - np.asarray(result["per_row"]["runtime_net_utility"]),
                                               expected_work_penalty, atol=1e-15)
        for invalid in (-1, float("nan"), float("inf"), True):
            with self.subTest(invalid=invalid), self.assertRaisesRegex(ValueError, "decision price"):
                measure(self.model, critic, "continuation", self.data,
                        {**self.plan, "decision_price": invalid}, 100000)

    def test_observer_is_outside_service_timers(self):
        import data
        observed = []
        from independent import evaluation
        original = evaluation.prepare_decoded_observer
        def observer(model):
            observed.append(model.params["decoder"].copy())
            return original(model)
        with patch.object(evaluation, "prepare_decoded_observer", observer), \
             patch.object(data, "decoded_observations", wraps=data.decoded_observations) as observations:
            result = measure(self.model, None, "full", self.data, self.plan, 100000)
        self.assertEqual(observations.call_count, 2)
        self.assertEqual(len(observed), 2)
        np.testing.assert_array_equal(observed[0], self.model.params["decoder"])
        np.testing.assert_array_equal(observed[1], np.roll(self.model.params["decoder"], 1, axis=0))
        self.assertTrue(np.isfinite(result["decoder_corruption_score_drop"]))
        self.assertGreater(result["cost"]["observer_cpu_ns"], 0)
        self.assertEqual(len(result["per_row_cost"]["cpu_ns"]), 4)
        with patch.object(evaluation, "prepare_decoded_observer", side_effect=AssertionError("unfunded scoring")):
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
        with patch("independent.evaluation.prepare_decoded_observer", side_effect=AssertionError("scoring")) as table:
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

    def test_formal_measurement_order_rotates_systems_and_keeps_each_bundle_once(self):
        from independent.evaluation import SYSTEMS, _measurement_order
        seeds = [11, 23, 47]
        bundles = [({"system": system, "seed": seed}, object(), object())
                   for system in reversed(SYSTEMS) for seed in reversed(seeds)]
        original = bundles.copy()
        expected_rounds = [(11, ["supervised", "anchor", "additive", "ndu", "ndu_control"]),
                           (23, ["anchor", "additive", "ndu", "ndu_control", "supervised"]),
                           (47, ["additive", "ndu", "ndu_control", "supervised", "anchor"])]
        ordered = _measurement_order(bundles, seeds)
        self.assertEqual([(row["system"], row["seed"]) for row, _, _ in ordered],
                         [(system, seed) for seed, systems in expected_rounds for system in systems])
        self.assertEqual(len(ordered), 15)
        self.assertEqual({id(bundle) for bundle in ordered}, {id(bundle) for bundle in bundles})
        self.assertEqual(bundles, original)

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
