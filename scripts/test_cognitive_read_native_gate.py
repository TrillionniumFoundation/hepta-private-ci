"""Regression tests for the mandatory real-worker qualification gate.

These exercise evidence rejection, not a Rust build or product execution.
"""
from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

import cognitive_read_evidence as evidence


class NativeFinalUseGateTests(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.argv = evidence.commands("a" * 40, self.root)["native-final-use-e2e"]

    def record(self, body: str, *, code: int = 0, argv: list[str] | None = None) -> None:
        (self.root / "native-final-use-e2e.command.json").write_text(
            json.dumps(self.argv if argv is None else argv)
        )
        (self.root / "native-final-use-e2e.log").write_text(body)
        (self.root / "native-final-use-e2e.exit-code").write_text(str(code))

    def problems(self) -> list[str]:
        return evidence.validate_evidence(
            self.root, {"native-final-use-e2e": self.argv}
        )

    def passed_log(self, name: str | None = None) -> str:
        return (
            "PASS [  1.234s] codex_hepta_infer_worker_host "
            f"{name or evidence.NATIVE_FINAL_USE_TEST}\n"
            "Summary [1.250s] 1 test run: 1 passed, 99 skipped\n"
        )

    def test_real_worker_gate_uses_exact_lib_selector_and_zero_match_rejection(self) -> None:
        self.assertEqual(
            self.argv,
            [
                "just", "test", "--locked", "-p", "codex-hepta-infer-worker-host",
                "--lib", "--no-tests=fail", "--status-level", "pass", "-E",
                f"test(={evidence.NATIVE_FINAL_USE_TEST})",
            ],
        )
        self.assertNotIn("--features", self.argv)

    def test_exact_executed_case_is_accepted(self) -> None:
        self.record(self.passed_log())
        self.assertEqual(self.problems(), [])

    def test_colored_nextest_status_is_accepted(self) -> None:
        self.record(self.passed_log().replace("PASS", "\x1b[32mPASS\x1b[0m"))
        self.assertEqual(self.problems(), [])

    def test_package_spelling_is_accepted(self) -> None:
        self.record(self.passed_log().replace("codex_hepta_infer_worker_host", "codex-hepta-infer-worker-host"))
        self.assertEqual(self.problems(), [])

    def test_missing_gate_is_rejected(self) -> None:
        self.assertTrue(self.problems())

    def test_unrelated_successful_case_cannot_replace_worker_execution(self) -> None:
        self.record(self.passed_log("native_app_server::tests::unrelated_case"))
        self.assertTrue(self.problems())

    def test_named_case_printed_as_plain_text_is_not_execution(self) -> None:
        self.record(
            f"selected test: {evidence.NATIVE_FINAL_USE_TEST}\n"
            "Summary [0.02s] 1 test run: 1 passed\n"
        )
        self.assertTrue(self.problems())

    def test_zero_run_summary_overrides_an_earlier_pass_line(self) -> None:
        self.record(self.passed_log() + "Summary [0.00s] 0 tests run: 0 passed\n")
        self.assertTrue(self.problems())

    def test_skip_is_not_a_pass(self) -> None:
        self.record(self.passed_log().replace("PASS [", "SKIP ["))
        self.assertTrue(self.problems())

    def test_failed_command_is_not_qualified_by_a_pass_line(self) -> None:
        self.record(self.passed_log(), code=1)
        self.assertTrue(self.problems())

    def test_broadened_selector_is_rejected(self) -> None:
        self.record(self.passed_log(), argv=[*self.argv[:-1], "test(native_app_server)"])
        self.assertTrue(self.problems())

    def test_two_executed_cases_do_not_match_the_exact_gate(self) -> None:
        self.record(self.passed_log().replace("1 test run: 1 passed", "2 tests run: 2 passed"))
        self.assertTrue(self.problems())

    def test_failure_from_other_binary_cannot_claim_the_worker_case(self) -> None:
        self.record(self.passed_log().replace("codex_hepta_infer_worker_host", "unrelated_binary"))
        self.assertTrue(self.problems())


class PinnedRunnerGateTests(unittest.TestCase):
    COMMIT = "d2e7b879fb79975e8b47a8e3ce569b651e6381c0"
    DATE = "2025-08-25"

    def check_version(self, version: str, code: int = 0) -> list[str]:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            argv = ["cargo", "nextest", "--version"]
            (root / "test-runner.command.json").write_text(json.dumps(argv))
            (root / "test-runner.log").write_text(version)
            (root / "test-runner.exit-code").write_text(str(code))
            return evidence.validate_evidence(root, {"test-runner": argv})

    def structured_version(
        self,
        *,
        short: str | None = None,
        full: str | None = None,
        first_date: str | None = None,
        commit_date: str | None = None,
        release: str | None = None,
        extra: str = "",
    ) -> str:
        full_hash = full or self.COMMIT
        short_hash = short or full_hash[:9]
        header_date = first_date or self.DATE
        metadata_date = commit_date or self.DATE
        release_version = release or evidence.NEXTEST_VERSION
        return (
            f"cargo-nextest {evidence.NEXTEST_VERSION} ({short_hash} {header_date})\n"
            f"release: {release_version}\n"
            f"commit-hash: {full_hash}\n"
            f"commit-date: {metadata_date}\n"
            "host: x86_64-unknown-linux-gnu\n"
            f"{extra}"
        )

    def test_exact_structured_runner_metadata_is_accepted(self) -> None:
        self.assertEqual(self.check_version(self.structured_version()), [])

    def test_absent_wrong_or_prefixed_version_is_rejected(self) -> None:
        for value in (
            "",
            "cargo 1.95.0",
            "cargo-nextest 0.9.10",
            "cargo-nextest 0.9.1030",
            f"cargo-nextest {evidence.NEXTEST_VERSION}\n",
        ):
            with self.subTest(value=value):
                self.assertTrue(self.check_version(value))

    def test_extra_or_mismatched_structured_metadata_is_rejected(self) -> None:
        cases = (
            self.structured_version(extra="unexpected: injected evidence\n"),
            self.structured_version(commit_date="2025-08-26"),
            self.structured_version(release="0.9.102"),
            self.structured_version(short="aaaaaaaaa"),
            self.structured_version(full="not-a-commit"),
        )
        for value in cases:
            with self.subTest(value=value):
                self.assertTrue(self.check_version(value))

    def test_failed_probe_cannot_pass(self) -> None:
        self.assertTrue(self.check_version(self.structured_version(), code=127))


if __name__ == "__main__":
    unittest.main()
