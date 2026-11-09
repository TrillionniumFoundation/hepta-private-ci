"""Reject false native receipts without starting Cargo or Rust."""

import copy
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
from hepta_ci_junit import NoDoctypeTreeBuilder
import windows_fixture_followup as subject


class ReceiptTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name).resolve()
        self.root = self.base / "source"
        self.target = self.base / "target"
        self.binary = self.target / "dev-small/deps/example.exe"
        self.binary.parent.mkdir(parents=True)
        self.binary.write_bytes(b"MZ fixture, never executed")
        self.group = {
            "id": "test",
            "package": "codex-example",
            "binaryId": "codex-example",
            "crate": "example",
            "target": ["--lib"],
            "features": [],
            "required": ["required_case"],
            "prefixes": {},
            "expected": 1,
        }
        self.document = {
            "rust-suites": {
                "codex-example": {
                    "binary-id": "codex-example",
                    "package-name": "codex-example",
                    "cwd": str(self.root / "codex-rs/example"),
                    "binary-path": str(self.binary),
                    "testcases": {
                        "required_case": {
                            "ignored": False,
                            "filter-match": {"status": "matches"},
                        },
                        "excluded_case": {
                            "ignored": True,
                            "filter-match": {"status": "mismatch"},
                        },
                    },
                }
            }
        }
        self.suite = self.document["rust-suites"]["codex-example"]
        self.keys = [["codex-example", "required_case"]]

    def discover(self):
        return subject.selected_cases(self.document, self.group, self.root, self.target)

    def xml(self, body="", classname="codex-example", name="required_case"):
        return (
            '<testsuites><testsuite><testcase classname="'
            + classname
            + '" name="'
            + name
            + '">'
            + body
            + "</testcase></testsuite></testsuites>"
        )

    def junit(self, xml):
        path = self.base / "junit.xml"
        path.write_text(xml, encoding="utf-8")
        return subject.junit_result(
            path,
            {"startedUnix": time.time() - 5, "finishedUnix": time.time() + 5},
            self.keys,
            NoDoctypeTreeBuilder,
        )

    def test_exact_discovery_retains_excluded_ignored(self):
        found = self.discover()
        self.assertEqual(found["selected"], self.keys)
        self.assertEqual(
            (
                found["selectedCount"],
                found["excludedCount"],
                found["excludedIgnoredCount"],
            ),
            (1, 1, 1),
        )

    def test_owner_selection_preserves_the_registered_closed_scope(self):
        other = copy.deepcopy(self.group)
        other.update(id="second", expected=2)
        scope = {"groups": [self.group, other], "expectedTotal": 3}
        self.assertEqual(subject.select_groups(scope, None), scope["groups"])
        self.assertEqual(subject.select_groups(scope, "second"), [other])
        for group_id in ("missing", "test,second", ""):
            with self.subTest(group_id=group_id), self.assertRaises(ValueError):
                subject.select_groups(scope, group_id)
        scope["expectedTotal"] = 4
        with self.assertRaises(ValueError):
            subject.select_groups(scope, "second")

    def helper_fixture(self):
        rows = []
        for name in ("codex-command-runner", "codex-windows-sandbox-setup"):
            data = b"MZ checker fixture, never executed: " + name.encode()
            binary = self.target / "dev-small" / (name + ".exe")
            sibling = self.target / "dev-small/deps" / (name + ".exe")
            binary.write_bytes(data)
            sibling.write_bytes(data)
            rows.append(
                {
                    "name": name,
                    "source": str(binary),
                    "testSibling": str(sibling),
                    "bytes": len(data),
                    "sha256": hashlib.sha256(data).hexdigest(),
                }
            )
        return {"passed": True, "artifacts": rows}

    def test_cli_receives_only_verified_compiler_metadata_in_child_environment(self):
        helpers = self.helper_fixture()
        inherited = {"PATH": "preserve-existing-path"}
        environment, bindings = subject.cli_helper_environment(
            helpers, self.target, inherited
        )
        self.assertEqual(inherited, {"PATH": "preserve-existing-path"})
        self.assertEqual(environment["PATH"], inherited["PATH"])
        self.assertEqual(len(environment), 3)
        self.assertEqual(len(bindings), 2)
        for row in helpers["artifacts"]:
            self.assertEqual(environment["CARGO_BIN_EXE_" + row["name"]], row["source"])
        self.group["id"] = "cli-cloud"
        commands = []

        def capture(folder, name, command, cwd, environment=None):
            commands.append((name, environment))
            if name == "discovery":
                stdout = json.dumps(self.document)
            else:
                stdout = ""
                report = folder / "nextest-store/local/junit.xml"
                report.parent.mkdir()
                report.write_text(self.xml())
            (folder / (name + ".stdout")).write_text(stdout)
            (folder / (name + ".stderr")).write_text("")
            return {
                "exitCode": 0,
                "startedUnix": time.time() - 5,
                "finishedUnix": time.time() + 5,
            }

        with patch.object(subject, "capture", side_effect=capture):
            result = subject.run_group(
                self.group,
                self.root,
                self.target,
                self.base / "cli",
                NoDoctypeTreeBuilder,
                [],
                helpers,
            )
        self.assertTrue(result["passed"])
        self.assertEqual([name for name, _ in commands], ["discovery", "tests"])
        for _, child_environment in commands:
            for row in helpers["artifacts"]:
                self.assertEqual(
                    child_environment["CARGO_BIN_EXE_" + row["name"]], row["source"]
                )
        self.assertEqual(
            result["cliHelperBindingsBefore"], result["cliHelperBindingsAfter"]
        )

    def test_missing_changed_or_conflicting_cli_helper_metadata_is_rejected(self):
        helpers = self.helper_fixture()
        for changed in (
            None,
            {"passed": False},
            {"passed": True, "artifacts": helpers["artifacts"][:1]},
        ):
            with self.subTest(changed=changed), self.assertRaises(ValueError):
                subject.cli_helper_environment(changed, self.target, {})
        wrong = copy.deepcopy(helpers)
        wrong["artifacts"][0]["sha256"] = "0" * 64
        with self.assertRaises(ValueError):
            subject.cli_helper_environment(wrong, self.target, {})
        with self.assertRaises(ValueError):
            subject.cli_helper_environment(
                helpers,
                self.target,
                {"CARGO_BIN_EXE_CODEX-COMMAND-RUNNER": str(self.binary)},
            )
        Path(helpers["artifacts"][0]["testSibling"]).write_bytes(b"MZ changed")
        with self.assertRaises(ValueError):
            subject.cli_helper_environment(helpers, self.target, {})

    def test_passed_junit_does_not_rescue_a_native_process_leak(self):
        def capture(folder, name, command, cwd, environment=None):
            if name == "discovery":
                stdout = json.dumps(self.document)
            else:
                stdout = "LEAK [ 0.1s] codex-example required_case\nSummary 1 tests run: 1 passed (1 leaky)"
                report = folder / "nextest-store/local/junit.xml"
                report.parent.mkdir()
                report.write_text(self.xml())
            (folder / (name + ".stdout")).write_text(stdout)
            (folder / (name + ".stderr")).write_text("")
            return {
                "exitCode": 0,
                "startedUnix": time.time() - 5,
                "finishedUnix": time.time() + 5,
            }

        with patch.object(subject, "capture", side_effect=capture):
            result = subject.run_group(
                self.group,
                self.root,
                self.target,
                self.base / "leak",
                NoDoctypeTreeBuilder,
                [],
            )
        self.assertTrue(result["junit"]["passed"])
        self.assertFalse(result["passed"])
        self.assertTrue(result["leakObservations"]["terminalLines"])
        self.assertEqual(result["leakObservations"]["nonzeroSummaryCounts"], [1])

    def test_wrong_source_binary_or_ignored_is_rejected(self):
        for change in ("binary-id", "cwd", "ignored", "missing"):
            with self.subTest(change=change):
                document = copy.deepcopy(self.document)
                suite = document["rust-suites"]["codex-example"]
                if change == "binary-id":
                    suite["binary-id"] = "another-target"
                elif change == "cwd":
                    suite["cwd"] = str(self.base / "old-source")
                elif change == "ignored":
                    suite["testcases"]["required_case"]["ignored"] = True
                else:
                    del suite["testcases"]["required_case"]
                with self.assertRaises(ValueError):
                    subject.selected_cases(document, self.group, self.root, self.target)

    def test_parameterized_prefix_requires_all_four_cases(self):
        self.group.update(required=[], prefixes={"parameterized::": 4}, expected=4)
        self.suite["testcases"] = {
            f"parameterized::{i}": {
                "ignored": False,
                "filter-match": {"status": "matches"},
            }
            for i in range(4)
        }
        self.assertEqual(self.discover()["selectedCount"], 4)
        del self.suite["testcases"]["parameterized::3"]
        with self.assertRaises(ValueError):
            self.discover()

    def test_missing_added_signed_case_rejects_the_default_agentd_group(self):
        scope = json.loads(
            (
                Path(__file__).resolve().parents[1]
                / "fixtures/windows-fixture-followup-scope.json"
            ).read_text()
        )
        group = next(
            row for row in scope["groups"] if row["id"] == "agentd-fleet-default"
        )
        suite = copy.deepcopy(self.suite)
        suite.update(
            {
                "binary-id": group["binaryId"],
                "package-name": group["package"],
                "cwd": str(self.root / "codex-rs" / group["crate"]),
                "testcases": {
                    name: {"ignored": False, "filter-match": {"status": "matches"}}
                    for name in group["required"]
                },
            }
        )
        document = {"rust-suites": {group["binaryId"]: suite}}
        accepted = subject.selected_cases(document, group, self.root, self.target)
        self.assertEqual(accepted["selectedCount"], group["expected"])
        del suite["testcases"][group["required"][-1]]
        with self.assertRaises(ValueError):
            subject.selected_cases(document, group, self.root, self.target)

    def test_binary_outside_task_profile_is_rejected(self):
        other = self.base / "old.exe"
        other.write_bytes(b"MZ old")
        self.suite["binary-path"] = str(other)
        with self.assertRaises(ValueError):
            self.discover()

    def test_junit_pass_failure_skip_preserve_real_counts(self):
        self.assertTrue(self.junit(self.xml())["passed"])
        for body in ('<failure message="original failure"/>', "<error/>", "<skipped/>"):
            with self.subTest(body=body):
                result = self.junit(self.xml(body))
                self.assertFalse(result["passed"])
                self.assertEqual(result["passedCount"], 0)

    def test_wrong_or_duplicate_junit_keys_are_rejected(self):
        for xml in (
            self.xml(classname="another-target"),
            self.xml(name="unselected"),
            self.xml().replace(
                "</testsuite>",
                '<testcase classname="codex-example" '
                'name="required_case"/></testsuite>',
            ),
        ):
            with self.subTest(xml=xml), self.assertRaises(ValueError):
                self.junit(xml)

    def test_stale_junit_is_rejected(self):
        path = self.base / "stale.xml"
        path.write_text(self.xml())
        os.utime(path, (1, 1))
        with self.assertRaises(ValueError):
            subject.junit_result(
                path,
                {"startedUnix": time.time() - 5, "finishedUnix": time.time() + 5},
                self.keys,
                NoDoctypeTreeBuilder,
            )

    def test_document_types_are_rejected(self):
        with self.assertRaises(ValueError):
            self.junit("<!DOCTYPE testsuites []>" + self.xml())

    def test_junit_retry_records_are_rejected(self):
        for tag in ("rerunFailure", "rerunError", "flakyFailure", "flakyError"):
            with self.subTest(tag=tag), self.assertRaises(ValueError):
                self.junit(self.xml(f"<{tag}/>"))

    def test_intermediate_source_drift_is_rejected(self):
        baseline = {
            "source": {"head": "same", "allChanges": ""},
            "observer": {"head": "observer", "allChanges": ""},
        }
        changed = copy.deepcopy(baseline["source"])
        changed["allChanges"] = " M production.rs"
        with patch.object(
            subject, "source", side_effect=[changed, baseline["observer"]]
        ):
            with self.assertRaises(ValueError):
                subject.check_sources(
                    self.base,
                    "after-failed-case",
                    self.root,
                    self.base / "observer",
                    baseline,
                )
        observed = json.loads((self.base / "after-failed-case-source.json").read_text())
        self.assertEqual(observed["source"], changed)

    def test_explicit_skip_cannot_be_rescued_by_junit_pass(self):
        directory = self.base / "group"
        marker = "Skipping test in a remote test environment:"

        def capture(folder, name, command, cwd, environment=None):
            self.assertEqual(cwd, self.root / "codex-rs")
            if name == "discovery":
                stdout = json.dumps(self.document)
            else:
                self.assertEqual(command[command.index("--retries") + 1], "0")
                self.assertEqual(
                    command[command.index("--success-output") + 1], "final"
                )
                stdout = marker
                report = folder / "nextest-store/local/junit.xml"
                report.parent.mkdir()
                report.write_text(self.xml())
            (folder / (name + ".stdout")).write_text(stdout)
            (folder / (name + ".stderr")).write_text("")
            return {
                "exitCode": 0,
                "startedUnix": time.time() - 5,
                "finishedUnix": time.time() + 5,
            }

        with patch.object(subject, "capture", side_effect=capture):
            result = subject.run_group(
                self.group,
                self.root,
                self.target,
                directory,
                NoDoctypeTreeBuilder,
                [marker],
            )
        self.assertTrue(result["junit"]["passed"])
        self.assertEqual(result["explicitSkipMarkers"], [marker])
        self.assertFalse(result["passed"])


if __name__ == "__main__":
    unittest.main()
