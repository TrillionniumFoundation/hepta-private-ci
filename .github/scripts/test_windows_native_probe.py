"""Negative observation controls; these are not Windows/native evidence."""

import json
from pathlib import Path
import tempfile
import time
import unittest

import windows_current_ci
import windows_native_probe as probe


class ObservationControls(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.path = Path(self.temporary.name) / "junit.xml"
        self.root = Path(__file__).resolve().parents[2]
        self.group = {
            "id": "operator-native",
            "package": "operator",
            "expectedTestCount": 2,
            "requiredTests": ["exact", "denied"],
        }

    def collect(self, body, *, started=None):
        self.path.write_text("<testsuite>" + body + "</testsuite>", encoding="utf-8")
        return probe.retain_junit(
            self.root,
            self.path,
            self.group,
            started if started is not None else time.time() - 5,
            time.time() + 5,
        )

    def test_native_failure_and_skip_are_retained_not_passed(self):
        for marker, field in (
            ("failure", "failures"),
            ("error", "failures"),
            ("skipped", "skipped"),
        ):
            with self.subTest(marker=marker):
                result = self.collect(
                    f'<testcase name="exact"><{marker}/></testcase><testcase name="denied"/>'
                )
                self.assertFalse(result["passed"])
                self.assertEqual(result[field], 1)

    def test_empty_missing_duplicate_and_extra_selection_are_rejected(self):
        for body in (
            "",
            '<testcase name="exact"/>',
            '<testcase name="exact"/><testcase name="exact"/>',
            '<testcase name="exact"/><testcase name="other"/>',
            '<testcase name="exact"/><testcase name="denied"/><testcase name="extra"/>',
        ):
            with self.subTest(body=body), self.assertRaises(ValueError):
                self.collect(body)

    def test_stale_junit_cannot_bind_to_a_new_execution(self):
        with self.assertRaises(ValueError):
            self.collect(
                '<testcase name="exact"/><testcase name="denied"/>',
                started=time.time() + 60,
            )

    def test_doctype_is_rejected_by_the_original_parser(self):
        self.path.write_bytes(
            b'<?xml version="1.0" encoding="UTF-16"?>\n'.decode().encode("utf-16")
            + "<!DOCTYPE testsuite><testsuite/>".encode("utf-16-le")
        )
        with self.assertRaises(ValueError):
            probe.retain_junit(
                self.root, self.path, self.group, time.time() - 5, time.time() + 5
            )

    def test_failed_child_never_becomes_passed_with_successful_text(self):
        log = "Starting 2 tests across 1 binaries\nPASS [0.1s] operator exact\nPASS [0.1s] operator denied\n"
        self.assertFalse(windows_current_ci.assess(self.group, 1, log)["passed"])

    def test_report_creation_refuses_an_old_result(self):
        probe.write_json(self.path, {"status": "failed"})
        with self.assertRaises(FileExistsError):
            probe.write_json(self.path, {"status": "passed"})
        self.assertEqual(json.loads(self.path.read_text()), {"status": "failed"})


if __name__ == "__main__":
    unittest.main()
