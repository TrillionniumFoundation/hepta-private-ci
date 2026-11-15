"""Selection rejection controls; these synthetic reports are not native evidence."""

from __future__ import annotations

from pathlib import Path
import unittest
from unittest.mock import patch
import xml.etree.ElementTree as ET

import hepta_windows_learn_regressions as runner


class ExactNativeCoverageTests(unittest.TestCase):
    def setUp(self):
        self.groups = runner.expected_groups()
        self.identities = [case for group in self.groups.values() for case in group]

    def log(self, rows):
        passed = sum(status == "PASS" for status, _, _ in rows)
        failed = sum(status not in ("PASS", "SKIP") for status, _, _ in rows)
        skipped = sum(status == "SKIP" for status, _, _ in rows)
        return "\n".join(
            [
                f"Starting {len(rows)} tests across 3 binaries",
                *[
                    f"    {status} [   0.001s] {package} {name}"
                    for status, package, name in rows
                ],
                f"Summary [ 1.000s] {len(rows)} tests run: "
                f"{passed} passed, {failed} failed, {skipped} skipped",
            ]
        )

    def xml(self, names=None, negative=None):
        root = ET.Element("testsuites")
        suites = {}
        if names is None:
            names = [name for _, name in self.identities]
        for index, name in enumerate(names):
            package = self.identities[index][0]
            suite = suites.get(package)
            if suite is None:
                suite = ET.SubElement(root, "testsuite", name=package)
                suites[package] = suite
            case = ET.SubElement(suite, "testcase", name=name, classname=package)
            if index == 0 and negative:
                ET.SubElement(case, negative)
        return ET.tostring(root)

    def test_complete_exact_reports_keep_each_group_independent(self):
        rows = [("PASS", package, name) for package, name in self.identities]
        log = runner.assess_log(self.log(rows), self.groups)
        junit = runner.assess_junit(self.xml(), self.groups)
        self.assertTrue(log["exact_pass_coverage"])
        self.assertTrue(junit["exact_pass_coverage"])
        for group, cases in self.groups.items():
            self.assertEqual(log["groups"][group]["observed_pass_rows"], len(cases))
            self.assertTrue(log["groups"][group]["exact_pass_coverage"])
            self.assertTrue(junit["groups"][group]["exact_pass_coverage"])
        changed = rows.copy()
        changed[-1] = ("FAIL", *changed[-1][1:])
        failed = runner.assess_log(self.log(changed), self.groups)
        self.assertFalse(failed["exact_pass_coverage"])
        self.assertTrue(failed["groups"]["original_windows_21"]["exact_pass_coverage"])
        self.assertFalse(
            failed["groups"]["dataset_materialization"]["exact_pass_coverage"]
        )

    def test_missing_duplicate_foreign_package_and_extra_rows_reject(self):
        rows = [("PASS", package, name) for package, name in self.identities]
        altered = {
            "missing": rows[:-1],
            "duplicate": rows[:-1] + [rows[0]],
            "foreign-package": [("PASS", "foreign-package", rows[0][2])] + rows[1:],
            "extra": rows + [("PASS", "foreign-package", "foreign-test")],
            "empty": [],
        }
        for name, observed in altered.items():
            with self.subTest(name=name):
                self.assertFalse(
                    runner.assess_log(self.log(observed), self.groups)[
                        "exact_pass_coverage"
                    ]
                )

    def test_skips_errors_and_repeated_attempts_never_count_as_passes(self):
        rows = [("PASS", package, name) for package, name in self.identities]
        for status in ("SKIP", "FAIL", "TIMEOUT", "EXECFAIL", "LEAK"):
            with self.subTest(status=status):
                altered = [(status, *rows[0][1:])] + rows[1:]
                self.assertFalse(
                    runner.assess_log(self.log(altered), self.groups)[
                        "exact_pass_coverage"
                    ]
                )
        self.assertFalse(
            runner.assess_log(self.log(rows + [rows[0]]), self.groups)[
                "exact_pass_coverage"
            ]
        )

    def test_same_count_junit_substitution_duplicate_and_nonpass_nodes_reject(self):
        names = [name for _, name in self.identities]
        for altered in (
            ["foreign-test"] + names[1:],
            [names[1]] + names[1:],
            names[:-1],
        ):
            self.assertFalse(
                runner.assess_junit(self.xml(altered), self.groups)[
                    "exact_pass_coverage"
                ]
            )
        for negative in ("skipped", "failure", "error", "rerunFailure", "flakyFailure"):
            with self.subTest(negative=negative):
                self.assertFalse(
                    runner.assess_junit(self.xml(negative=negative), self.groups)[
                        "exact_pass_coverage"
                    ]
                )

    def test_same_names_and_count_require_native_package_and_suite_identity(self):
        for change in (
            "foreign-classname",
            "missing-classname",
            "foreign-suite",
            "missing-suite",
            "duplicate-suite",
            "unowned-testcase",
        ):
            with self.subTest(change=change):
                root = ET.fromstring(self.xml())
                suite = root.find("testsuite")
                case = suite.find("testcase")
                if change == "foreign-classname":
                    case.set("classname", "foreign-package")
                elif change == "missing-classname":
                    del case.attrib["classname"]
                elif change == "foreign-suite":
                    suite.set("name", "foreign-package")
                elif change == "missing-suite":
                    del suite.attrib["name"]
                elif change == "duplicate-suite":
                    ET.SubElement(root, "testsuite", name=suite.get("name"))
                else:
                    suite.remove(case)
                    root.append(case)
                report = runner.assess_junit(ET.tostring(root), self.groups)
                self.assertEqual(report["total_testcases"], len(self.identities))
                self.assertFalse(report["exact_pass_coverage"])

    def test_non_windows_host_cannot_dispatch_or_issue_native_result(self):
        output = Path("must-not-be-created")
        with (
            patch.object(runner.sys, "platform", "linux"),
            patch.object(runner.os, "name", "posix"),
            patch.object(runner.subprocess, "run") as invoke,
        ):
            with self.assertRaisesRegex(ValueError, "native Windows is required"):
                runner.run("a" * 40, output)
            invoke.assert_not_called()


if __name__ == "__main__":
    unittest.main()
