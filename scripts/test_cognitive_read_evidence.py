import json
from pathlib import Path
import tempfile
import unittest

from cognitive_read_evidence import BENCHMARK_SCHEMAS, TEST_GATES, commands, validate_evidence


class EvidenceGateTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.evidence = Path(self.temporary.name)
        self.required = commands("a" * 40, self.evidence)
        for label, argv in self.required.items():
            (self.evidence / f"{label}.command.json").write_text(json.dumps(argv))
            (self.evidence / f"{label}.log").write_text("Summary [0.1s] 1 test run: 1 passed, 0 skipped\n")
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


if __name__ == "__main__":
    unittest.main()
