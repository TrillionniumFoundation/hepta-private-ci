import json
import sys
import tempfile
import unittest
from pathlib import Path

from operational_cohort_plan import canonical
from prospective_action_dataset import build_dataset, observed_label
from prospective_action_execution import run_case
from prospective_action_inputs import TASK, sha_file
from test_prospective_action_execution import fixture


class ProspectiveDatasetTests(unittest.TestCase):
    def test_normal_negative_reverse_difference_and_unknown_semantics(self):
        def pair(base, candidate):
            return {"base": {"outcome": base}, "candidate": {"outcome": candidate}}
        self.assertEqual(observed_label(pair("pass", "pass")), (0, None))
        self.assertEqual(observed_label(pair("test_failure", "test_failure")), (0, None))
        self.assertEqual(observed_label(pair("pass", "test_failure")), (1, None))
        self.assertEqual(observed_label(pair("test_failure", "pass")), (1, None))
        for unknown in ("infrastructure_error", "uninformative"):
            self.assertIsNone(observed_label(pair("pass", unknown))[0])
        self.assertIsNone(observed_label({"base": {"outcome": "pass"}})[0])

    def test_actual_complete_execution_preserves_all_preobserved_predictors(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            store, _ = fixture(root)
            inputs_path = root / "inputs/inputs.json"
            original = json.loads(inputs_path.read_bytes())
            group, binding = next(iter(original["case_bindings"].items()))
            executions = root / "executions"
            executions.mkdir()
            plan = executions / "execution-plan.json"
            plan.write_bytes(canonical({"inputs_sha256": sha_file(inputs_path)}))
            case_output = executions / (binding["project"] + "-" + str(binding["bug_id"]))
            limits = {"cpu_seconds": 10, "wall_timeout_seconds": 15,
                      "address_space_bytes": 1024 ** 3, "log_file_bytes": 1024 ** 2}
            run_case(binding, store, {"python": sys.executable, "plain_pytest": True},
                     case_output, root / "work", limits, sha_file(plan))
            summary_path = executions / "summary.json"
            summary_path.write_bytes(canonical({"execution_plan_sha256": sha_file(plan),
                "case_results": {group: sha_file(case_output / "result.json")}}))
            audit = build_dataset(inputs_path, executions, root / "dataset")
            data = json.loads((root / "dataset/dataset.json").read_bytes())
            self.assertEqual(audit["proposed_actions"], 3)
            self.assertEqual(audit["physical_commands"], 6)
            self.assertCountEqual([r["labels"][TASK] for r in data["rows"]], [1, 0, None])
            for before, after in zip(original["rows"], data["rows"]):
                self.assertEqual({k: v for k, v in after.items() if k not in ("labels", "outcome_provenance")},
                                 {k: v for k, v in before.items() if k != "labels"})
            self.assertEqual(len(data["proposal_registry"][0]["actions"]), 3)
            self.assertTrue(audit["all_predictor_fields_unchanged"])
            summary_path.write_bytes(canonical({"execution_plan_sha256": sha_file(plan), "case_results": {}}))
            with self.assertRaisesRegex(ValueError, "complete proposal"):
                build_dataset(inputs_path, executions, root / "invalid")


if __name__ == "__main__":
    unittest.main()
