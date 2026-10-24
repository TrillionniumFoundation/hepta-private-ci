import tempfile
import unittest
from pathlib import Path

from run_calibrated_cells import run_study
from summarize_calibrated_resources import label_counts, summarize_resources
import test_run_calibrated_cells as driver_fixtures


class ResourceLedgerTests(unittest.TestCase):
    def test_repeated_targets_and_groups_are_counted_separately(self):
        rows = {"a": {"group_id": "same"}, "b": {"group_id": "same"}}
        report = label_counts([("one", "a"), ("one", "a"), ("two", "a"), ("two", "b")], rows)
        self.assertEqual(report, {"unique_source_rows": 2, "unique_source_groups": 1, "source_target_label_entries": 3})

    def test_gradient_budget_is_not_total_label_access(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            dataset, features = driver_fixtures.CalibratedDriverTests().fixture(root)
            study = root/"study"
            run_study(dataset, features, study, phase="all", holdout_use="fixture",
                protocol=dict(budgets=[8], seeds=[7], checkpoints=[2,4], l2_grid=[.1]))
            result = summarize_resources(dataset, study, root/"costs.json")
            case = result["per_task_seed_budget"][0]
            self.assertEqual(case["gradient_selected"]["unique_source_rows"], 8)
            self.assertEqual(case["available_training_pool"]["unique_source_rows"], 16)
            self.assertEqual(case["selected_gradient_plus_tuning_calibration"]["unique_source_rows"], 24)
            self.assertEqual(case["heldout_scoring_only"]["unique_source_rows"], 16)
            self.assertEqual(result["label_stages"]["heldout_scoring_only"]["unique_source_rows"], 32)
            self.assertGreater(result["head_cost"]["actual_optimizer_updates_all_paths"], 0)
            self.assertGreater(result["head_cost"]["fresh_process_child_cpu_ns"], 0)
            self.assertFalse(result["head_cost"]["equal_parameter_cap_or_steps_imply_equal_cost"])


if __name__ == "__main__":
    unittest.main()
