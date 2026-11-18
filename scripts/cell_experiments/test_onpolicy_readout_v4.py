"""Real verifier observations with a scripted model, not learning evidence."""

import copy
from pathlib import Path
import tempfile
import unittest

from . import data, onpolicy_readout_v4 as readout, repo_execution
from .protocol_v3 import execution_summary
from .online_v4.onpolicy_rollout import collect_current
from .online_v4.test_onpolicy_flow import CORRECT, ScriptedPredictor, prepared
from .test_repo_execution import answer


class RecoveryReadoutTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        repo_execution.load_catalog("open")
        cls.records = [prepared(1), prepared(2)]
        cls.manifest = {"generation": "scripted_fixture"}
        cls.identity = data.digest(cls.manifest)

    def collect(self, outputs, *, execute=True, maximum=2):
        with tempfile.TemporaryDirectory() as tmp:
            return collect_current(
                self.records,
                self.manifest,
                None,
                Path(tmp) / "collection",
                lambda model, root: ScriptedPredictor(model, [], iter(outputs)),
                execute=execute,
                maximum=maximum,
            )

    def test_executed_failure_and_rejected_action_have_separate_denominators(self):
        wrong = answer('    assert subject({"calls": 0}, "calls") == {"calls": 2}')
        observed = self.collect([wrong, CORRECT, '{"edits":[', CORRECT])
        report = readout.summarize_collection(observed, self.records, self.identity)
        self.assertEqual(report["measured_tasks"], 2)
        self.assertEqual(report["first_attempt_successes"], 0)
        self.assertEqual(report["final_successes"], 2)
        for cohort in ("executed_first_failures", "unexecuted_first_failures"):
            self.assertEqual(
                report[cohort],
                {
                    "recovered": 1,
                    "first_failure_tasks": 1,
                    "rate": 1.0,
                    "tasks_with_retry": 1,
                },
            )
        self.assertEqual(
            report["actual_call_cost"],
            {
                "model_calls": 4,
                "student_verifier_calls": 4,
                "input_tokens": 40,
                "output_tokens": 20,
            },
        )

    def test_shadow_is_unmeasured_and_zero_failure_cohort_has_no_rate(self):
        observed = self.collect([CORRECT, '{"edits":['], execute=False)
        report = readout.summarize_collection(observed, self.records, self.identity)
        self.assertEqual((report["measured_tasks"], report["unmeasured_tasks"]), (0, 2))
        self.assertIsNone(report["final_successes"])
        self.assertIsNone(report["all_first_failures"]["rate"])
        self.assertEqual(report["actual_call_cost"]["student_verifier_calls"], 0)
        measured = self.collect([CORRECT, CORRECT])
        self.assertIsNone(
            readout.summarize_collection(measured, self.records, self.identity)[
                "all_first_failures"
            ]["rate"]
        )

    def test_changed_model_missing_task_and_changed_tokens_are_rejected(self):
        observed = self.collect([CORRECT, CORRECT])
        for kind in ("model", "coverage", "totals", "step", "summary"):
            changed = copy.deepcopy(observed)
            if kind == "model":
                changed["rows"][0]["model_digest"] = "0" * 64
            elif kind == "coverage":
                changed["rows"].pop()
            elif kind == "totals":
                changed["input_tokens"] = False
            elif kind == "step":
                changed["rows"][0]["steps"][0]["output"]["answer"] = "changed"
            else:
                changed["rows"][0]["success"] = False
            with self.subTest(kind=kind), self.assertRaises(ValueError):
                readout.summarize_collection(changed, self.records, self.identity)

    def test_missing_retry_is_not_a_complete_failure(self):
        observed = self.collect(['{"edits":[', '{"edits":['], maximum=1)
        with self.assertRaisesRegex(ValueError, "before its declared attempt cap"):
            readout.summarize_collection(
                observed, self.records, self.identity, maximum=2
            )

    def test_rehashed_outer_step_does_not_admit_another_business_receipt(self):
        observed = self.collect([CORRECT, CORRECT])
        other_input = copy.deepcopy(self.records[0])
        other_input["task"]["input"] += (
            " Use the same counter contract in another task."
        )
        other_receipt = data.verify_answer(other_input, CORRECT)
        self.assertTrue(other_receipt["success"])
        for kind in ("task", "input", "answer", "parameters", "raw_receipt"):
            changed = copy.deepcopy(observed)
            step = changed["rows"][0]["steps"][0]
            if kind == "task":
                step["verification"] = copy.deepcopy(
                    observed["rows"][1]["steps"][0]["verification"]
                )
            elif kind == "input":
                step["verification"] = copy.deepcopy(other_receipt)
            elif kind == "answer":
                step["output"]["answer"] = '{"edits":[]}'
            elif kind == "parameters":
                step["verification"]["parameters_sha256"] = data.digest({"other": True})
            else:
                step["verification"]["result"]["reason"] = "modified_after_execution"
            step["execution_summary"] = execution_summary(step["verification"])
            step["receipt_sha256"] = data.digest(
                {k: v for k, v in step.items() if k != "receipt_sha256"}
            )
            with self.subTest(kind=kind), self.assertRaises(ValueError):
                readout.summarize_collection(changed, self.records, self.identity)

    def test_success_requires_original_calls_and_consistent_control_observations(self):
        observed = self.collect([CORRECT, CORRECT])
        for kind in ("missing_calls", "control_disagrees"):
            changed = copy.deepcopy(observed)
            step = changed["rows"][0]["steps"][0]
            verification = step["verification"]
            observations = verification["result"]["result"]["observations"]
            if kind == "missing_calls":
                observations[0]["calls"] = []
            else:
                observations[1]["passed"] = True
            verification["receipt_sha256"] = data.digest(
                {
                    k: v
                    for k, v in verification.items()
                    if k not in ("receipt_sha256", "success")
                }
            )
            step["execution_summary"] = execution_summary(verification)
            step["receipt_sha256"] = data.digest(
                {k: v for k, v in step.items() if k != "receipt_sha256"}
            )
            with self.subTest(kind=kind), self.assertRaises(ValueError):
                readout.summarize_collection(changed, self.records, self.identity)


if __name__ == "__main__":
    unittest.main()
