"""Tests for inference.control lane-result classification."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

SCRIPT = Path(__file__).with_name("hepta-inference-control-classify.py").resolve()
SPEC = importlib.util.spec_from_file_location("hepta_inference_control_classify", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)

SOURCE = "1" * 40
TESTED = "2" * 40


class LaneClassificationTests(unittest.TestCase):
    def setUp(self) -> None:
        directory = tempfile.TemporaryDirectory(prefix="hepta-inference-classify-")
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.records = self.root / "lane" / "commands"
        self.evidence = self.root / "lane" / "evidence"
        self.records.mkdir(parents=True)
        self.evidence.mkdir(parents=True)
        self.setup = self.root / "lane" / "setup.json"
        self.output = self.evidence / "classification.json"
        self.write_setup(toolchain_ready=True)

    def write_setup(self, *, toolchain_ready: bool) -> None:
        self.setup.write_text(
            json.dumps(
                {
                    "schema": "hepta.inference-control-lane-setup.v1",
                    "lane": "base-merge",
                    "sourceSha": SOURCE,
                    "checkoutBound": True,
                    "toolchainReady": toolchain_ready,
                }
            ),
            encoding="utf-8",
        )

    def write_record(
        self,
        name: str,
        *,
        status: str = "passed",
        exit_code: int = 0,
    ) -> None:
        (self.records / name).write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "lane": "base-merge",
                    "source_sha": SOURCE,
                    "tested_sha": TESTED,
                    "status": status,
                    "exit_code": exit_code,
                }
            ),
            encoding="utf-8",
        )

    def classify(self, expected: list[str]):
        return MODULE.classify(
            records_dir=self.records,
            setup_marker=self.setup,
            output=self.output,
            expected=expected,
            lane="base-merge",
            source_sha=SOURCE,
            tested_sha=TESTED,
        )

    def test_complete_exact_record_set_passes(self) -> None:
        self.write_record("00.json")
        self.write_record("01.json")
        result = self.classify(["00.json", "01.json"])
        self.assertEqual(result["classification"], "passed")
        self.assertEqual(result["missingRecords"], [])
        self.assertEqual(result["malformedRecords"], [])
        self.assertEqual(
            json.loads(self.output.read_text(encoding="utf-8"))["classification"],
            "passed",
        )

    def test_real_command_failure_is_source_failed_even_when_later_record_is_missing(self) -> None:
        self.write_record("00.json", status="failed", exit_code=9)
        result = self.classify(["00.json", "01.json"])
        self.assertEqual(result["classification"], "source_failed")
        self.assertEqual(result["missingRecords"], ["01.json"])
        self.assertEqual(result["failedRecords"][0]["name"], "00.json")

    def test_missing_records_without_command_failure_are_infrastructure_invalid(self) -> None:
        self.write_record("00.json")
        result = self.classify(["00.json", "01.json"])
        self.assertEqual(result["classification"], "infrastructure_invalid")
        self.assertIn("expected_command_records_missing", result["reasonCodes"])

    def test_unready_toolchain_cannot_be_reported_as_source_failure_or_pass(self) -> None:
        self.write_setup(toolchain_ready=False)
        self.write_record("00.json")
        result = self.classify(["00.json"])
        self.assertEqual(result["classification"], "infrastructure_invalid")
        self.assertIn("toolchain_not_ready", result["reasonCodes"])

    def test_duplicate_or_ambiguous_record_is_infrastructure_invalid(self) -> None:
        (self.records / "00.json").write_text(
            '{"schema_version":1,"schema_version":1}', encoding="utf-8"
        )
        result = self.classify(["00.json"])
        self.assertEqual(result["classification"], "infrastructure_invalid")
        self.assertEqual(result["malformedRecords"][0]["name"], "00.json")


if __name__ == "__main__":
    unittest.main()
