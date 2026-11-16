"""Integration checks for actual repository-contract execution and weak tests."""

import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from . import data, repo_execution as execution, repo_tasks


def answer(assertions):
    return json.dumps(
        {"edits": [{"path": "test_contract.py", "old": "    pass", "new": assertions}]}
    )


class RepoExecutionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        execution.load_catalog()
        cls.fixture = execution._CATALOG["A-counter"]
        cls.binding = {
            "fixture_id": "A-counter",
            "fixture_sha256": data.digest(cls.fixture),
        }

    def test_actual_assertions_distinguish_original_from_wrong_outputs(self):
        result = execution.verify_patch(
            self.binding,
            answer(
                '    assert subject({"calls": 0}, "calls") == {"calls": 1}\n'
                '    assert subject({"calls": 7}, "calls") == {"calls": 8}'
            ),
        )
        self.assertTrue(result["success"])
        self.assertEqual(
            {
                "executed": result["executed"],
                "exit_code": result["exit_code"],
                "passed": [row["passed"] for row in result["result"]["observations"]],
                "kills": result["controls_rejected"],
                "assertions": result["assertions"],
            },
            {
                "executed": True,
                "exit_code": 0,
                "passed": [True, False, False],
                "kills": 2,
                "assertions": 2,
            },
        )

    def test_syntax_valid_but_wrong_business_expectation_fails(self):
        result = execution.verify_patch(
            self.binding,
            answer('    assert subject({"calls": 0}, "calls") == {"calls": 9}'),
        )
        self.assertTrue(result["executed"])
        self.assertFalse(result["success"])
        self.assertFalse(result["result"]["original_passed"])

    def test_weak_assertion_does_not_earn_semantic_success(self):
        result = execution.verify_patch(
            self.binding,
            answer('    assert subject({"calls": 0}, "calls") is not None'),
        )
        self.assertEqual(
            (
                result["success"],
                result["result"]["original_passed"],
                result["controls_rejected"],
            ),
            (False, True, 0),
        )

    def test_only_assertion_subject_calls_reach_child(self):
        for code in (
            '    assert print("x") is None',
            '    import math\n    assert subject({"calls": 0}, "calls")',
            '    assert subject.__name__ == "counter"',
        ):
            with (
                self.subTest(code=code),
                patch.object(execution.subprocess, "run") as run,
            ):
                result = execution.verify_patch(self.binding, answer(code))
                self.assertFalse(result["success"])
                self.assertFalse(result["executed"])
                run.assert_not_called()

    def test_source_binding_checked_before_execution(self):
        with patch.object(execution.subprocess, "run") as run:
            with self.assertRaisesRegex(ValueError, "changed"):
                execution.verify_patch(
                    {**self.binding, "fixture_sha256": "0" * 64},
                    answer('    assert subject({"calls": 0}, "calls")'),
                )
            run.assert_not_called()

    def test_confirmation_requires_retained_selection_digest(self):
        with patch.object(execution, "_CONFIRMATION", None):
            with self.assertRaisesRegex(ValueError, "selection"):
                execution.load_catalog("confirmation")
            with tempfile.TemporaryDirectory() as tmp:
                path = Path(tmp) / "selection.json"
                path.write_text('{"status":"frozen"}\n')
                with self.assertRaisesRegex(ValueError, "changed"):
                    execution.unlock_confirmation(path, "0" * 64)
            self.assertIsNone(execution._CONFIRMATION)

    def test_built_trace_contains_actual_incomplete_then_complete_test_results(self):
        from .chat_protocol import native_examples, training_messages

        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "open"
            repo_tasks.build("open", output)
            records = data.load_records(output / "records.jsonl")
            record = next(row for row in records if row["record_id"] == "A-counter")
            phases = [event["kind"] for event in record["trajectory"]]
            self.assertEqual(phases, ["action", "observation", "action", "observation"])
            before, after = [
                json.loads(event["content"])
                for event in record["trajectory"]
                if event["kind"] == "observation"
            ]
            self.assertTrue(before["original_passed"])
            self.assertFalse(before["success"])
            self.assertLess(before["controls_rejected"], before["control_count"])
            self.assertTrue(after["success"])
            self.assertEqual(after["controls_rejected"], after["control_count"])
            for feedback in (before, after):
                self.assertTrue(feedback["executed"])
                self.assertTrue(feedback["next_attempt_resets_template"])
                self.assertFalse(
                    set(feedback) & {"reference_answer", "output", "expected", "patch"}
                )
            final, _ = training_messages(native_examples([record], "final_answer")[0])
            trajectory, duplicates = training_messages(
                native_examples([record], "trajectory")[0]
            )
            self.assertEqual(final[:2], trajectory[:2])
            self.assertEqual(
                [message["role"] for message in trajectory[:2]], ["user", "tool"]
            )
            self.assertEqual(duplicates, 1)
            self.assertEqual(
                sum(message["role"] == "assistant" for message in trajectory), 2
            )


if __name__ == "__main__":
    unittest.main()
