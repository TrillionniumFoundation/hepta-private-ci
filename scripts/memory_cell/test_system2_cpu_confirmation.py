"""Frozen new synthetic cohort and no outcome-based selection."""

import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from system2_cpu_confirmation import BASE_CAP, PREFILTER_CAP, REPEATS, fresh_cohort, run
from system2_cpu_exchange import cohorts


class ConfirmationTests(unittest.TestCase):
    def test_fixed_caps_and_unexposed_multisets(self):
        old, dev = cohorts()
        fresh = fresh_cohort()
        self.assertEqual((BASE_CAP, PREFILTER_CAP, REPEATS), (512, 1024, 5))
        self.assertEqual(len(fresh), 48)
        self.assertFalse(set(fresh) & (set(old) | set(dev)))

    def test_real_runner_covers_all_480_conditions_and_seals(self):
        def fake(n, cap, profile):
            return dict(
                cpu_ns=80 if profile == "prefilter" else 100,
                wall_ns=100,
                found=False,
                proof=None,
                work=dict(generated_successors=10),
                verification_skips=0,
            )

        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp) / "confirm"
            with patch("system2_cpu_confirmation.one", side_effect=fake):
                receipt = run(dest, source_commit="a" * 40)
            self.assertEqual(
                (receipt["planned"], receipt["recorded"], receipt["failed"]),
                (480, 480, 0),
            )
            self.assertEqual(
                receipt["candidate_disposition"], "stop_no_stable_cpu_confirmation"
            )
            self.assertTrue((dest / "prediction-seal.json").exists())
            self.assertFalse(receipt["production_accepted"])

    def test_failure_is_recorded_and_never_scored_as_negative_proof(self):
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp) / "confirm"
            with patch(
                "system2_cpu_confirmation.one", side_effect=RuntimeError("injected")
            ):
                with self.assertRaises(RuntimeError):
                    run(dest, source_commit="b" * 40)
            report = json.loads((dest / "run-failure.json").read_text())
            self.assertFalse(report["complete"])
            self.assertTrue(report["missing_work_not_imputed"])
            self.assertEqual(
                len((dest / "predictions.jsonl").read_text().splitlines()), 1
            )
            self.assertFalse((dest / "summary.json").exists())

    def test_invalid_source_identity(self):
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp) / "confirm"
            with self.assertRaises(ValueError):
                run(dest, source_commit="wrong")
            self.assertFalse(dest.exists())


if __name__ == "__main__":
    unittest.main()
