"""Whole-project attachment keeps authentic per-case origins and all attempts."""

import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from prospective_action_inputs import TASK, sha_file
from prospective_outcome_selection import freeze_selection
from reconcile_prospective_outcomes import reconcile, write_json
from test_prospective_outcome_selection import condition, fixture, write


def completed(root):
    args, original, projected, old_plan = fixture(root)
    freeze_selection(**args)
    path = root/"selection/plan.json"
    selection_sha = sha_file(path)
    config_path = root/"selection/execution-runtime-config.json"
    new_plan = copy.deepcopy(old_plan)
    new_plan.update(inputs_sha256=args["projected_inputs_sha256"], runtime_config=json.loads(config_path.read_bytes()),
        runtime_config_sha256=sha_file(config_path), frozen_file_pins={str(path): selection_sha}, source_roles=projected["project_roles"])
    new_sha, summary_sha = condition(root/"replacement", projected, new_plan,
        {"bugsinpy/luigi/1": 0, "bugsinpy/luigi/2": None})
    return args, {"selection_plan": path, "selection_plan_sha256": selection_sha,
        "replacement_plan_sha256": new_sha, "replacement_summary_sha256": summary_sha, "output": root/"final"}


class ReconciledOutcomeTests(unittest.TestCase):
    def test_all_luigi_replaced_including_unknown_and_every_original_attempt_retained(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            original, args = completed(root)
            diagnostic = root/"diagnostic.json"
            pin = write(diagnostic, {"claimed_label": 1, "kind": "ignored diagnostic content", "wall_ns": 999})
            audit = reconcile(**args, diagnostic_receipts=[{"path": str(diagnostic), "sha256": pin}])
            data = json.loads((root/"final/dataset.json").read_bytes())
            by_group = {r["group_id"]: r for r in data["rows"]}
            self.assertEqual([by_group[g]["labels"][TASK] for g in ("bugsinpy/luigi/1", "bugsinpy/luigi/2", "bugsinpy/scrapy/1")], [0, None, 1])
            self.assertEqual(data["input_dataset_sha256"], original["inputs_sha256"])
            self.assertNotIn("execution_plan_sha256", data)
            for group, row in by_group.items():
                expected = args["replacement_plan_sha256"] if "/luigi/" in group else original["original_plan_sha256"]
                self.assertEqual(row["outcome_provenance"]["execution_plan_sha256"], expected)
            self.assertEqual(audit["selected_execution_counts"]["physical_command_executions"], 6)
            self.assertEqual(audit["both_complete_condition_counts"]["physical_command_executions"], 10)
            self.assertEqual(len(data["source_condition_bindings"]["original"]["complete_original_summary"]["case_results"]), 3)
            self.assertFalse(data["additional_all_attempt_diagnostic_receipts"][0]["supplies_labels"])
            self.assertEqual((audit["proposed_groups"], audit["proposed_actions"], audit["source_available_rows"]), (3, 3, 3))

    def test_resealed_case_from_wrong_execution_plan_or_partial_project_is_rejected(self):
        for attack in ("wrong_case_plan", "missing_group"):
            with self.subTest(attack=attack), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                old, args = completed(root)
                summary_path = root/"replacement/summary.json"
                summary = json.loads(summary_path.read_bytes())
                if attack == "wrong_case_plan":
                    path = root/"replacement/luigi-1/result.json"
                    result = json.loads(path.read_bytes())
                    result["execution_plan_sha256"] = old["original_plan_sha256"]
                    summary["case_results"]["bugsinpy/luigi/1"] = write(path, result)
                else:
                    summary["case_results"].pop("bugsinpy/luigi/2")
                    summary.update(completed_groups=1, proposed_groups=1)
                args["replacement_summary_sha256"] = write(summary_path, summary)
                with self.assertRaises(ValueError): reconcile(**args)
                self.assertFalse((root/"final/manifest.json").exists())

    def test_late_superseded_case_tamper_or_extra_log_prevents_final_seal(self):
        for attack in ("changed", "extra"):
            with self.subTest(attack=attack), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                _, args = completed(root)
                def mutate(path, value):
                    write_json(path, value)
                    if Path(path).name == "dataset.json":
                        (root/"original/luigi-1"/("stdout.log" if attack == "changed" else "extra.log")).write_bytes(b"late mutation")
                with patch("reconcile_prospective_outcomes.write_json", side_effect=mutate), self.assertRaises(ValueError):
                    reconcile(**args)
                self.assertFalse((root/"final/manifest.json").exists())


if __name__ == "__main__":
    unittest.main()
