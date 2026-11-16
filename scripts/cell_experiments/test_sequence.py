"""Behavioral integrity checks; these tests make no model learning claim."""

import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from .sequence import Execution


class ExecutionTests(unittest.TestCase):
    def test_changed_input_is_rejected_before_a_child_can_run(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            dataset = root / "data.jsonl"
            dataset.write_text("original\n")
            execution = Execution(
                root / "run", dataset, root / "materials", root / "logs"
            )
            dataset.write_text("changed\n")
            with patch("cell_experiments.sequence.subprocess.run") as spawn:
                with self.assertRaisesRegex(ValueError, "changed"):
                    execution.stage("first", "prepare")
                spawn.assert_not_called()
            self.assertFalse((root / "logs/first").exists())

    def test_failed_stage_keeps_exit_status_and_both_raw_logs(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            dataset = root / "data.jsonl"
            dataset.write_text("input\n")
            execution = Execution(
                root / "run", dataset, root / "materials", root / "logs"
            )

            def failure(*args, **kwargs):
                kwargs["stdout"].write(b"partial measured output\n")
                kwargs["stderr"].write(b"actual failure\n")
                return type("Completed", (), {"returncode": 7})()

            with patch(
                "cell_experiments.sequence.subprocess.run", side_effect=failure
            ) as spawn:
                with self.assertRaisesRegex(RuntimeError, "original evidence retained"):
                    execution.stage("failed", "train", "trajectory")
                self.assertEqual(spawn.call_count, 1)
            receipt = json.loads((root / "logs/failed/RESULT.json").read_text())
            self.assertEqual((receipt["exit_code"], receipt["status"]), (7, "FAILED"))
            self.assertEqual(
                (root / "logs/failed/stderr.txt").read_text(), "actual failure\n"
            )


if __name__ == "__main__":
    unittest.main()
