"""Controller costs include failures and never count wait4 CPU twice."""

import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from warm_trial import execute


class ControllerTests(unittest.TestCase):
    def test_self_cpu_is_separate_from_child_and_result_write_is_inside_interval(self):
        with tempfile.TemporaryDirectory() as temporary:
            args = SimpleNamespace(output=Path(temporary) / "new")

            def body(_):
                result = {
                    "error": None,
                    "charged_process_cost": {
                        "dimensions": {"cpu_ns": {"total": 12345}}
                    },
                }
                (args.output / "result.json").write_text(json.dumps(result))
                return result

            with patch("warm_trial.execute_body", body):
                execute(args)
            measured = json.loads((args.output / "controller-cost.json").read_bytes())
            self.assertEqual(
                measured["controller_plus_child_cpu_ns"],
                measured["self_cpu_ns"] + 12345,
            )
            self.assertTrue(measured["self_cpu_excludes_child_cpu"])
            self.assertGreaterEqual(measured["whole_execute_wall_ns"], 0)
            self.assertTrue((args.output / "result.json").is_file())

    def test_preflight_exception_still_retains_self_cost_and_unknown_child_total(self):
        with tempfile.TemporaryDirectory() as temporary:
            args = SimpleNamespace(output=Path(temporary) / "rejected")
            with patch(
                "warm_trial.execute_body", side_effect=ValueError("pinned source drift")
            ):
                with self.assertRaisesRegex(ValueError, "source drift"):
                    execute(args)
            measured = json.loads((args.output / "controller-cost.json").read_bytes())
            self.assertIn("source drift", measured["error"])
            self.assertIsNone(measured["charged_child_cpu_ns"])
            self.assertIsNone(measured["controller_plus_child_cpu_ns"])
            self.assertGreaterEqual(measured["self_cpu_ns"], 0)


if __name__ == "__main__":
    unittest.main()
