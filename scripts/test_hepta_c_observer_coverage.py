"""Positive and adversarial original-owner report coverage, without Rust work."""

import ast
import base64
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile
from types import SimpleNamespace
import unittest
import xml.etree.ElementTree as ET

import hepta_c_observer_coverage as coverage


class OriginalObserverCoverageTests(unittest.TestCase):
    def reports(self):
        root = ET.Element("testsuites")
        suites = {}
        for package, name in coverage.EXPECTED_CASES:
            if package not in suites:
                suites[package] = ET.SubElement(root, "testsuite", name=package)
            ET.SubElement(suites[package], "testcase", name=name, classname=package)
        ET.SubElement(
            suites[coverage.PACKAGE],
            "testcase",
            name="unrelated::actual_native_test",
            classname=coverage.PACKAGE,
        )
        total = len(coverage.EXPECTED_CASES) + 1
        lines = [
            f"PASS [0.001s] ({index}/{total}) {package} {name}"
            for index, (package, name) in enumerate(coverage.EXPECTED_CASES, 1)
        ]
        lines.append(
            f"PASS [0.001s] ({total}/{total}) {coverage.PACKAGE} unrelated::actual_native_test"
        )
        lines.append(f"Summary [0.007s] {total} tests run: {total} passed, 0 skipped")
        return root, "\n".join(lines)

    def assess(self, root, log):
        return coverage.assess_original_observer_coverage(log, ET.tostring(root))[
            "exact_pass_coverage"
        ]

    def provider_native_cases(self):
        source = (
            Path(__file__).resolve().parents[1]
            / "codex-rs/hepta-agentd/src/circuit_original_evaluation_provider_tests.rs"
        ).read_text()
        names = re.findall(
            r"(?m)^#\[tokio::test(?:\([^\n]*\))?\]\n"
            r"async fn (original_evaluation_provider_\w+)\(",
            source,
        )
        self.assertTrue(names, "no registered native Provider tests found")
        return tuple(
            coverage.ORIGINAL_EVALUATION_PROVIDER_PREFIX + name for name in names
        )

    def test_exact_subset_retains_other_native_cases(self):
        root, log = self.reports()
        self.assertTrue(self.assess(root, log))
        # --success-output final repeats native status headers after Summary.
        final_headers = "\n".join(log.splitlines()[:-1])
        self.assertTrue(self.assess(root, log + "\n" + final_headers))

    def test_provider_catalog_tracks_registered_native_tests(self):
        # Compare independently maintained producer entry points and report
        # obligations, not fixtures generated from the catalog itself.
        self.assertCountEqual(
            coverage.ORIGINAL_EVALUATION_PROVIDER_CASES, self.provider_native_cases()
        )

    def test_provider_cases_require_both_original_reports_and_package(self):
        for name in self.provider_native_cases():
            for mutation in ("missing_junit", "missing_log", "foreign_package"):
                with self.subTest(name=name, mutation=mutation):
                    root, log = self.reports()
                    if mutation != "missing_log":
                        for suite in root.findall("testsuite"):
                            for case in list(suite):
                                if case.get("name") != name:
                                    continue
                                suite.remove(case)
                                if mutation == "foreign_package":
                                    case.set("classname", "foreign-package")
                                    foreign = ET.SubElement(
                                        root, "testsuite", name="foreign-package"
                                    )
                                    foreign.append(case)
                    if mutation == "missing_log":
                        log = "\n".join(
                            line
                            for line in log.splitlines()
                            if not line.endswith(" " + name)
                        )
                    elif mutation == "foreign_package":
                        log = "\n".join(
                            line.replace(
                                f" {coverage.PACKAGE} {name}",
                                f" foreign-package {name}",
                            )
                            if line.endswith(" " + name)
                            else line
                            for line in log.splitlines()
                        )
                    self.assertFalse(self.assess(root, log))

    def test_each_original_owner_group_is_required_in_both_reports(self):
        for group, _, names in coverage.OWNER_GROUPS:
            with self.subTest(group=group, missing_from="junit"):
                root, log = self.reports()
                for suite in root.findall("testsuite"):
                    for case in list(suite):
                        if case.get("name") in names:
                            suite.remove(case)
                self.assertFalse(self.assess(root, log))
            with self.subTest(group=group, missing_from="native_log"):
                root, log = self.reports()
                lines = [
                    line
                    for line in log.splitlines()
                    if not any(line.endswith(" " + name) for name in names)
                ]
                self.assertFalse(self.assess(root, "\n".join(lines)))

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
        for status in (
            "skipped",
            "failure",
            "error",
            "flakyFailure",
            "flakyError",
            "rerunFailure",
            "rerunError",
        ):
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
                saved["original-learning-owner-coverage.json"]["exact_pass_coverage"]
            )
            self.assertFalse((directory / "ordinary.log").exists())

    def test_original_evaluator_cases_cannot_be_supplied_by_agentd(self):
        root, log = self.reports()
        suites = {suite.get("name"): suite for suite in root.findall("testsuite")}
        evaluator = suites[coverage.EXECUTION_PACKAGE]
        daemon = suites[coverage.PACKAGE]
        for case in list(evaluator):
            evaluator.remove(case)
            case.set("classname", coverage.PACKAGE)
            daemon.append(case)
        self.assertFalse(
            self.assess(root, log.replace(coverage.EXECUTION_PACKAGE, coverage.PACKAGE))
        )

    def test_workflow_ordinary_executes_all_original_owner_packages(self):
        workflow = (
            Path(__file__).resolve().parents[1]
            / ".github/workflows/hepta-daemon-learning-native.yml"
        )
        text = workflow.read_text()
        start = text.index("          import base64\n")
        end = text.index("          PY\n", start)
        driver = "\n".join(line[10:] for line in text[start:end].splitlines())
        tree = ast.parse(driver)
        packages = next(
            node.value
            for node in tree.body
            if isinstance(node, ast.Assign)
            and any(
                isinstance(target, ast.Name) and target.id == "packages"
                for target in node.targets
            )
        )
        self.assertEqual(
            ast.literal_eval(packages),
            [
                "-p",
                "codex-hepta-agentd",
                "-p",
                "codex-hepta-learning-ledger",
                "-p",
                "codex-hepta-learning-artifacts",
                "-p",
                "codex-hepta-intelligence-eval",
                "-p",
                "codex-hepta-neuron",
            ],
        )
        ordinary = [
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "test"
            and node.args
            and isinstance(node.args[0], ast.Constant)
            and node.args[0].value == "ordinary"
        ]
        self.assertEqual(len(ordinary), 1)
        self.assertEqual(
            ast.dump(ordinary[0].args[1]),
            ast.dump(
                ast.parse(
                    '[*packages, "--lib", "--test-threads", "2"]', mode="eval"
                ).body
            ),
        )

    def maintenance_driver(self, directory, paths):
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
            if isinstance(node, ast.FunctionDef) and node.name == "postimages"
        )
        repo = directory / "source"
        records = directory / "records"
        records.mkdir()
        original = {}
        for path in paths:
            file = repo / path
            file.parent.mkdir(parents=True, exist_ok=True)
            original[path] = ("// original maintenance bytes: " + path + "\n").encode()
            file.write_bytes(original[path])

        def git(*args):
            if args == ("diff", "--binary", "HEAD", "--"):
                return b"original maintenance diff\n"
            if args == ("diff", "--name-only", "--no-renames", "-z", "HEAD", "--"):
                return b"\0".join(path.encode() for path in paths) + b"\0"
            if args == ("ls-files", "--others", "--exclude-standard", "-z"):
                return b""
            self.fail(f"unexpected maintenance Git query: {args}")

        saved = {}
        namespace = {
            "records": records,
            "repo": repo,
            "git": git,
            "os": SimpleNamespace(
                fsdecode=os.fsdecode, environ={"SOURCE_SHA": "b" * 40}
            ),
            "hashlib": hashlib,
            "base64": base64,
            "json": json,
            "print": lambda *args, **kwargs: None,
            "save": lambda name, value: saved.update({name: value}),
        }
        exec(
            compile(ast.Module(body=[method], type_ignores=[]), str(workflow), "exec"),
            namespace,
        )
        return namespace["postimages"], records, original, saved

    def test_actual_workflow_retains_all_five_maintained_owner_postimages(self):
        paths = (
            "codex-rs/hepta-agentd/src/owner.rs",
            "codex-rs/hepta-learning-ledger/src/witness.rs",
            "codex-rs/hepta-learning-artifacts/src/owner.rs",
            "codex-rs/hepta-intelligence-eval/src/owner.rs",
            "codex-rs/hepta-neuron/src/witness.rs",
        )
        with tempfile.TemporaryDirectory() as temporary:
            postimages, records, original, saved = self.maintenance_driver(
                Path(temporary), paths
            )
            postimages(True)
            result = saved["maintenance-summary.json"]
            self.assertTrue(result["complete"])
            self.assertEqual({item["path"] for item in result["files"]}, set(paths))
            restored = {}
            for line in (
                (records / "maintenance-postimages.jsonl").read_text().splitlines()
            ):
                if line.startswith("HEPTA_MAINTAINED_CHUNK "):
                    item = json.loads(line.split(" ", 1)[1])
                    self.assertEqual(item["index"], 0)
                    restored[item["path"]] = base64.b64decode(
                        item["base64"], validate=True
                    )
            self.assertEqual(restored, original)
            self.assertEqual(
                (records / "maintenance.patch").read_bytes(),
                b"original maintenance diff\n",
            )

    def test_actual_workflow_still_refuses_maintenance_outside_exact_owner_scope(self):
        for path in (
            "codex-rs/hepta-neuron-foreign/src/witness.rs",
            "codex-rs/hepta-neuron/Cargo.toml",
            "codex-rs/hepta-agentd-foreign/src/owner.rs",
            "codex-rs/hepta-learning-ledger-foreign/src/witness.rs",
            "codex-rs/hepta-learning-ledger/Cargo.toml",
        ):
            with self.subTest(path=path), tempfile.TemporaryDirectory() as temporary:
                postimages, records, _, saved = self.maintenance_driver(
                    Path(temporary), (path,)
                )
                with self.assertRaisesRegex(RuntimeError, "outside its Rust owners"):
                    postimages(True)
                self.assertEqual(saved, {})
                self.assertFalse((records / "maintenance-postimages.jsonl").exists())


if __name__ == "__main__":
    unittest.main()
