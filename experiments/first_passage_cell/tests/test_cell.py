"""Independent sampling, joint-gradient, renewal and restoration regressions."""

import copy
import math
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import numpy as np
from scipy.stats import kstest

from ..cell import CellParameters, FirstPassageCell, sample_hitting_time, sample_survivor
from ..kernels import first_passage, killed_cdf
from ..task import MaintenanceTask, scenarios
from ..training import (fit_cell, generate_renewal_data, objective_and_gradient,
                        dataset_digest, save_dataset, load_dataset)


class SamplingTests(unittest.TestCase):
    def test_inverse_gaussian_and_defective_hit_frequency(self):
        rng = np.random.Generator(np.random.Philox(24119))
        n = 12000
        for drift in (-0.6, 0.0, 0.5):
            samples = np.array([sample_hitting_time(0.8, drift, 0.7, rng) for _ in range(n)])
            target = float(first_passage(0.8, drift, 0.7, 1.0)["F"])
            actual = float(np.mean(samples <= 1.0))
            tolerance = 5 * math.sqrt(target * (1 - target) / n) + 1 / n
            self.assertLess(abs(actual - target), tolerance)
            if drift > 0:
                expected = math.exp(-2 * drift * 0.8 / 0.7**2)
                self.assertLess(abs(np.mean(np.isfinite(samples)) - expected), 0.02)

    def test_surviving_endpoint_matches_killed_law(self):
        rng = np.random.Generator(np.random.Philox(92021))
        for distance, drift, sigma, duration in [(0.8, -0.5, 0.7, 1.0),
                                                 (0.05, -0.8, 0.8, 1.0)]:
            target = float(first_passage(distance, drift, sigma, duration)["S"])
            samples = np.array([sample_survivor(distance, drift, sigma, duration, rng)
                                for _ in range(2500)])
            result = kstest(samples, lambda y: killed_cdf(distance, y, drift, sigma, duration) / target)
            self.assertGreater(result.pvalue, 1e-5)
            self.assertGreater(np.min(samples), 0)


    def test_near_zero_drift_has_no_false_zero_time_atom(self):
        for drift in (-1e-100, -1e-200, -1e-300, 0.0, 1e-300):
            value = sample_hitting_time(1.0, drift, 1.0, np.random.default_rng(2))
            self.assertGreater(value, 0.0)
            self.assertTrue(math.isfinite(value))
        with self.assertRaisesRegex(ArithmeticError, "quantile|endpoint"):
            sample_survivor(5e-324, 0.0, 1.0, 1.0, np.random.default_rng(2))


class RenewalTests(unittest.TestCase):
    def setUp(self):
        self.parameters = CellParameters(-0.5, (-0.2, 0.1), 0.3, 0.1, 0.8, 0.1)

    def test_repeated_events_use_reset_refractory_and_remaining_time(self):
        cell = FirstPassageCell(self.parameters, 1.1, 1)
        with patch("experiments.first_passage_cell.cell.sample_hitting_time",
                   side_effect=[0.2, 0.2, math.inf]), patch(
                   "experiments.first_passage_cell.cell.sample_survivor", return_value=0.7):
            receipt = cell.advance(1.0, (0.0, 0.0))
        self.assertEqual(receipt["failure_count"], 2)
        self.assertEqual([round(row["time"], 12) for row in receipt["events"]], [0.2, 0.5])
        self.assertAlmostEqual(receipt["active_duration"], 0.8)
        self.assertEqual(receipt["time"], 1.0)
        self.assertAlmostEqual(receipt["level"], 0.8)

    def test_boundary_atom_and_partial_refractory_survive_checkpoint(self):
        cell = FirstPassageCell(self.parameters, 0.1, 7)
        first = cell.advance(0.03, (0.0, 0.0))
        self.assertEqual(first["failure_count"], 1)
        self.assertEqual(first["events"][0]["time"], 0.0)
        self.assertEqual(first["active_duration"], 0.0)
        self.assertAlmostEqual(first["refractory_remaining"], 0.07)
        restored = FirstPassageCell.from_checkpoint(cell.checkpoint(), self.parameters.digest())
        self.assertEqual(cell.advance(0.9, (0.2, -0.5)), restored.advance(0.9, (0.2, -0.5)))
        self.assertEqual(cell.checkpoint(), restored.checkpoint())

    def test_new_cell_and_disk_checkpoint_replay_exactly(self):
        cell = FirstPassageCell(self.parameters, 0.85, 15)
        cell.advance(0.4, (0.1, 0.7))
        with tempfile.TemporaryDirectory(dir=Path(__file__).parents[1]) as folder:
            path = Path(folder) / "checkpoint.json"
            cell.save_checkpoint(path)
            import json
            restored = FirstPassageCell.from_checkpoint(json.loads(path.read_text()),
                                                        self.parameters.digest())
            for inputs in [(0.7, -0.3), (0.0, 0.0), (-1.0, 0.8)]:
                self.assertEqual(cell.advance(0.5, inputs), restored.advance(0.5, inputs))

    def test_checkpoint_corruption_and_model_mismatch_are_rejected(self):
        cell = FirstPassageCell(self.parameters, 1.0, 3)
        broken = copy.deepcopy(cell.checkpoint())
        broken["payload"]["level"] += 0.1
        with self.assertRaisesRegex(ValueError, "digest"):
            FirstPassageCell.from_checkpoint(broken, self.parameters.digest())
        other = CellParameters(-0.6, (-0.2, 0.1), 0.3, 0.1, 0.8, 0.1)
        with self.assertRaisesRegex(ValueError, "model"):
            FirstPassageCell.from_checkpoint(cell.checkpoint(), other.digest())

    def test_unsupported_event_bound_and_partial_failure_are_atomic(self):
        cell = FirstPassageCell(self.parameters, 1.0, 3)
        old = cell.checkpoint()
        tiny = CellParameters(-0.5, (-0.2, 0.1), 0.3, 0.1, 0.8, 1e-5)
        with self.assertRaisesRegex(ValueError, "128-event"):
            FirstPassageCell(tiny, 1.0, 3).advance(0.5, (0.0, 0.0))
        with patch("experiments.first_passage_cell.cell.sample_hitting_time",
                   side_effect=[0.01, ArithmeticError("induced numerical failure")]):
            with self.assertRaises(ArithmeticError):
                cell.advance(0.5, (0.0, 0.0))
        self.assertEqual(cell.checkpoint(), old)

    def test_invalid_input_leaves_state_unchanged(self):
        cell = FirstPassageCell(self.parameters, 1.0, 3)
        old = cell.checkpoint()
        with self.assertRaises(ValueError):
            cell.advance(0.5, (math.nan, 0.2))
        self.assertEqual(cell.checkpoint(), old)


class JointTrainingTests(unittest.TestCase):
    def test_full_chain_rule_matches_independent_parameter_differences(self):
        data = generate_renewal_data(91, 48, "training")
        vector = np.array([-0.45, -0.1, 0.13, math.log(0.4), 0.04, math.log(1.05), 0.03])
        loss, gradient = objective_and_gradient(vector, data)
        self.assertTrue(math.isfinite(loss))
        differences = []
        for index in range(len(vector)):
            offset = np.zeros(len(vector))
            offset[index] = 1e-6
            differences.append((objective_and_gradient(vector + offset, data)[0]
                                - objective_and_gradient(vector - offset, data)[0]) / 2e-6)
        np.testing.assert_allclose(gradient, differences, rtol=2e-5, atol=2e-6)

    def test_all_physical_parameter_groups_are_jointly_trained(self):
        data = generate_renewal_data(1103, 128, "training")
        selected, receipt = fit_cell(1103, data)
        self.assertTrue(receipt["optimizer_success"])
        self.assertLess(receipt["selected_loss"], receipt["initial_loss"] - 0.1)
        self.assertTrue(all(v > 1e-4 for v in receipt["absolute_parameter_change"].values()))
        self.assertEqual(receipt["active_parameter_count"], 6)
        self.assertEqual(selected.digest(), receipt["model_digest"])

    def test_split_guard_and_dataset_roundtrip(self):
        data = generate_renewal_data(55, 20, "development")
        with self.assertRaisesRegex(ValueError, "training"):
            fit_cell(55, data)
        with tempfile.TemporaryDirectory(dir=Path(__file__).parents[1]) as folder:
            path = Path(folder) / "renewal.npz"
            save_dataset(data, path)
            self.assertEqual(dataset_digest(load_dataset(path)), dataset_digest(data))


class TaskTests(unittest.TestCase):
    def test_action_cost_and_failure_cost_are_each_paid_once(self):
        task = MaintenanceTask(scenarios(1103, 1, "diagnostic")[0])
        with patch("experiments.first_passage_cell.cell.sample_hitting_time",
                   side_effect=[0.01, math.inf]), patch(
                   "experiments.first_passage_cell.cell.sample_survivor", return_value=0.9):
            receipt = task.step("repair")
        self.assertEqual(len(receipt["interventions"]), 1)
        self.assertEqual(receipt["outcome"]["failure_count"], 1)
        self.assertAlmostEqual(receipt["outcome"]["active_duration"], 0.38)
        self.assertEqual(receipt["failure_cost"], 0.5)
        self.assertEqual(receipt["action_cost"], task.cost)
        self.assertAlmostEqual(receipt["reward"], 0.6 * 0.38 - 0.5 - task.cost)

    def test_stop_ends_future_actions_and_costs(self):
        task = MaintenanceTask(scenarios(1103, 1, "diagnostic")[0])
        receipt = task.step("stop")
        self.assertEqual(receipt["reward"], 0.0)
        self.assertEqual(receipt["outcome"]["elapsed_duration"], 0.0)
        with self.assertRaises(ValueError):
            task.step("wait")

    def test_task_checkpoint_requires_external_identity_and_recomputes_scores(self):
        task = MaintenanceTask(scenarios(1151, 1, "diagnostic")[0])
        task.step("wait")
        with self.assertRaisesRegex(ValueError, "model"):
            MaintenanceTask.from_checkpoint(task.checkpoint(), "wrong model")
        altered = copy.deepcopy(task.checkpoint())
        altered["payload"]["ledger"][0]["reward"] += 0.1
        altered["payload"]["ledger"][0]["cumulative_reward"] += 0.1
        altered["payload"]["total_reward"] += 0.1
        import hashlib
        from ..cell import canonical_bytes
        altered["sha256"] = hashlib.sha256(canonical_bytes(altered["payload"])).hexdigest()
        with self.assertRaisesRegex(ValueError, "score"):
            MaintenanceTask.from_checkpoint(altered, task.cell.parameters.digest())

    def test_repair_and_failed_propagation_are_one_transaction(self):
        task = MaintenanceTask(scenarios(1151, 1, "diagnostic")[0])
        old = task.checkpoint()
        with patch("experiments.first_passage_cell.cell.sample_hitting_time",
                   side_effect=ArithmeticError("injected propagation failure")):
            with self.assertRaises(ArithmeticError):
                task.step("repair")
        self.assertEqual(task.checkpoint(), old)

    def test_active_time_forgery_is_rejected_despite_recomputed_score(self):
        task = MaintenanceTask(scenarios(1151, 1, "diagnostic")[0])
        task.step("wait")
        altered = task.checkpoint()
        row = altered["payload"]["ledger"][0]
        row["outcome"]["active_duration"] *= 0.5
        row["running_reward"] = 0.6 * row["outcome"]["active_duration"]
        row["reward"] = row["running_reward"] - row["failure_cost"] - row["action_cost"]
        row["cumulative_reward"] = row["reward"]
        altered["payload"]["total_reward"] = row["reward"]
        import hashlib
        from ..cell import canonical_bytes
        altered["sha256"] = hashlib.sha256(canonical_bytes(altered["payload"])).hexdigest()
        with self.assertRaisesRegex(ValueError, "conservation"):
            MaintenanceTask.from_checkpoint(altered, task.cell.parameters.digest())

    def test_checkpoint_is_an_immutable_snapshot(self):
        task = MaintenanceTask(scenarios(1151, 1, "diagnostic")[0])
        task.step("wait")
        saved = task.checkpoint()
        before = copy.deepcopy(saved)
        task.step("wait")
        self.assertEqual(saved, before)
        self.assertEqual(MaintenanceTask.from_checkpoint(saved, task.cell.parameters.digest()).index, 1)

    def test_task_restore_binds_random_stream_to_scenario_seed(self):
        task = MaintenanceTask(scenarios(1151, 1, "diagnostic")[0])
        task.step("wait")
        altered = task.checkpoint()
        altered["payload"]["cell"]["payload"]["seed"] += 1
        import hashlib
        from ..cell import canonical_bytes
        inner = altered["payload"]["cell"]
        inner["sha256"] = hashlib.sha256(canonical_bytes(inner["payload"])).hexdigest()
        altered["sha256"] = hashlib.sha256(canonical_bytes(altered["payload"])).hexdigest()
        with self.assertRaisesRegex(ValueError, "seed mismatch"):
            MaintenanceTask.from_checkpoint(altered, task.cell.parameters.digest())

    def test_entire_task_continuation_replays(self):
        task = MaintenanceTask(scenarios(1151, 1, "diagnostic")[0])
        task.step("wait")
        restored = MaintenanceTask.from_checkpoint(task.checkpoint(), task.cell.parameters.digest())
        while not task.done:
            self.assertEqual(task.step("wait"), restored.step("wait"))
        self.assertEqual(task.checkpoint(), restored.checkpoint())


if __name__ == "__main__":
    unittest.main()
