"""Positive and adversarial native Observer report coverage, without Rust work."""

import unittest
import xml.etree.ElementTree as ET

import hepta_c_observer_coverage as coverage


class OriginalObserverCoverageTests(unittest.TestCase):
    def reports(self):
        root = ET.Element("testsuites")
        suite = ET.SubElement(root, "testsuite", name=coverage.PACKAGE)
        for name in coverage.CASES:
            ET.SubElement(suite, "testcase", name=name, classname=coverage.PACKAGE)
        ET.SubElement(suite, "testcase", name="unrelated::actual_native_test", classname=coverage.PACKAGE)
        lines = [
            f"PASS [0.001s] ({index}/7) {coverage.PACKAGE} {name}"
            for index, name in enumerate(coverage.CASES, 1)
        ]
        lines.append(f"PASS [0.001s] (7/7) {coverage.PACKAGE} unrelated::actual_native_test")
        lines.append("Summary [0.007s] 7 tests run: 7 passed, 0 skipped")
        return root, "\n".join(lines)

    def assess(self, root, log):
        return coverage.assess_original_observer_coverage(log, ET.tostring(root))["exact_pass_coverage"]

    def test_exact_subset_retains_other_native_cases(self):
        root, log = self.reports()
        self.assertTrue(self.assess(root, log))
        # --success-output final repeats native status headers after Summary.
        final_headers = "\n".join(log.splitlines()[:-1])
        self.assertTrue(self.assess(root, log + "\n" + final_headers))

    def test_missing_and_duplicate_required_cases_reject(self):
        for duplicate in (False, True):
            root, log = self.reports()
            suite = root.find("testsuite")
            assert suite is not None
            if duplicate:
                ET.SubElement(suite, "testcase", name=coverage.CASES[0], classname=coverage.PACKAGE)
            else:
                suite.remove(suite[0])
            self.assertFalse(self.assess(root, log))

    def test_same_names_require_native_package_and_suite_identity(self):
        for attribute, value in (("classname", "foreign-package"), ("classname", None), ("suite", "foreign-package")):
            root, log = self.reports()
            suite = root.find("testsuite")
            assert suite is not None
            if attribute == "suite":
                suite.set("name", value)
            elif value is None:
                del suite[0].attrib[attribute]
            else:
                suite[0].set(attribute, value)
            self.assertFalse(self.assess(root, log))

    def test_nested_and_orphan_cases_cannot_supply_coverage(self):
        for nested in (True, False):
            root, log = self.reports()
            suite = root.find("testsuite")
            assert suite is not None
            case = suite[0]
            suite.remove(case)
            parent = ET.SubElement(suite, "testsuite", name=coverage.PACKAGE) if nested else root
            parent.append(case)
            self.assertFalse(self.assess(root, log))

    def test_skipped_failed_and_errored_cases_are_not_passes(self):
        for status in ("skipped", "failure", "error"):
            root, log = self.reports()
            ET.SubElement(root.find("testsuite")[0], status)
            self.assertFalse(self.assess(root, log))

    def test_raw_log_missing_substituted_duplicate_and_failed_rows_reject(self):
        root, log = self.reports()
        lines = log.splitlines()
        for changed in (
            "\n".join(lines[1:]),
            log.replace(coverage.PACKAGE, "foreign-package"),
            log.replace("Summary", lines[0] + "\nSummary", 1),
            log.replace("Summary [0.007s]", "missing native summary"),
            log.replace("PASS", "FAIL", 1),
        ):
            self.assertFalse(self.assess(root, changed))


if __name__ == "__main__":
    unittest.main()
