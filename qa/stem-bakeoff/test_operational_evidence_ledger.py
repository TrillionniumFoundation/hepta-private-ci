import copy
import unittest

from operational_evidence_ledger import execution_cost, label_pools


class OperationalLedgerTests(unittest.TestCase):
    def test_two_revision_labels_remain_one_source_group_and_inapplicable_is_not_negative(self):
        rows = [{"source_id": "before", "group_id": "bug", "repo": "repo", "text": "before",
                 "split": "train", "labels": {"outcome": 0}},
                {"source_id": "after", "group_id": "bug", "repo": "repo", "text": "after",
                 "split": "train", "labels": {"outcome": 1}},
                {"source_id": "action", "group_id": "bug", "repo": "repo", "text": "action",
                 "split": "train", "labels": {"diagnostic": 1}}]
        data = {"selected_tasks": ["outcome", "diagnostic"], "rows": rows,
                "task_definitions": {"outcome": {"family_id": "outcome"}, "diagnostic": {"family_id": "diagnostic"}}}
        pool = label_pools(data)
        self.assertEqual(pool["outcome"]["partitions"]["train"], {
            "applicable_labelled_rows": 2, "independent_source_groups": 1, "class_rows": [1, 1],
            "class_source_groups": [1, 1], "groups_with_both_implementation_labels": 1,
            "normalized_predictor_count": 2, "predictor_utf8_bytes": 11, "repositories": ["repo"]})
        self.assertEqual(pool["diagnostic"]["partitions"]["train"]["class_rows"], [0, 1])
        rows[0]["labels"]["outcome"] = False
        with self.assertRaises(ValueError):
            label_pools(data)

    def test_failed_attempt_cost_is_counted_and_inexact_physical_counter_is_rejected(self):
        command = {"wall_ns": 11, "outcome": "infrastructure_error",
                   "compatibility": {"build": {"wall_ns": 7, "returncode": 1}}}
        case = {"physical_command_executions": 2, "harness_error": None,
                "pairs": {"pair": {"base": command, "candidate": {"wall_ns": 13, "outcome": "pass"}}}}
        result = execution_cost([case, copy.deepcopy(case)])
        self.assertEqual({k: result[k] for k in ("physical_test_commands", "summed_observed_test_wall_ns",
            "physical_package_build_commands", "summed_observed_build_wall_ns", "failed_package_build_commands",
            "child_cpu_ns", "child_peak_rss_bytes", "concurrent_elapsed_wall_ns")}, {
            "physical_test_commands": 4, "summed_observed_test_wall_ns": 48,
            "physical_package_build_commands": 2, "summed_observed_build_wall_ns": 14,
            "failed_package_build_commands": 2, "child_cpu_ns": None, "child_peak_rss_bytes": None,
            "concurrent_elapsed_wall_ns": None})
        for counter in (True, 1, 3, 2.0):
            with self.subTest(counter=counter), self.assertRaises(ValueError):
                execution_cost([{**case, "physical_command_executions": counter}])


if __name__ == "__main__":
    unittest.main()
