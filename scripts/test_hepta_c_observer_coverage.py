"""Positive and adversarial native Observer report coverage, without Rust work."""

import ast
import hashlib
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
import xml.etree.ElementTree as ET

import hepta_c_observer_coverage as coverage


class OriginalObserverCoverageTests(unittest.TestCase):
    def reports(self):
        root = ET.Element("testsuites")
        suite = ET.SubElement(root, "testsuite", name=coverage.PACKAGE)
        for name in coverage.CASES:
            ET.SubElement(suite, "testcase", name=name, classname=coverage.PACKAGE)
        ET.SubElement(
            suite,
            "testcase",
            name="unrelated::actual_native_test",
            classname=coverage.PACKAGE,
        )
        lines = [
            f"PASS [0.001s] ({index}/7) {coverage.PACKAGE} {name}"
            for index, name in enumerate(coverage.CASES, 1)
        ]
        lines.append(
            f"PASS [0.001s] (7/7) {coverage.PACKAGE} unrelated::actual_native_test"
        )
        lines.append("Summary [0.007s] 7 tests run: 7 passed, 0 skipped")
        return root, "\n".join(lines)

    def assess(self, root, log):
        return coverage.assess_original_observer_coverage(log, ET.tostring(root))[
            "exact_pass_coverage"
        ]

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
                ET.SubElement(
                    suite,
                    "testcase",
                    name=coverage.CASES[0],
                    classname=coverage.PACKAGE,
                )
            else:
                suite.remove(suite[0])
            self.assertFalse(self.assess(root, log))

    def test_same_names_require_native_package_and_suite_identity(self):
        for attribute, value in (
            ("classname", "foreign-package"),
            ("classname", None),
            ("suite", "foreign-package"),
        ):
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
            parent = (
                ET.SubElement(suite, "testsuite", name=coverage.PACKAGE)
                if nested
                else root
            )
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

    def retained(self, directory):
        root, log = self.reports()
        record_path = directory / "ordinary.json"
        xml_path = directory / "ordinary.xml"
        name = record_path.name + "." + "a" * 32 + ".log"
        raw = log.encode()
        record = {
            "status": "passed",
            "returncode": 0,
            "command_exit_code": 0,
            "exit_code": 0,
            "timed_out": False,
            "output_limit_exceeded": False,
            "log_file": name,
            "log_bytes": len(raw),
            "log_sha256": hashlib.sha256(raw).hexdigest(),
        }
        (directory / name).write_bytes(raw)
        record_path.write_text(json.dumps(record))
        xml_path.write_bytes(ET.tostring(root))
        return record_path, xml_path, record

    def test_retained_execution_uses_exact_original_log_identity(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            record_path, xml_path, record = self.retained(directory)
            self.assertFalse((directory / "ordinary.log").exists())
            result = coverage.assess_retained_original_observer_coverage(
                record_path, xml_path
            )
            self.assertTrue(result["exact_pass_coverage"])
            self.assertEqual(result["log_file"], record["log_file"])
            self.assertEqual(result["log_bytes"], record["log_bytes"])
            self.assertEqual(result["log_sha256"], record["log_sha256"])

    def test_retained_log_aliases_and_path_escape_are_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            record_path, xml_path, record = self.retained(directory)
            for name in (
                "ordinary.log",
                "../" + record["log_file"],
                str(directory / record["log_file"]),
                "elsewhere.json." + "a" * 32 + ".log",
                "subdir\\\\ordinary.json." + "a" * 32 + ".log",
            ):
                with self.subTest(name=name):
                    record_path.write_text(json.dumps({**record, "log_file": name}))
                    with self.assertRaises(ValueError):
                        coverage.assess_retained_original_observer_coverage(
                            record_path, xml_path
                        )

    def test_retained_raw_bytes_cannot_be_changed_truncated_or_extended(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            record_path, xml_path, record = self.retained(directory)
            log_path = directory / record["log_file"]
            raw = log_path.read_bytes()
            for changed in (raw.replace(b"PASS", b"FAIL", 1), raw[:-1], raw + b"\n"):
                with self.subTest(size=len(changed)):
                    log_path.write_bytes(changed)
                    with self.assertRaises(ValueError):
                        coverage.assess_retained_original_observer_coverage(
                            record_path, xml_path
                        )

    def test_retained_execution_refuses_failed_records_bad_identity_and_symlinks(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            record_path, xml_path, record = self.retained(directory)
            for key, value in (
                ("status", "failed"),
                ("exit_code", 1),
                ("returncode", True),
                ("command_exit_code", None),
                ("timed_out", True),
                ("output_limit_exceeded", True),
                ("log_bytes", -1),
                ("log_bytes", 64 * 1024 * 1024 + 1),
                ("log_sha256", "0" * 64),
                ("log_sha256", None),
            ):
                with self.subTest(field=key, value=value):
                    record_path.write_text(json.dumps({**record, key: value}))
                    with self.assertRaises(ValueError):
                        coverage.assess_retained_original_observer_coverage(
                            record_path, xml_path
                        )
            record_path.write_text(json.dumps(record))
            log_path = directory / record["log_file"]
            actual = directory / "actual.log"
            log_path.rename(actual)
            log_path.symlink_to(actual)
            with self.assertRaises(ValueError):
                coverage.assess_retained_original_observer_coverage(
                    record_path, xml_path
                )

    def test_actual_workflow_ordinary_report_wiring_reads_recorded_log(self):
        workflow = (
            Path(__file__).resolve().parents[1]
            / ".github/workflows/hepta-daemon-learning-native.yml"
        )
        text = workflow.read_text()
        start = text.index("          import base64\n")
        end = text.index("          PY\n", start)
        driver = "\n".join(line[10:] for line in text[start:end].splitlines())
        method = next(
            node
            for node in ast.parse(driver).body
            if isinstance(node, ast.FunctionDef) and node.name == "test"
        )
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            self.retained(directory)
            saved = {}
            namespace = {
                "repo": directory / "source",
                "records": directory,
                "os": SimpleNamespace(
                    geteuid=lambda: 1000, environ={"SOURCE_SHA": "b" * 40}
                ),
                "subprocess": SimpleNamespace(
                    run=lambda *args, **kwargs: SimpleNamespace(returncode=0)
                ),
                "collect": lambda *args: 0,
                "save": lambda name, value: saved.update({name: value}),
                "assess_retained_original_observer_coverage": coverage.assess_retained_original_observer_coverage,
            }
            exec(
                compile(
                    ast.Module(body=[method], type_ignores=[]), str(workflow), "exec"
                ),
                namespace,
            )
            namespace["test"]("ordinary", ["--lib"])
            self.assertTrue(
                saved["original-c-observer-coverage.json"]["exact_pass_coverage"]
            )
            self.assertFalse((directory / "ordinary.log").exists())


if __name__ == "__main__":
    unittest.main()
