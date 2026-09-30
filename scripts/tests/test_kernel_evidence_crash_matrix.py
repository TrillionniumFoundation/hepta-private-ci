from __future__ import annotations

from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest import mock

from scripts import kernel_evidence_crash_matrix as crash


class CrashMatrixTests(unittest.TestCase):
    def test_exact_test_and_required_marker_are_mandatory(self) -> None:
        spec = crash.evidence_integration(
            "frontier_backend_multiprocess",
            "eight_process_first_generation_contention_has_one_durable_winner",
            "kernel_evidence_multiprocess_contention=",
        )
        output = (
            b"test eight_process_first_generation_contention_has_one_durable_winner ... ok\n"
            b"kernel_evidence_multiprocess_contention={}\n"
        )
        passed, missing, skipped = crash.assess_command(
            spec, exit_code=0, output=output, timed_out=False
        )
        self.assertTrue(passed)
        self.assertEqual(missing, [])
        self.assertFalse(skipped)

        passed, missing, _ = crash.assess_command(
            spec,
            exit_code=0,
            output=(
                b"test eight_process_first_generation_contention_"
                b"has_one_durable_winner ... ok\n"
            ),
            timed_out=False,
        )
        self.assertFalse(passed)
        self.assertIn("kernel_evidence_multiprocess_contention=", missing)

    def test_self_reported_skip_is_failure_even_when_rust_test_returns_ok(self) -> None:
        spec = crash.evidence_integration(
            "frontier_backend_multiprocess",
            "eight_process_first_generation_contention_has_one_durable_winner",
        )
        output = (
            b"skipping: external and local roots share one device\n"
            b"test eight_process_first_generation_contention_has_one_durable_winner ... ok\n"
        )
        passed, _, skipped = crash.assess_command(
            spec, exit_code=0, output=output, timed_out=False
        )
        self.assertFalse(passed)
        self.assertTrue(skipped)

    def test_each_command_retains_its_own_log_and_timestamps(self) -> None:
        spec = crash.evidence_lib("tests::example")
        completed = subprocess.CompletedProcess(
            args=spec.argv(),
            returncode=0,
            stdout=b"test tests::example ... ok\n",
        )
        with tempfile.TemporaryDirectory() as temporary:
            log = Path(temporary) / "one.log"
            with mock.patch.object(crash.subprocess, "run", return_value=completed):
                result = crash.run_command(
                    spec,
                    workspace=Path(temporary),
                    log_path=log,
                    timeout_seconds=10,
                    environment={},
                )
            self.assertEqual(result["status"], "passed")
            self.assertEqual(result["exitCode"], 0)
            self.assertGreaterEqual(
                result["finishedAtUnixMs"], result["startedAtUnixMs"]
            )
            self.assertEqual(log.read_bytes(), completed.stdout)
            self.assertEqual(result["logSha256"], crash.sha256_bytes(completed.stdout))


if __name__ == "__main__":
    unittest.main()
