import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from cognitive_read_evidence import (
    BENCHMARK_SCHEMAS,
    EXACT_TEST_CASES,
    NEXTEST_VERSION,
    TEST_GATES,
    candidate_source_problems,
    commands,
    emit,
    git,
    nextest_log_problems,
    validate_candidate_claims,
    validate_evidence,
)


class EvidenceGateTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.evidence = Path(self.temporary.name)
        self.required = commands("a" * 40, self.evidence)
        for label, argv in self.required.items():
            (self.evidence / f"{label}.command.json").write_text(json.dumps(argv))
            (self.evidence / f"{label}.log").write_text("Summary [0.1s] 1 test run: 1 passed, 0 skipped\n")
            if label == "test-runner":
                commit = "d2e7b879fb79975e8b47a8e3ce569b651e6381c0"
                (self.evidence / f"{label}.log").write_text(
                    f"cargo-nextest {NEXTEST_VERSION} ({commit[:9]} 2025-08-25)\n"
                    f"release: {NEXTEST_VERSION}\n"
                    f"commit-hash: {commit}\n"
                    "commit-date: 2025-08-25\n"
                    "host: x86_64-unknown-linux-gnu\n"
                )
            elif label in EXACT_TEST_CASES:
                binary, case = EXACT_TEST_CASES[label]
                (self.evidence / f"{label}.log").write_text(
                    f"PASS [0.1s] {binary} {case}\n"
                    "Summary [0.1s] 1 test run: 1 passed, 99 skipped\n"
                )
            (self.evidence / f"{label}.exit-code").write_text("0\n")
            if label in BENCHMARK_SCHEMAS:
                value = {"schema": BENCHMARK_SCHEMAS[label], "iterations": 32}
                if label == "benchmark":
                    value.update(records=16384, requested_ids=512, p50_us=1, p95_us=2, p99_us=3)
                else:
                    value["cases"] = []
                    for records in (128, 4096, 16384):
                        for depth in (1, 8):
                            for requested in (1, 512):
                                row = {"records": records, "revision_depth": depth, "requested_ids": min(requested, records // depth)}
                                for mode in ("one_shot_pair", "prepared_pair_including_build", "prepare_only", "projection_only"):
                                    row[mode] = {"p50_ns": 1, "p95_ns": 2, "p99_ns": 3}
                                value["cases"].append(row)
                (self.evidence / f"{label}.json").write_text(json.dumps(value))

    def test_complete_evidence_is_accepted(self):
        self.assertEqual(validate_evidence(self.evidence, self.required), [])

    def test_pinned_nextest_structured_multiline_version_is_accepted(self):
        commit = "d2e7b879fb79975e8b47a8e3ce569b651e6381c0"
        (self.evidence / "test-runner.log").write_text(
            f"cargo-nextest {NEXTEST_VERSION} ({commit[:9]} 2025-08-25)\n"
            f"release: {NEXTEST_VERSION}\n"
            f"commit-hash: {commit}\n"
            "commit-date: 2025-08-25\n"
            "host: x86_64-unknown-linux-gnu\n"
        )
        self.assertEqual(validate_evidence(self.evidence, self.required), [])

    def test_pinned_nextest_unstructured_multiline_version_is_rejected(self):
        commit = "d2e7b879fb79975e8b47a8e3ce569b651e6381c0"
        (self.evidence / "test-runner.log").write_text(
            f"cargo-nextest {NEXTEST_VERSION} ({commit[:9]} 2025-08-25)\n"
            f"release: {NEXTEST_VERSION}\n"
            f"commit-hash: {commit}\n"
            "commit-date: 2025-08-25\n"
            "host: x86_64-unknown-linux-gnu\n"
            "unexpected: injected evidence\n"
        )
        self.assertTrue(validate_evidence(self.evidence, self.required))

    def test_pinned_nextest_mismatched_metadata_is_rejected(self):
        commit = "d2e7b879fb79975e8b47a8e3ce569b651e6381c0"
        (self.evidence / "test-runner.log").write_text(
            f"cargo-nextest {NEXTEST_VERSION} ({commit[:9]} 2025-08-25)\n"
            f"release: {NEXTEST_VERSION}\n"
            f"commit-hash: {commit}\n"
            "commit-date: 2025-08-26\n"
            "host: x86_64-unknown-linux-gnu\n"
        )
        self.assertTrue(validate_evidence(self.evidence, self.required))

    def test_every_required_gate_must_have_a_command_log_and_exit(self):
        for label in self.required:
            for suffix in ("command.json", "log", "exit-code"):
                path = self.evidence / f"{label}.{suffix}"
                original = path.read_bytes()
                path.unlink()
                with self.subTest(label=label, suffix=suffix):
                    self.assertTrue(validate_evidence(self.evidence, self.required))
                path.write_bytes(original)

    def test_successful_unrelated_command_is_not_evidence(self):
        (self.evidence / "core-tests.command.json").write_text('["true"]')
        self.assertTrue(validate_evidence(self.evidence, self.required))

    def test_zero_executed_tests_rejected(self):
        for label in TEST_GATES:
            path = self.evidence / f"{label}.log"
            original = path.read_text()
            path.write_text("Summary [0.0s] 0 tests run: 0 passed\n")
            with self.subTest(label=label):
                self.assertTrue(validate_evidence(self.evidence, self.required))
            path.write_text(original)

    def test_nonzero_exit_rejected(self):
        (self.evidence / "strict-clippy.exit-code").write_text("101\n")
        self.assertTrue(validate_evidence(self.evidence, self.required))

    def test_missing_measurement_rejected(self):
        (self.evidence / "prepared-benchmark.json").unlink()
        self.assertTrue(validate_evidence(self.evidence, self.required))

    def test_invalid_measurement_rejected(self):
        (self.evidence / "benchmark.json").write_text("{broken")
        self.assertTrue(validate_evidence(self.evidence, self.required))

    def test_one_iteration_does_not_establish_percentiles(self):
        path = self.evidence / "benchmark.json"
        path.write_text(json.dumps({"schema": BENCHMARK_SCHEMAS["benchmark"], "iterations": 1}))
        self.assertTrue(validate_evidence(self.evidence, self.required))

    def test_fabricated_measurement_header_is_insufficient(self):
        path = self.evidence / "prepared-benchmark.json"
        path.write_text(json.dumps({"schema": BENCHMARK_SCHEMAS["prepared-benchmark"], "iterations": 32}))
        self.assertTrue(validate_evidence(self.evidence, self.required))

    def test_symlink_evidence_rejected(self):
        path = self.evidence / "core-tests.log"
        path.unlink()
        path.symlink_to(self.evidence / "owner-tests.log")
        self.assertTrue(validate_evidence(self.evidence, self.required))

    def test_duplicate_native_pass_cannot_claim_one_physical_worker_execution(self):
        path = self.evidence / "native-final-use-e2e.log"
        body = path.read_text()
        path.write_text(body.splitlines()[0] + "\n" + body)
        self.assertTrue(validate_evidence(self.evidence, self.required))

    def test_product_gates_require_exact_binary_case_and_single_execution(self):
        for label in ("product-read-replay", "product-write-smoke"):
            argv = self.required[label]
            self.assertEqual(argv[argv.index("--status-level") + 1], "pass")
            path = self.evidence / f"{label}.log"
            original = path.read_text()
            binary, case = EXACT_TEST_CASES[label]
            for body in (
                original.replace(binary, "unrelated-binary"),
                original.replace(case, "unrelated_case"),
                original.splitlines()[0] + "\n" + original,
                original.replace("1 test run: 1 passed", "2 tests run: 2 passed"),
                original.splitlines()[1] + "\n",
            ):
                path.write_text(body)
                with self.subTest(label=label, body=body):
                    self.assertTrue(validate_evidence(self.evidence, {label: argv}))
            path.write_text(original.replace(binary, binary.replace("-", "_")))
            self.assertEqual(validate_evidence(self.evidence, {label: argv}), [])
            path.write_text(original)


class CandidateIdentityTests(unittest.TestCase):
    def test_source_cannot_be_relabelled_as_a_merge(self):
        self.assertTrue(validate_candidate_claims("a" * 40, "merge-candidate", ["b" * 40],
                                                  {"activation": False}, "c" * 40, "b" * 40))

    def test_ordered_merge_parents_must_match_frozen_inputs(self):
        self.assertEqual(validate_candidate_claims("a" * 40, "merge-candidate", ["b" * 40, "c" * 40],
                                                   {"activation": False}, "c" * 40, "b" * 40), [])
        self.assertTrue(validate_candidate_claims("a" * 40, "merge-candidate", ["c" * 40, "b" * 40],
                                                  {"activation": False}, "c" * 40, "b" * 40))

    def test_active_or_missing_activation_is_rejected(self):
        for mapping in ({}, {"activation": True}, {"activation": False, "nested": {"activation": True}}):
            with self.subTest(mapping=mapping):
                self.assertTrue(validate_candidate_claims("a" * 40, "source-head", [], mapping, "a" * 40, None))


class NextestSummaryIntegrityTests(unittest.TestCase):
    SUCCESS = "Summary [   4.213s] 226 tests run: 226 passed, 1 skipped\n"

    def test_real_summary_and_passed_subsets_are_accepted(self):
        for summary in (
            self.SUCCESS,
            self.SUCCESS.replace("226 passed", "226 passed (4 slow, 2 flaky, 1 leaky)"),
            "Summary [0.001s] 1 test run: 1 passed (1 slow, 1 flaky, 1 leaky), 0 skipped\n",
        ):
            with self.subTest(summary=summary):
                self.assertEqual(nextest_log_problems("gate", summary), [])

    def test_every_terminal_summary_is_counted(self):
        for later in (
            self.SUCCESS,
            "Summary [4.214s] 226 tests run: 226 failed\n",
            "Summary [4.214s] cancelled\n",
            "Summary malformed\n",
        ):
            with self.subTest(later=later):
                self.assertTrue(nextest_log_problems("gate", self.SUCCESS + later))

    def test_failure_timeout_and_partial_run_cannot_follow_a_pass_count(self):
        for summary in (
            self.SUCCESS.replace("1 skipped", "1 failed, 1 skipped"),
            self.SUCCESS.replace("1 skipped", "1 exec failed, 1 skipped"),
            self.SUCCESS.replace("1 skipped", "1 timed out, 1 skipped"),
            self.SUCCESS.replace("226 tests", "226/227 tests"),
            self.SUCCESS.replace("226 passed", "225 passed"),
            self.SUCCESS.replace(", 1 skipped", ""),
            self.SUCCESS.replace("1 skipped", "1 skipped, cancelled"),
        ):
            with self.subTest(summary=summary):
                self.assertTrue(nextest_log_problems("gate", summary))

    def test_invalid_passed_subsets_are_rejected(self):
        for annotation in (
            "227 slow", "0 slow", "1 failed", "1 flaky, 1 slow", "1 slow, 1 slow", "",
        ):
            summary = self.SUCCESS.replace("226 passed", f"226 passed ({annotation})")
            with self.subTest(annotation=annotation):
                self.assertTrue(nextest_log_problems("gate", summary))

    def test_cancellation_notice_cannot_be_hidden_by_a_success_summary(self):
        for status in ("Cancelling", "Killing"):
            body = f"{status} due to signal\n" + self.SUCCESS
            with self.subTest(status=status):
                self.assertTrue(nextest_log_problems("gate", body))


class CandidateSourceIntegrityTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        mapping = self.root / "docs/modules/cognitive.read/IMPLEMENTATION_MAP.json"
        mapping.parent.mkdir(parents=True)
        mapping.write_text('{"activation": false}')
        subprocess.run(["git", "init", "-q", str(self.root)], check=True)
        subprocess.run(["git", "-C", str(self.root), "add", "."], check=True)
        subprocess.run(
            ["git", "-C", str(self.root), "-c", "user.name=Audit",
             "-c", "user.email=audit@example.invalid", "commit", "-qm", "fixture"],
            check=True,
        )

    def test_untracked_migration_is_not_an_exact_candidate_input(self):
        path = self.root / "codex-rs/hepta-memory/migrations/9999_untracked.sql"
        path.parent.mkdir(parents=True)
        path.write_text("CREATE TABLE untracked_build_input(x INT);")
        self.assertEqual(git(self.root, "status", "--porcelain", "--untracked-files=no"), "")
        self.assertEqual(
            candidate_source_problems(self.root),
            ["candidate has untracked source input: codex-rs/hepta-memory/migrations/9999_untracked.sql"],
        )
        evidence = self.root / ".hepta-evidence/fixture"
        evidence.mkdir(parents=True)
        output = evidence / "receipt.json"
        with patch("cognitive_read_evidence.commands", return_value={}), patch(
            "cognitive_read_evidence.validate_candidate_claims", return_value=[]
        ):
            self.assertFalse(emit(self.root, evidence, git(self.root, "rev-parse", "HEAD"),
                                  "source-head", output))
        self.assertFalse(json.loads(output.read_text())["passed"])

    def test_regular_evidence_output_is_allowed(self):
        path = self.root / ".hepta-evidence/fixture/command.json"
        path.parent.mkdir(parents=True)
        path.write_text("[]")
        self.assertEqual(candidate_source_problems(self.root), [])

    def test_evidence_aliases_and_prefix_lookalikes_are_rejected(self):
        path = self.root / ".hepta-evidence-other/input.rs"
        path.parent.mkdir()
        path.write_text("fn untracked() {}")
        self.assertTrue(candidate_source_problems(self.root))
        path.unlink()
        path.parent.rmdir()
        evidence = self.root / ".hepta-evidence"
        evidence.mkdir()
        (evidence / "alias").symlink_to(self.root / "docs", target_is_directory=True)
        self.assertTrue(candidate_source_problems(self.root))

    def test_leading_whitespace_cannot_alias_evidence(self):
        path = self.root / " .hepta-evidence/input.rs"
        path.parent.mkdir()
        path.write_text("fn untracked() {}")
        self.assertEqual(
            candidate_source_problems(self.root),
            ["candidate has untracked source input:  .hepta-evidence/input.rs"],
        )


if __name__ == "__main__":
    unittest.main()
