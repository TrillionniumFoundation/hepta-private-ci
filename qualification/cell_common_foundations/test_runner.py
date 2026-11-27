"""Regressions for evidence persistence, without rerunning the training grid."""

import json
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

from qualification.cell_common_foundations import run_reference as runner
from qualification.cell_common_foundations.protocol import (
    AttemptSpec,
    summarize_attempts,
)


class RunnerTests(unittest.TestCase):
    def test_temporal_failure_keeps_partial_evidence_and_empty_exception_type(self):
        raw = {
            "seed": 11,
            "kernel": "hcsn",
            "status": "failed",
            "error": "",
            "error_type": "RuntimeError",
            "head_updates_completed": 3,
            "cases": {"partial_loss": 0.5},
            "panel_sha256": {"train": "digest"},
        }
        row = runner._temporal_records({"attempts": [raw]})[0]
        spec = AttemptSpec(row["attempt_id"], row["family"], row["method"], row["seed"])
        summary = summarize_attempts([spec], [row])
        self.assertEqual(summary["counts"]["failed"], 1)
        self.assertEqual(row["result"], raw)
        self.assertEqual(row["reason"], "RuntimeError: <no message>")

    def test_no_completed_profiles_cannot_pass_comparison(self):
        def failed(*args, **kwargs):
            return {"status": "failed"}

        with patch(
            "qualification.cell_common_foundations.credit.run_credit_attempt", failed
        ):
            report = runner._credit_panel(lambda *args: None)
        self.assertFalse(report["comparison_contract_passed"])
        self.assertEqual(report["matched_profile_checks"], [])

    def test_outer_report_retains_events_after_rss_observation_and_refuses_replay(self):
        spec = AttemptSpec("credit-test-only", "credit", "mock", 11)

        def credit(observe):
            base = dict(
                attempt_id=spec.attempt_id,
                family=spec.family,
                method=spec.method,
                seed=spec.seed,
            )
            observe("started", {**base, "status": "running"})
            observe(
                "finished",
                {**base, "status": "completed", "result": {"test_only": True}},
            )
            return {"comparison_contract_passed": True}

        fake_torch = types.ModuleType("torch")
        fake_torch.__version__ = "test-only"
        fake_torch.set_num_threads = lambda _: None
        fake_torch.set_num_interop_threads = lambda _: None
        fake_temporal = types.ModuleType(
            "qualification.cell_common_foundations.temporal"
        )
        fake_temporal.run_temporal_pilot = lambda *args, **kwargs: {"attempts": []}
        tests = types.SimpleNamespace(
            testsRun=1,
            failures=[],
            errors=[],
            skipped=[],
            executed_names=["mock_test_only"],
            wasSuccessful=lambda: True,
        )
        with (
            tempfile.TemporaryDirectory() as temp,
            patch.object(runner, "_roster", return_value=[spec]),
            patch.object(runner, "_credit_panel", side_effect=credit),
            patch(
                "qualification.cell_common_foundations.plasticity.run_plasticity_pilot",
                return_value={},
            ),
            patch.object(
                unittest.defaultTestLoader,
                "loadTestsFromNames",
                return_value=unittest.TestSuite(),
            ),
            patch.object(unittest.TextTestRunner, "run", return_value=tests),
            patch.dict(
                sys.modules,
                {
                    "torch": fake_torch,
                    "qualification.cell_common_foundations.temporal": fake_temporal,
                },
            ),
        ):
            output = Path(temp) / "result.json"
            report = runner.run_reference(output)
            self.assertEqual(report["attempt_summary"]["counts"]["completed"], 1)
            self.assertEqual(
                report["attempt_records"][0]["result"], {"test_only": True}
            )
            files = list(output.with_suffix(".attempts").glob("*.json"))
            self.assertEqual(len(files), 2)
            self.assertEqual(
                {json.loads(path.read_text())["event"] for path in files},
                {"started", "finished"},
            )
            with self.assertRaises(ValueError):
                runner.run_reference(output)


if __name__ == "__main__":
    unittest.main()
