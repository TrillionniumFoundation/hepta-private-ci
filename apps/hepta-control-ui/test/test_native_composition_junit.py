"""Synthetic JUnit/receipt rejection tests; these do not execute Rust or a UI."""

import copy
from datetime import datetime, timedelta, timezone
import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
import uuid
import xml.etree.ElementTree as ET

spec = importlib.util.spec_from_file_location(
    "composition_junit", Path(__file__).resolve().parents[1] / "tools/check-native-composition-junit.py")
guard = importlib.util.module_from_spec(spec)
spec.loader.exec_module(guard)


class JunitGateTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.start = datetime.now(timezone.utc)
        self.end = self.start + timedelta(seconds=2)

    def xml(self, mode="native"):
        names = sorted(guard.MODES[mode]) + ["presentation::tests::existing_unfiltered_test"]
        root = ET.Element("testsuites", name="hepta-native-composition-" + mode,
                          tests=str(len(names)), errors="0", failures="0", uuid=str(uuid.uuid4()),
                          timestamp=self.start.isoformat())
        suite = ET.SubElement(root, "testsuite", name=guard.PACKAGE, tests=str(len(names)),
                              errors="0", failures="0", disabled="0")
        for name in names:
            ET.SubElement(suite, "testcase", name=name, classname=guard.PACKAGE,
                          time="0.001", timestamp=(self.start + timedelta(milliseconds=10)).isoformat())
        return root

    def check(self, xml, mode="native"):
        return guard.check_xml(ET.tostring(xml), mode, self.start, self.end, len(guard.MODES[mode]) + 1)

    def bundle(self):
        junit = self.root / "junit.xml"
        start = self.root / "start.json"
        guard.prepare(start, junit, "native", "a" * 40)
        self.start = datetime.now(timezone.utc)
        self.end = self.start + timedelta(seconds=2)
        junit.write_bytes(ET.tostring(self.xml()))
        log = b"synthetic original execution log for gate tests only\n"
        (self.root / "execution.log").write_bytes(log)
        identity = {"commit": "a" * 40, "tree": "b" * 40, "dirty": False, "parents": []}
        receipt = {"status": "passed", "exit_code": 0, "command_exit_code": 0, "returncode": 0,
                   "timed_out": False, "output_limit_exceeded": False, "observed_failed_tests": 0,
                   "observed_passed_tests": 9, "command": guard.command("native"),
                   "before": identity, "after": copy.deepcopy(identity), "tested_sha": "a" * 40,
                   "started_at": self.start.isoformat(), "finished_at": self.end.isoformat(),
                   "log_file": "execution.log", "log_bytes": len(log),
                   "log_sha256": hashlib.sha256(log).hexdigest()}
        execution = self.root / "execution.json"
        execution.write_text(json.dumps(receipt))
        return start, execution, self.root / "validation.json", receipt

    def test_both_exact_modes_allow_absent_root_skipped_and_keep_full_suite(self):
        for mode in guard.MODES:
            result = self.check(self.xml(mode), mode)
            self.assertEqual(result["required_passed_tests"], sorted(guard.MODES[mode]))
            self.assertEqual(result["total_passed_tests"], len(guard.MODES[mode]) + 1)

    def test_missing_name_is_not_replaced_by_another_test_with_same_prefix(self):
        xml = self.xml()
        xml.find("testsuite/testcase").set("name", sorted(guard.MODES["native"])[0] + "_replacement")
        with self.assertRaisesRegex(ValueError, "required composition tests missing"):
            self.check(xml)

    def test_duplicate_required_name_is_rejected(self):
        xml = self.xml()
        cases = xml.findall("testsuite/testcase")
        cases[1].set("name", cases[0].get("name"))
        with self.assertRaisesRegex(ValueError, "duplicate"):
            self.check(xml)

    def test_skipped_failed_error_or_retried_test_is_rejected(self):
        for tag in ["skipped", "failure", "error", "flakyFailure", "flakyError", "rerunFailure", "rerunError"]:
            with self.subTest(tag=tag):
                xml = self.xml()
                ET.SubElement(xml.find("testsuite/testcase"), tag)
                with self.assertRaisesRegex(ValueError, "unsuccessful"):
                    self.check(xml)

    def test_aggregate_counters_cannot_hide_skips_failures_or_missing_rows(self):
        for tag, name, value in [(None, "skipped", "1"), (None, "errors", "1"),
                                 (None, "tests", "99"), ("testsuite", "disabled", "1")]:
            with self.subTest(tag=tag, name=name):
                xml = self.xml()
                (xml if tag is None else xml.find(tag)).set(name, value)
                with self.assertRaises(ValueError):
                    self.check(xml)

    def test_wrong_mode_suite_or_class_cannot_substitute_for_original_library(self):
        for element, name, value in [(None, "name", "hepta-native-composition-headless"),
                                     ("testsuite", "name", "other-package"),
                                     ("testsuite/testcase", "classname", "other-package")]:
            xml = self.xml()
            (xml if element is None else xml.find(element)).set(name, value)
            with self.assertRaises(ValueError):
                self.check(xml)

    def test_stale_xml_timestamp_is_rejected_even_with_correct_test_names(self):
        xml = self.xml()
        xml.set("timestamp", (self.start - timedelta(days=1)).isoformat())
        with self.assertRaisesRegex(ValueError, "execution interval"):
            self.check(xml)

    def test_existing_report_or_reused_start_record_is_refused_before_dispatch(self):
        report = self.root / "report.xml"
        report.write_text("old report")
        with self.assertRaises(ValueError):
            guard.prepare(self.root / "start.json", report, "native", "a" * 40)
        report.unlink()
        guard.prepare(self.root / "start.json", report, "native", "a" * 40)
        with self.assertRaises(FileExistsError):
            guard.prepare(self.root / "start.json", report, "native", "a" * 40)

    def test_complete_synthetic_receipt_is_bound_and_raw_xml_is_retained(self):
        start, execution, output, _ = self.bundle()
        result = guard.verify(start, execution, output)
        self.assertEqual(result["status"], "passed")
        self.assertEqual(output.with_suffix(".xml").read_bytes(), (self.root / "junit.xml").read_bytes())

    def test_command_filter_or_source_drift_or_failed_command_is_rejected(self):
        start, execution, output, original = self.bundle()
        for mutation in ["filter", "source", "failure"]:
            receipt = copy.deepcopy(original)
            if mutation == "filter":
                receipt["command"] += ["-E", "test(presentation::tests::)"]
            elif mutation == "source":
                receipt["after"]["tree"] = "c" * 40
            else:
                receipt["command_exit_code"] = 101
            execution.write_text(json.dumps(receipt))
            with self.assertRaises(ValueError):
                guard.verify(start, execution, output)

    def test_missing_report_and_changed_execution_log_are_rejected(self):
        start, execution, output, _ = self.bundle()
        (self.root / "junit.xml").unlink()
        with self.assertRaisesRegex(ValueError, "JUnit missing"):
            guard.verify(start, execution, output)
        (self.root / "execution.log").write_text("changed")
        with self.assertRaisesRegex(ValueError, "execution log changed"):
            guard.verify(start, execution, output)

    def test_unknown_xml_entity_or_unbounded_report_is_rejected(self):
        for raw in [b'<!DOCTYPE testsuites><testsuites/>', b"x" * (guard.MAX_REPORT + 1)]:
            with self.assertRaises(ValueError):
                guard.check_xml(raw, "native", self.start, self.end, 9)


if __name__ == "__main__":
    unittest.main()
