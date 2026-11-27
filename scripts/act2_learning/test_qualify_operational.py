"""Exercise the lifecycle runner with real policies and original file owners."""

from pathlib import Path
import tempfile
import unittest

from models import Model
from qualify_operational import episode


class OperationalRunnerTests(unittest.TestCase):
    def test_all_policy_apis_execute_real_effects_under_shared_fence(self):
        with tempfile.TemporaryDirectory() as folder:
            for arm in ("fixed", "head", "gru"):
                task = {"id": arm, "version": 1, "goals": ["value"], "fault": "normal"}
                model = None if arm == "fixed" else Model(arm, 700)
                row = episode(task, arm, model, Path(folder) / arm, "pause_resume")
                self.assertEqual(
                    (
                        row["false_success"],
                        row["duplicate_effects"],
                        row["pause_count"],
                    ),
                    (False, 0, 1),
                )
                self.assertTrue(row["decisions"])
                for payload in (Path(folder) / arm / "effects").glob("*/value"):
                    self.assertEqual(payload.read_text(), "value")

    def test_expired_arm_reconciles_without_any_effect(self):
        with tempfile.TemporaryDirectory() as folder:
            task = {
                "id": "expired",
                "version": 2,
                "goals": ["value"],
                "fault": "normal",
            }
            row = episode(task, "fixed", None, Path(folder) / "owner", "expired")
            self.assertEqual(
                (
                    row["effect_count"],
                    row["state"],
                    row["effect_knowledge"],
                    row["claimed_success"],
                ),
                (0, "DEADLINE", "CONFIRMED_INCOMPLETE", False),
            )


if __name__ == "__main__":
    unittest.main()
