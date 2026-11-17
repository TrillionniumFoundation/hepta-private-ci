"""Readiness accounting tests; scripted predictors are never model evidence."""

import copy
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from . import development_readiness_v3 as readiness, repo_execution
from . import test_repo_interaction_v3 as support


class ReadinessAccountingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        support.InteractionV3Tests.setUpClass()
        cls.record = copy.deepcopy(support.InteractionV3Tests.prepared)
        cls.record["exposure"] = "development"
        cls.answer = support.InteractionV3Tests.correct

    def test_no_followup_has_no_recovery_rate_and_real_retry_is_measured(self):
        with tempfile.TemporaryDirectory() as directory:
            first = readiness.run(
                support.ScriptedPredictor(["{"]),
                [self.record],
                Path(directory) / "no-retry",
                maximum=1,
            )
            second = readiness.run(
                support.ScriptedPredictor(["{", self.answer]),
                [self.record],
                Path(directory) / "actual-retry",
                maximum=2,
            )
        self.assertEqual(
            (
                first["first_attempt_failures"],
                first["recovery_opportunities"],
                first["recovery_rate"],
                first["executed_attempts"],
            ),
            (1, 0, None, 0),
        )
        self.assertEqual(
            (
                second["successful_tasks"],
                second["recovered_tasks"],
                second["recovery_opportunities"],
                second["recovery_rate"],
                second["completed_original_calls"],
            ),
            (1, 1, 1, 1.0, 2),
        )
        self.assertFalse(second["scientific_confirmation_qualified"])
        self.assertEqual(second["independent_sample_increment"], 0)

    def test_timeout_keeps_format_admission_and_unknown_completed_calls(self):
        with (
            tempfile.TemporaryDirectory() as directory,
            patch.object(
                repo_execution.subprocess,
                "run",
                side_effect=subprocess.TimeoutExpired("verifier", 1),
            ),
        ):
            result = readiness.run(
                support.ScriptedPredictor([self.answer]),
                [self.record],
                Path(directory) / "timeout",
                maximum=1,
            )
        self.assertEqual(result["format_admitted_attempts"], 1)
        self.assertEqual(result["executed_attempts"], 1)
        self.assertIsNone(result["completed_original_calls"])
        self.assertEqual(result["completed_original_call_measured_subtotal"], 0)
        self.assertEqual(result["completed_call_measurement_missing_attempts"], 1)
        self.assertIsNone(result["recovery_rate"])


if __name__ == "__main__":
    unittest.main()
