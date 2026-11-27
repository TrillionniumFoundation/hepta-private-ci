"""Failures retain their original command, budget and inventory evidence."""

import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from . import milestone, run


class ReceiptTests(unittest.TestCase):
    def test_early_capability_failure_still_checks_final_source(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "result"
            original = {"commit": "0" * 40, "tree": "original-source"}

            def fail_capability(args, root, result):
                result["source_before"] = original
                raise RuntimeError(
                    "Base capability failed before future materialization"
                )

            with patch.object(milestone, "execute", side_effect=fail_capability):
                with patch.object(milestone, "source_identity", return_value=original):
                    status = milestone.main(
                        [
                            "--source-commit",
                            "0" * 40,
                            "--rustc",
                            "unused",
                            "--output",
                            str(output),
                        ]
                    )
            result = json.loads((output / "milestone.json").read_text())
            self.assertEqual(status, 1)
            self.assertEqual(result["source_before"], result["source_after"])
            self.assertIn("Base capability failed", result["error"])
            self.assertEqual(result["production_update"], "no-update")

    def test_timed_out_process_retains_command_receipt(self):
        with tempfile.TemporaryDirectory() as directory:
            prefix = Path(directory) / "timed-out"
            argv = [sys.executable, "-c", "import time; time.sleep(2)"]
            with self.assertRaises(subprocess.TimeoutExpired):
                run._command(argv, prefix, timeout=0.02)
            receipt = json.loads(prefix.with_suffix(".command.json").read_text())
            self.assertEqual(receipt["argv"], argv)
            self.assertEqual(receipt["status"], "timeout")
            self.assertEqual(receipt["error_type"], "TimeoutExpired")
            self.assertIsNone(receipt["exit_code"])
            self.assertGreaterEqual(receipt["wall_seconds"], 0.02)
            self.assertTrue(prefix.with_suffix(".stdout.log").is_file())
            self.assertTrue(prefix.with_suffix(".stderr.log").is_file())

    def test_missing_executable_retains_launch_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            prefix = Path(directory) / "missing"
            with self.assertRaises(FileNotFoundError):
                run._command([Path(directory) / "absent-executable"], prefix)
            receipt = json.loads(prefix.with_suffix(".command.json").read_text())
            self.assertEqual(receipt["status"], "execution_error")
            self.assertEqual(receipt["error_type"], "FileNotFoundError")
            self.assertIsNone(receipt["exit_code"])

    def test_inventory_failure_preserves_original_execution_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "result"

            def fail_with_symlink(args, root, result):
                (root / "original.txt").write_text("retained evidence")
                (root / "symlink.txt").symlink_to(root / "original.txt")
                raise RuntimeError("original execution failure")

            with patch.object(milestone, "execute", side_effect=fail_with_symlink):
                status = milestone.main(
                    [
                        "--source-commit",
                        "0" * 40,
                        "--rustc",
                        "unused",
                        "--output",
                        str(output),
                    ]
                )
            result = json.loads((output / "milestone.json").read_text())
            self.assertEqual(status, 1)
            self.assertEqual(result["error"], "original execution failure")
            self.assertEqual(result["execution_status"], "failed")
            self.assertIn("symlink", result["artifact_inventory_error"])
            self.assertEqual(result["production_update"], "no-update")


if __name__ == "__main__":
    unittest.main()
