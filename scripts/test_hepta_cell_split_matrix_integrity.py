"""Fail-closed, offline integrity regressions for Cell Split target-host evidence.

These synthetic fixtures ONLY test report and subprocess protocol validation.
They do NOT assert that an observer is independent or authorize Cell Split.
"""

from __future__ import annotations

import copy
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from subprocess import CompletedProcess
from unittest.mock import patch


SCRIPT = Path(__file__).with_name("hepta-cell-split-target-matrix.py")
SPEC = importlib.util.spec_from_file_location("cell_split_matrix", SCRIPT)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError("cannot import cell split matrix script")
MATRIX = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MATRIX)

SOURCE = "b" * 40
WORKLOAD = "a" * 64
METRICS = {
    "p50Micros": 10,
    "p95Micros": 20,
    "p99Micros": 30,
    "throughputPerSecond": 100.0,
    "cpuMicros": 200,
    "rssBytes": 300,
    "communicationBytes": 400,
    "fsyncCount": 1,
    "lockWaitMicros": 2,
    "recoveryMicros": 3,
    "negativeMigrationQ32": 0,
}
PROVISIONAL_KEYS = (
    "schema",
    "authority",
    "sourceCommit",
    "workloadDigest",
    "workloadSourceDigest",
    "host",
    "cases",
)


def synthetic_complete_report() -> dict:
    cases = [
        {
            **case,
            "workloadDigest": WORKLOAD,
            "status": "measured",
            "metrics": dict(METRICS),
            "metricsDigest": MATRIX.digest(METRICS),
        }
        for case in MATRIX.matrix_cases()
    ]
    provisional = {
        "schema": MATRIX.SCHEMA,
        "authority": MATRIX.AUTHORITY,
        "sourceCommit": SOURCE,
        "workloadDigest": WORKLOAD,
        "workloadSourceDigest": WORKLOAD,
        "host": {
            "hostId": "synthetic-only",
            "platform": "fixture",
            "python": "fixture",
        },
        "cases": cases,
    }
    observer = {
        "verified": True,
        "observerId": "untrusted-test-only",
        "sourceCommit": SOURCE,
        "workloadDigest": WORKLOAD,
        "reportDigest": MATRIX.digest(provisional),
        "metricsDigest": MATRIX.digest(
            [
                {"caseId": case["caseId"], "metricsDigest": case["metricsDigest"]}
                for case in cases
            ]
        ),
    }
    observer["receiptDigest"] = MATRIX.digest(observer)
    return {
        **provisional,
        "observer": observer,
        "blockingCases": [],
        "status": "qualified",
        "reportDigest": MATRIX.digest({**provisional, "observer": observer}),
    }


def reseal_untrusted_fixture(report: dict) -> None:
    """Rehash intentionally forged evidence to test SEMANTIC checks, not SHA checks."""
    provisional = {key: report[key] for key in PROVISIONAL_KEYS}
    observer = report["observer"]
    observer["reportDigest"] = MATRIX.digest(provisional)
    observer["metricsDigest"] = MATRIX.digest(
        [
            {"caseId": row["caseId"], "metricsDigest": row.get("metricsDigest")}
            for row in report["cases"]
        ]
    )
    observer["receiptDigest"] = MATRIX.digest(
        {key: value for key, value in observer.items() if key != "receiptDigest"}
    )
    report["reportDigest"] = MATRIX.digest({**provisional, "observer": observer})


class MatrixIntegrityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.report = synthetic_complete_report()
        # platform.platform() may itself call subprocess.run(['uname', ...]).
        # Tests stub the matrix worker's subprocess.run, not platform probes.
        platform_stub = patch.object(
            MATRIX.platform, "platform", return_value="synthetic-test-host"
        )
        platform_stub.start()
        self.addCleanup(platform_stub.stop)

    def test_synthetic_claim_without_independent_signer_is_denied(self) -> None:
        with self.assertRaisesRegex(ValueError, "independently pinned observer trust"):
            MATRIX.validate_report(self.report)
        self.assertEqual(self.report["authority"], "DENY_ALL")

    def test_large_workload_hash_is_streamed_without_read_bytes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "large-frozen-workload.bin"
            chunk = b"x" * (1024 * 1024)
            expected = MATRIX.hashlib.sha256()
            with path.open("wb") as stream:
                for _ in range(12):
                    stream.write(chunk)
                    expected.update(chunk)
            with patch.object(
                Path,
                "read_bytes",
                side_effect=AssertionError("whole-file copy forbidden"),
            ):
                self.assertEqual(MATRIX.sha256_file(path), expected.hexdigest())

    def test_repeated_case_with_same_sixteen_id_set_fails(self) -> None:
        self.report["cases"].append(copy.deepcopy(self.report["cases"][0]))
        with self.assertRaisesRegex(ValueError, "exactly sixteen"):
            MATRIX.validate_report(self.report)

    def test_forged_factor_tuple_with_recomputed_digests_fails(self) -> None:
        self.report["cases"][0]["encoder_topology"] = "replicated"
        reseal_untrusted_fixture(self.report)
        with self.assertRaisesRegex(ValueError, "factor tuple"):
            MATRIX.validate_report(self.report)

    def test_case_workload_changed_and_resealed_fails(self) -> None:
        self.report["cases"][0]["workloadDigest"] = "c" * 64
        reseal_untrusted_fixture(self.report)
        with self.assertRaisesRegex(ValueError, "case workload"):
            MATRIX.validate_report(self.report)

    def test_source_workload_digest_changed_and_resealed_fails(self) -> None:
        self.report["workloadSourceDigest"] = "d" * 64
        reseal_untrusted_fixture(self.report)
        with self.assertRaisesRegex(ValueError, "source digest"):
            MATRIX.validate_report(self.report)

    def test_final_report_digest_tamper_fails(self) -> None:
        self.report["reportDigest"] = "0" * 64
        with self.assertRaisesRegex(ValueError, "final report digest"):
            MATRIX.validate_report(self.report)

    def test_observer_receipt_digest_tamper_fails(self) -> None:
        self.report["observer"]["receiptDigest"] = "0" * 64
        provisional = {key: self.report[key] for key in PROVISIONAL_KEYS}
        self.report["reportDigest"] = MATRIX.digest(
            {**provisional, "observer": self.report["observer"]}
        )
        with self.assertRaisesRegex(ValueError, "observer receipt digest"):
            MATRIX.validate_report(self.report)

    def test_qualified_with_unresolved_blocker_fails(self) -> None:
        self.report["blockingCases"] = ["independent-observer"]
        with self.assertRaisesRegex(ValueError, "blockingCases"):
            MATRIX.validate_report(self.report)

    def test_blocked_without_any_real_blocker_fails(self) -> None:
        self.report["status"] = "blocked"
        with self.assertRaisesRegex(ValueError, "no blocking evidence"):
            MATRIX.validate_report(self.report)

    def test_unmeasured_case_hidden_from_blockers_fails(self) -> None:
        self.report["cases"][0].pop("metrics")
        self.report["cases"][0].pop("metricsDigest")
        self.report["cases"][0]["status"] = "blocked"
        self.report["cases"][0]["reason"] = "test-only missing worker receipt"
        reseal_untrusted_fixture(self.report)
        with self.assertRaisesRegex(ValueError, "blockingCases"):
            MATRIX.validate_report(self.report)

    def test_fractional_negative_migration_q32_fails(self) -> None:
        bad = {**METRICS, "negativeMigrationQ32": 0.5}
        with self.assertRaisesRegex(ValueError, "integer"):
            MATRIX.validate_metrics(bad)

    def test_source_head_mismatch_rejected_before_worker(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workload = Path(directory) / "workload.json"
            workload.write_bytes(b"example bytes")
            actual_digest = MATRIX.hashlib.sha256(workload.read_bytes()).hexdigest()
            fake_git = CompletedProcess(
                args=["git"], returncode=0, stdout="c" * 40 + "\n", stderr=""
            )
            with patch.object(
                MATRIX.subprocess, "run", return_value=fake_git
            ) as runner:
                with self.assertRaisesRegex(ValueError, "repository HEAD"):
                    MATRIX.run_matrix(
                        workload_command="fake-worker",
                        observer_command=None,
                        workload_digest=actual_digest,
                        source_commit=SOURCE,
                        workload_path=workload,
                        output=Path(directory) / "report.json",
                    )
                runner.assert_called_once()

    def test_worker_mutating_frozen_workload_blocks_all_sixteen(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workload = Path(directory) / "workload.json"
            workload.write_bytes(b"original")
            actual_digest = MATRIX.hashlib.sha256(workload.read_bytes()).hexdigest()

            def fake_exec(argv: list[str], **kwargs: object) -> CompletedProcess:
                if argv[0] == "git":
                    return CompletedProcess(argv, 0, stdout=SOURCE + "\n", stderr="")
                self.assertEqual(argv[0], "fake-worker")
                workload.write_bytes(b"mutated")
                return CompletedProcess(argv, 0, stdout="{}\n", stderr="")

            with patch.object(MATRIX.subprocess, "run", side_effect=fake_exec):
                report = MATRIX.run_matrix(
                    workload_command="fake-worker",
                    observer_command=None,
                    workload_digest=actual_digest,
                    source_commit=SOURCE,
                    workload_path=workload,
                    output=Path(directory) / "report.json",
                )
            self.assertEqual(report["status"], "blocked")
            self.assertEqual(len(report["blockingCases"]), 17)
            self.assertIn("frozen workload changed", report["cases"][0]["reason"])
            MATRIX.validate_report(report)

    def test_worker_missing_factor_echo_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workload = Path(directory) / "workload.json"
            workload.write_bytes(b"original")
            actual_digest = MATRIX.hashlib.sha256(workload.read_bytes()).hexdigest()

            def fake_exec(argv: list[str], **kwargs: object) -> CompletedProcess:
                if argv[0] == "git":
                    return CompletedProcess(argv, 0, stdout=SOURCE + "\n", stderr="")
                env = kwargs["env"]
                emitted = {
                    "caseId": env["HEPTA_MATRIX_CASE_ID"],
                    "sourceCommit": SOURCE,
                    "workloadDigest": actual_digest,
                    "workloadSourceDigest": actual_digest,
                    "metrics": METRICS,
                    # Missing the four requested factor values must fail closed.
                }
                return CompletedProcess(
                    argv, 0, stdout=json.dumps(emitted) + "\n", stderr=""
                )

            with patch.object(MATRIX.subprocess, "run", side_effect=fake_exec):
                report = MATRIX.run_matrix(
                    workload_command="fake-worker",
                    observer_command=None,
                    workload_digest=actual_digest,
                    source_commit=SOURCE,
                    workload_path=workload,
                    output=Path(directory) / "report.json",
                )
            self.assertEqual(report["status"], "blocked")
            self.assertEqual(len(report["blockingCases"]), 17)
            self.assertIn("workload identity", report["cases"][0]["reason"])
            MATRIX.validate_report(report)


if __name__ == "__main__":
    unittest.main()
