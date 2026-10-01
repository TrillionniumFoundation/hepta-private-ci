"""Reject misleading named-gate and per-consumer qualification evidence."""

import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import cognitive_read_full_evidence as full


class FullGateIntegrityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.evidence = Path(self.temporary.name)
        self.label = "revision-shadow-tests"
        self.argv = full.commands("a" * 40, self.evidence)[self.label]
        self.cases = full.EXACT_CASES[self.label]
        self.binary = full.EXACT_BINARIES[self.label]
        self.log = (
            "\n".join(f"PASS [0.1s] {self.binary} {case}" for case in self.cases)
            + f"\nSummary [0.3s] {len(self.cases)} tests run: {len(self.cases)} passed, 0 skipped\n"
        )
        self.record(self.log)

    def record(self, log: str) -> None:
        (self.evidence / f"{self.label}.command.json").write_text(json.dumps(self.argv))
        (self.evidence / f"{self.label}.exit-code").write_text("0")
        (self.evidence / f"{self.label}.log").write_text(log)

    def problems(self) -> list[str]:
        return full.validate_evidence(self.evidence, {self.label: self.argv})

    def test_exact_case_set_passes_and_can_report_gate_success(self) -> None:
        self.assertEqual(self.problems(), [])
        self.assertTrue(full.gate_status(self.evidence, self.label))

    def test_context_ingress_gate_requires_envelope_preflight_execution(self) -> None:
        label = "context-v2-ingress-tests"
        argv = full.commands("a" * 40, self.evidence)[label]
        cases = full.EXACT_CASES[label]
        rows = [f"PASS [0.1s] {full.EXACT_BINARIES[label]} {case}" for case in cases]
        (self.evidence / f"{label}.command.json").write_text(json.dumps(argv))
        (self.evidence / f"{label}.exit-code").write_text("0")
        log = self.evidence / f"{label}.log"
        log.write_text(
            "\n".join(rows)
            + f"\nSummary [0.4s] {len(cases)} tests run: {len(cases)} passed, 0 skipped\n"
        )
        self.assertEqual(full.validate_evidence(self.evidence, {label: argv}), [])
        rows = [
            row
            for row in rows
            if "ingress_envelope_preflight_precedes_shadow_validation" not in row
        ]
        log.write_text(
            "\n".join(rows)
            + f"\nSummary [0.3s] {len(rows)} tests run: {len(rows)} passed, 0 skipped\n"
        )
        self.assertTrue(full.validate_evidence(self.evidence, {label: argv}))
        self.assertFalse(full.gate_status(self.evidence, label))

    def test_wrong_binary_or_only_leaf_name_is_rejected(self) -> None:
        for log in (
            self.log.replace(self.binary, "unrelated-binary"),
            self.log.replace(self.cases[0], self.cases[0].split("::")[-1]),
            self.log.replace(self.cases[0], "unrelated::" + self.cases[0]),
        ):
            with self.subTest(log=log):
                self.record(log)
                self.assertTrue(self.problems())
                self.assertFalse(full.gate_status(self.evidence, self.label))

    def test_extra_execution_duplicate_pass_and_failed_summary_are_rejected(
        self,
    ) -> None:
        for log in (
            self.log.replace("3 tests run: 3 passed", "99 tests run: 99 passed"),
            self.log + self.log.splitlines()[0] + "\n",
            self.log.replace(
                "3 tests run: 3 passed", "3 tests run: 2 passed, 1 failed"
            ),
            self.log + "Summary [0.4s] 0 tests run: 0 passed\n",
            self.log.replace("0 skipped", "1 failed, 0 skipped"),
            self.log + "Summary [0.4s] 3 tests run: 3 failed\n",
            self.log + "Summary [0.4s] cancelled\n",
            "Cancelling due to signal\n" + self.log,
        ):
            with self.subTest(log=log):
                self.record(log)
                self.assertTrue(self.problems())
                self.assertFalse(full.gate_status(self.evidence, self.label))

    def test_zero_exit_without_a_command_or_log_cannot_report_success(self) -> None:
        for suffix in ("command.json", "log"):
            path = self.evidence / f"{self.label}.{suffix}"
            contents = path.read_bytes()
            path.unlink()
            self.assertFalse(full.gate_status(self.evidence, self.label))
            path.write_bytes(contents)

    def test_command_substitution_and_symlink_exit_cannot_report_success(self) -> None:
        (self.evidence / f"{self.label}.command.json").write_text('["true"]')
        self.assertFalse(full.gate_status(self.evidence, self.label))
        self.record(self.log)
        code = self.evidence / f"{self.label}.exit-code"
        code.unlink()
        target = self.evidence / "another-run.exit-code"
        target.write_text("0")
        code.symlink_to(target)
        self.assertFalse(full.gate_status(self.evidence, self.label))

    def test_measurement_from_another_commit_or_tree_is_rejected(self) -> None:
        candidate = {"commit": "a" * 40, "tree": "b" * 40}
        path = self.evidence / "sqlite-capacity.json"
        path.write_text(json.dumps({"candidate": candidate}))
        self.assertEqual(
            full.measurement_candidate_problems(self.evidence, candidate), []
        )
        for field in ("commit", "tree"):
            measured = {**candidate, field: "c" * 40}
            path.write_text(json.dumps({"candidate": measured}))
            self.assertTrue(
                full.measurement_candidate_problems(self.evidence, candidate)
            )

    def test_mismatched_measurement_fails_overall_and_local_receipt_status(
        self,
    ) -> None:
        candidate = {"commit": "a" * 40, "tree": "b" * 40}
        distribution = {"p50_us": 1, "p95_us": 2, "p99_us": 3}
        measurement = {
            "schema": full.SQLITE_CAPACITY_SCHEMA,
            "records": 512,
            "requested_ids": 512,
            "iterations": 32,
            "authority": "deny_all",
            "candidate": {**candidate, "tree": "c" * 40},
            **{
                name: 1
                for name in (
                    "sqlite_file_bytes",
                    "sqlite_page_count",
                    "sqlite_page_size_bytes",
                    "sqlite_memory_revision_rows",
                    "sqlite_source_rows",
                    "sqlite_citation_rows",
                )
            },
            **{
                name: distribution
                for name in (
                    "acquire_snapshot",
                    "prepare_index",
                    "read_ids",
                    "revalidate",
                )
            },
            "process": {
                name: 1
                for name in (
                    "user_cpu_ms",
                    "system_cpu_ms",
                    "elapsed_wall_ms",
                    "cpu_percent",
                    "maximum_rss_kib",
                )
            },
        }
        (self.evidence / "sqlite-capacity.json").write_text(json.dumps(measurement))
        (self.evidence / "sqlite-capacity.command.json").write_text(
            json.dumps(
                full.commands(candidate["commit"], self.evidence)["sqlite-capacity"]
            )
        )
        (self.evidence / "sqlite-capacity.log").write_text("")
        (self.evidence / "sqlite-capacity.exit-code").write_text("0")
        lock = self.evidence / "codex-rs/Cargo.lock"
        lock.parent.mkdir()
        lock.write_text("lock fixture")
        (self.evidence / "toolchain.txt").write_text("fixture")
        (self.evidence / "test-runner.log").write_text("fixture")
        policy = self.evidence / "docs/modules/cognitive.read/CONSUMER_EXECUTION.json"
        policy.parent.mkdir(parents=True)
        policy.write_text(
            json.dumps(
                {"schema": "fixture", "consumers": [], "claim_boundary": "deny_all"}
            )
        )
        output = self.evidence / "receipt.json"

        def base_emit(*args) -> bool:
            output.write_text(
                json.dumps({"candidate": candidate, "problems": [], "passed": True})
            )
            return True

        with patch.object(full, "_original_emit", side_effect=base_emit):
            self.assertFalse(
                full.emit(
                    self.evidence,
                    self.evidence,
                    candidate["commit"],
                    "source-head",
                    output,
                )
            )
        receipt = json.loads(output.read_text())
        self.assertFalse(receipt["passed"])
        self.assertFalse(receipt["sqlite_capacity"]["passed"])


if __name__ == "__main__":
    unittest.main()
