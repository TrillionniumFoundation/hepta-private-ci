import gzip
from pathlib import Path
import unittest
import xml.etree.ElementTree as ET

from run_qualification import parse_reports
from run_qualification import parse_idle_reports
from run_qualification import IDLE_CASES


class OriginalReportAcceptance(unittest.TestCase):
    def inputs(self, target="git-utils-unit-tests"):
        root = Path(__file__).parent / "upstream-112c"
        return tuple(gzip.decompress((root / f"{target}-test.{suffix}.gz").read_bytes())
                     for suffix in ("log", "xml"))

    def changed_log(self, transform):
        log, raw = self.inputs()
        log = transform(log.decode()).encode()
        xml = ET.fromstring(raw)
        xml.find("testsuite/system-out").text = log.decode()
        return log, ET.tostring(xml)

    def test_original_two_complete_reports(self):
        for target, expected in (("git-utils-unit-tests", 33), ("queue-queue_service-test", 35)):
            with self.subTest(target=target):
                result = parse_reports(*self.inputs(target), target)
                self.assertEqual(result["outer_passed"], expected)
                self.assertEqual(result["outer_filtered"], 0)
                self.assertEqual(result["outer_ignored"], 0)

    def test_rejects_empty_wrapper(self):
        log, raw = self.inputs()
        xml = ET.fromstring(raw)
        suite = xml.find("testsuite")
        suite.remove(suite.find("testcase"))
        with self.assertRaises(RuntimeError):
            parse_reports(log, ET.tostring(xml), "git-utils-unit-tests")

    def test_rejects_skipped_or_failed_wrapper(self):
        log, raw = self.inputs()
        for tag in ("failure", "error", "skipped"):
            with self.subTest(tag=tag):
                xml = ET.fromstring(raw)
                ET.SubElement(xml.find("testsuite/testcase"), tag)
                with self.assertRaises(RuntimeError):
                    parse_reports(log, ET.tostring(xml), "git-utils-unit-tests")

    def test_rejects_zero_native_result(self):
        changed = self.changed_log(lambda value: value.replace(
            "33 passed; 0 failed; 0 ignored; 0 measured; 0 filtered out;",
            "0 passed; 0 failed; 0 ignored; 0 measured; 0 filtered out;"))
        with self.assertRaises(RuntimeError):
            parse_reports(*changed, "git-utils-unit-tests")

    def test_rejects_parent_filtering(self):
        changed = self.changed_log(lambda value: value.replace(
            "33 passed; 0 failed; 0 ignored; 0 measured; 0 filtered out;",
            "33 passed; 0 failed; 0 ignored; 0 measured; 1 filtered out;"))
        with self.assertRaises(RuntimeError):
            parse_reports(*changed, "git-utils-unit-tests")

    def test_rejects_different_nested_subprocess(self):
        changed = self.changed_log(lambda value: value.replace("32 filtered out;", "31 filtered out;"))
        with self.assertRaises(RuntimeError):
            parse_reports(*changed, "git-utils-unit-tests")

    def test_rejects_missing_original_lifecycle_case(self):
        changed = self.changed_log(lambda value: value.replace(
            "git_process::tests::timed_out_exited_git_wrapper_does_not_leave_child_process_running",
            "unrelated_test_with_same_count"))
        with self.assertRaises(RuntimeError):
            parse_reports(*changed, "git-utils-unit-tests")

    def test_rejects_mismatched_raw_report(self):
        log, raw = self.inputs()
        with self.assertRaises(RuntimeError):
            parse_reports(log + b"different output", raw, "git-utils-unit-tests")

    def test_rejects_duplicate_wrappers(self):
        log, raw = self.inputs()
        xml = ET.fromstring(raw)
        xml.append(ET.fromstring(ET.tostring(xml.find("testsuite"))))
        with self.assertRaises(RuntimeError):
            parse_reports(log, ET.tostring(xml), "git-utils-unit-tests")


if __name__ == "__main__":
    unittest.main()

class DeferredIdleReportAcceptance(unittest.TestCase):
    def reports(self, names=None, summary=None):
        names = sorted(IDLE_CASES) if names is None else names
        summary = summary or "test result: ok. 3 passed; 0 failed; 0 ignored; 0 measured; 100 filtered out;"
        log = "\n".join([*(f"test {name} ... ok" for name in names), summary]) + "\n"
        root = ET.Element("testsuites")
        suite = ET.SubElement(root, "testsuite", tests="1", failures="0", errors="0")
        ET.SubElement(suite, "testcase", name="core-unit-tests")
        ET.SubElement(suite, "system-out").text = log
        return log.encode(), ET.tostring(root)

    def test_accepts_only_all_three_selected_controls(self):
        result = parse_idle_reports(*self.reports())
        self.assertEqual(result["passed"], 3)
        self.assertEqual(result["filtered_other_core_cases"], 100)

    def test_rejects_missing_or_duplicate_control(self):
        names = sorted(IDLE_CASES)
        with self.assertRaises(RuntimeError):
            parse_idle_reports(*self.reports(names=names[:-1]))
        with self.assertRaises(RuntimeError):
            parse_idle_reports(*self.reports(names=[names[0], names[0], names[2]]))

    def test_rejects_ignored_control(self):
        with self.assertRaises(RuntimeError):
            parse_idle_reports(*self.reports(
                summary="test result: ok. 2 passed; 0 failed; 1 ignored; 0 measured; 100 filtered out;"
            ))

    def test_rejects_stale_xml(self):
        log, xml = self.reports()
        with self.assertRaises(RuntimeError):
            parse_idle_reports(log + b"changed\n", xml)
