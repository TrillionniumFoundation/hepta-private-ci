"""Synthetic report-validator controls, never native qualification tests."""

import copy
from pathlib import Path
import tempfile
import unittest
import xml.etree.ElementTree as ET

from native_fixture_evidence import EXPECTED, validate_report


class ReportValidationTests(unittest.TestCase):
    def setUp(self):
        self.root = ET.Element(
            "testsuites", name="native-fixtures", tests="2", failures="0", errors="0"
        )
        for binary, name in sorted(EXPECTED):
            suite = ET.SubElement(
                self.root,
                "testsuite",
                name=binary,
                tests="1",
                failures="0",
                errors="0",
                disabled="0",
            )
            ET.SubElement(
                suite,
                "testcase",
                name=name,
                classname=binary,
                timestamp="2026-10-24T00:00:00Z",
            )

    def check(self, root):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "report.xml"
            ET.ElementTree(root).write(path)
            return validate_report(path)

    def test_absent_root_skipped_attribute_is_valid(self):
        self.assertEqual(set(self.check(self.root)), EXPECTED)

    def test_zero_missing_duplicate_or_unexpected_is_refused(self):
        for mutation in ("zero", "missing", "duplicate", "unexpected"):
            with self.subTest(mutation=mutation):
                root = copy.deepcopy(self.root)
                first, second = root.findall("testsuite/testcase")
                if mutation == "zero":
                    root.clear()
                elif mutation == "missing":
                    root.remove(root.findall("testsuite")[1])
                elif mutation == "duplicate":
                    second.attrib.update(first.attrib)
                else:
                    first.set("name", "another_test")
                with self.assertRaises(ValueError):
                    self.check(root)

    def test_failure_skip_retry_and_unknown_child_are_refused(self):
        for tag in (
            "failure",
            "error",
            "skipped",
            "flakyFailure",
            "flakyError",
            "rerunFailure",
            "rerunError",
            "unknown",
        ):
            with self.subTest(tag=tag):
                root = copy.deepcopy(self.root)
                ET.SubElement(root.find("testsuite/testcase"), tag)
                with self.assertRaises(ValueError):
                    self.check(root)

    def test_missing_counters_and_unexpected_nested_results_are_refused(self):
        for key in ("tests", "failures", "errors"):
            root = copy.deepcopy(self.root)
            del root.attrib[key]
            with self.assertRaises(ValueError):
                self.check(root)
        for node in (".", "testsuite"):
            root = copy.deepcopy(self.root)
            ET.SubElement(root.find(node), "unexpected")
            with self.assertRaises(ValueError):
                self.check(root)

    def test_count_identity_and_execution_tampering_is_refused(self):
        for attribute, value in (
            ("tests", "0"),
            ("failures", "1"),
            ("errors", "1"),
            ("skipped", "1"),
            ("disabled", "1"),
        ):
            with self.subTest(attribute=attribute):
                root = copy.deepcopy(self.root)
                root.set(attribute, value)
                with self.assertRaises(ValueError):
                    self.check(root)
        for node, attribute in (
            ("testsuite", "name"),
            ("testsuite/testcase", "timestamp"),
        ):
            root = copy.deepcopy(self.root)
            del root.find(node).attrib[attribute]
            with self.assertRaises(ValueError):
                self.check(root)


if __name__ == "__main__":
    unittest.main()
