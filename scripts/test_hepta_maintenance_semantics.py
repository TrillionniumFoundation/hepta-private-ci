"""Behavioral checks for actual semantic outcomes and source/split admission."""

import copy
from pathlib import Path
import tempfile
import time
import unittest

from hepta_cells.maintenance_semantics import contract, evaluate, split_binding
from hepta_cells.maintenance_tasks import Compiler, cold_task, fixtures, repair
from verify_hepta_semantic_cycle import review_rows, review_served


class SemanticMaintenanceTests(unittest.TestCase):
    def setUp(self):
        self.task = fixtures(semantic=True)["A"][0]

    def test_compile_pass_with_wrong_result_is_failure(self):
        source = "def fixture_A_0(x):\n    return x - 3\n"
        result = evaluate(self.task, source)
        self.assertEqual(result["status"], "failed")
        self.assertFalse(result["success"])
        self.assertEqual([r["observed"] for r in result["child"]["checks"]], [-10, -3, 8])

    def test_real_correct_function_and_literal_cases(self):
        for task in (self.task, fixtures(semantic=True)["B"][2], cold_task()):
            action = 2 if task["id"] == "fixture_B_2" else 0
            result = evaluate(task, repair(task["source"], action))
            self.assertEqual(result["status"], "passed")
            self.assertTrue(result["success"])
            self.assertEqual(result["checks_sha256"], contract(task)["checks_sha256"])

    def test_runtime_exception_is_observed(self):
        result = evaluate(self.task, "def fixture_A_0(x):\n    return x / 0\n")
        self.assertEqual(result["status"], "error")
        self.assertIn("ZeroDivisionError", result["child"]["error"])
        self.assertFalse(result["success"])

    def test_timeout_terminates_owned_child(self):
        result = evaluate(self.task, "def fixture_A_0(x):\n    while True:\n        pass\n", timeout_seconds=0.15)
        self.assertEqual(result["status"], "timeout")
        self.assertIsInstance(result["returncode"], int)
        self.assertFalse(result["success"])

    def test_syntax_failure_does_not_launch_semantic_execution(self):
        with tempfile.TemporaryDirectory() as directory:
            compiler = Compiler(Path(directory), time.perf_counter(), semantic=True)
            result = compiler.check(self.task, self.task["source"], "A", "observation")
            self.assertFalse(result["compile_success"])
            self.assertEqual(result["semantic"]["status"], "not_run_compile_error")
            self.assertEqual(compiler.semantic_calls, 0)

    def test_compiler_records_success_only_after_semantic_pass(self):
        with tempfile.TemporaryDirectory() as directory:
            compiler = Compiler(Path(directory), time.perf_counter(), semantic=True)
            bad = compiler.check(self.task, "def fixture_A_0(x):\n    return 0\n", "B", "candidate")
            good = compiler.check(self.task, repair(self.task["source"], 0), "B", "candidate")
            self.assertTrue(bad["compile_success"])
            self.assertFalse(bad["success"])
            self.assertTrue(good["success"])
            self.assertEqual(compiler.semantic_calls, 2)

    def test_phase_source_identity_and_contract_are_bound(self):
        panels = fixtures(semantic=True)
        split_binding({**panels, "D-cold": [cold_task()]})
        duplicate = copy.deepcopy(panels)
        duplicate["B"][0]["source"] = duplicate["A"][0]["source"]
        with self.assertRaisesRegex(ValueError, "overlaps"):
            split_binding(duplicate)
        wrong = copy.deepcopy(panels)
        wrong["B"][0]["provenance"]["split"] = "A"
        with self.assertRaisesRegex(ValueError, "overlaps"):
            split_binding(wrong)
        changed = copy.deepcopy(self.task)
        changed["checks"][0]["expected"] += 1
        self.assertNotEqual(contract(changed)["checks_sha256"], contract(self.task)["checks_sha256"])

    def test_independent_review_rejects_promoted_compile_and_changed_checks(self):
        panels = fixtures(semantic=True)
        plan = dict(panels=panels, cold_task=cold_task(),
                    task_contracts=split_binding({**panels, "D-cold": [cold_task()]}))
        with tempfile.TemporaryDirectory() as directory:
            compiler = Compiler(Path(directory), time.perf_counter(), semantic=True)
            row = compiler.check(self.task, repair(self.task["source"], 0), "A", "acquisition")
        review_rows(plan, [row])
        altered = copy.deepcopy(row)
        altered["semantic"]["checks_sha256"] = "0" * 64
        with self.assertRaisesRegex(ValueError, "another source or checks"):
            review_rows(plan, [altered])
        altered = copy.deepcopy(row)
        altered["compile_success"] = False
        with self.assertRaisesRegex(ValueError, "compile failure"):
            review_rows(plan, [altered])
        altered = copy.deepcopy(row)
        altered["semantic"]["child_source_compile_attempted"] = False
        with self.assertRaisesRegex(ValueError, "child original"):
            review_rows(plan, [altered])

    def test_review_binds_action_and_repair_to_original_native_logits(self):
        logits = [3.0, 1.0, -1.0, 0.0]
        receipts = [dict(request_id=self.task["id"] + f"-event-{index}", output=dict(cell=dict(cursor=index + 1)))
                    for index in range(3)]
        receipts.append(dict(request_id=self.task["id"] + "-predict-0", output=dict(cell=dict(logits=logits))))
        row = dict(action=0, chosen_logits=logits, predict_action=[0.0], receipts=receipts,
                   outcome=dict(source=repair(self.task["source"], 0)))
        review_served(row, "memory", self.task)
        changed = copy.deepcopy(row)
        changed["action"] = 3
        with self.assertRaisesRegex(ValueError, "served action"):
            review_served(changed, "memory", self.task)
        changed = copy.deepcopy(row)
        changed["outcome"]["source"] = repair(self.task["source"], 3)
        with self.assertRaisesRegex(ValueError, "executed repair source"):
            review_served(changed, "memory", self.task)


if __name__ == "__main__":
    unittest.main()
