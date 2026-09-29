"""Synthetic command logs exercise evidence binding; no native tests are run."""
import json
from pathlib import Path
import tempfile
import unittest

from platform_types_consumer_evidence import EXPECTED_CHECKS, TEST_CHECKS, collect_checks


class ConsumerEvidenceTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.evidence = Path(temporary.name)
        (self.evidence / "results.tsv").write_text("".join(f"{name}\t0\t0\n" for name in EXPECTED_CHECKS))
        for name in EXPECTED_CHECKS:
            (self.evidence / (name + ".log")).write_text(
                "test result: ok. 2 passed; 0 failed; 0 ignored;\n" if name in TEST_CHECKS else "success\n")
            if name in TEST_CHECKS:
                (self.evidence / (name + "-count.json")).write_text('{"executedTests":2}\n')

    def test_complete_evidence_binds_test_counts(self):
        checks, errors = collect_checks(self.evidence)
        self.assertEqual(errors, [])
        self.assertEqual(tuple(row["name"] for row in checks), EXPECTED_CHECKS)
        tests = [row for row in checks if row["name"] in TEST_CHECKS]
        self.assertEqual(len(tests), 8)
        self.assertTrue(all(row["executedTests"] == 2 and len(row["testCountSha256"]) == 64 for row in tests))

    def test_missing_duplicate_or_reordered_commands_reject(self):
        path = self.evidence / "results.tsv"
        original = path.read_text().splitlines()
        for rows in (original[:-1], original[1:] + [original[1]], list(reversed(original))):
            path.write_text("\n".join(rows) + "\n")
            with self.subTest(rows=rows):
                self.assertTrue(collect_checks(self.evidence)[1])

    def test_count_is_recomputed_instead_of_trusted(self):
        path = self.evidence / "topology-consumer-count.json"
        for value in ({"executedTests": 3}, {"executedTests": True}, {}, {"executedTests": 2, "extra": 1}):
            path.write_text(json.dumps(value))
            with self.subTest(value=value):
                self.assertTrue(collect_checks(self.evidence)[1])

    def test_zero_test_log_rejects_even_with_success_exit_and_stale_count(self):
        (self.evidence / "topology-consumer.log").write_text("test result: ok. 0 passed; 0 failed; 0 ignored;\n")
        self.assertTrue(collect_checks(self.evidence)[1])

    def test_missing_count_or_log_rejects(self):
        (self.evidence / "topology-consumer-count.json").unlink()
        self.assertTrue(collect_checks(self.evidence)[1])
        (self.evidence / "canonical-python.log").unlink()
        self.assertTrue(collect_checks(self.evidence)[1])

    def test_failed_step_keeps_later_diagnostics(self):
        path = self.evidence / "results.tsv"
        path.write_text(path.read_text().replace("consumer-compile\t0\t0", "consumer-compile\t19\t0"))
        checks, errors = collect_checks(self.evidence)
        self.assertEqual(errors, [])
        self.assertEqual(len(checks), 24)
        self.assertEqual(next(row for row in checks if row["name"] == "consumer-compile")["exitCode"], 19)
        self.assertEqual(checks[-1]["name"], "ndu-lint")


if __name__ == "__main__":
    unittest.main()
