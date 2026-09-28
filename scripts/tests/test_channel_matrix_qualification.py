"""Synthetic receipt validation only; these tests are NOT native execution."""

import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

import channel_matrix_qualification as q
from channel_matrix_evidence import COMMANDS, file_digest


class ScenarioLedgerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name)
        self.registry = ROOT / q.REGISTRY
        self.row = q.load_registry(self.registry)
        sources = {
            test["source"]
            for scenario in self.row["scenarios"]
            for test in scenario["tests"]
        }
        source = {
            "schema": "hepta.channel-matrix-source-snapshot.v1",
            "testedSha": "a" * 40,
            "testedTree": "b" * 40,
            "sourceSha": "a" * 40,
            "baseSha": "c" * 40,
            "lane": "source-head",
            "files": [
                {"path": q.REGISTRY, "sha256": file_digest(self.registry)}
            ]
            + [{"path": path} for path in sources],
        }
        self.write("source.json", source)
        self.write("source-after.json", source)

    def write(self, name: str, row: dict) -> None:
        (self.path / name).write_text(json.dumps(row))

    def receipt(self, xml: str, **changes: object) -> None:
        log = self.path / "focused-tests.log"
        log.write_text("test fixture, not native execution")
        report = self.path / "focused-tests.junit.xml"
        report.write_text(xml)
        row = {
            "schema": "hepta.channel-matrix-command.v1",
            "label": "focused-tests",
            "arguments": COMMANDS["focused-tests"],
            "workingDirectory": "codex-rs",
            "testedSha": "a" * 40,
            "sourceSnapshotSha256": file_digest(self.path / "source.json"),
            "completed": True,
            "exitCode": 0,
            "launchError": None,
            "sourceUnchanged": True,
            "log": {
                "path": log.name,
                "bytes": log.stat().st_size,
                "sha256": file_digest(log),
                "withinBudget": True,
            },
            "junit": {
                "path": report.name,
                "bytes": report.stat().st_size,
                "sha256": file_digest(report),
            },
        }
        row.update(changes)
        self.write("focused-tests.command.json", row)

    def report(self, child: str = "") -> str:
        test = self.row["scenarios"][23]["tests"][0]
        return (
            "<testsuites>"
            f'<testsuite name="{test["binary"]}">'
            f'<testcase name="{test["test"]}">{child}</testcase>'
            "</testsuite>"
            "</testsuites>"
        )

    def all_native_report(self) -> str:
        suites: dict[str, set[str]] = {}
        for scenario in self.row["scenarios"]:
            for test in scenario["tests"]:
                suites.setdefault(test["binary"], set()).add(test["test"])
        encoded = "".join(
            f'<testsuite name="{binary}">'
            + "".join(
                f'<testcase name="{test}"/>' for test in sorted(tests)
            )
            + "</testsuite>"
            for binary, tests in sorted(suites.items())
        )
        return f"<testsuites>{encoded}</testsuites>"

    def test_exact_case_does_not_qualify_other_cases_or_external_target(self) -> None:
        self.receipt(self.report())
        row = q.ledger(self.path, self.registry)
        self.assertEqual(row["scenarios"][23]["native_fixture_result"], "passed")
        self.assertEqual(row["scenarios"][24]["native_fixture_result"], "not_executed")
        self.assertEqual(row["scenarios"][11]["external_qualification"], "not_proved")
        self.assertEqual(row["native_completion"], "incomplete")
        self.assertIn("MATRIX-Q25", row["native_blockers"])
        self.assertFalse(row["authority_granted"])
        self.assertFalse(row["release"])

    def test_every_declared_native_case_is_required_and_bound_to_artifacts(self) -> None:
        self.receipt(self.all_native_report())
        row = q.ledger(self.path, self.registry)
        self.assertEqual(row["native_completion"], "passed")
        self.assertEqual(row["native_blockers"], [])
        self.assertEqual(row["evidence"]["source_snapshot"]["path"], "source.json")
        self.assertEqual(
            row["evidence"]["focused_command"]["path"],
            "focused-tests.command.json",
        )
        self.assertEqual(row["evidence"]["junit"]["path"], "focused-tests.junit.xml")
        native = [
            scenario for scenario in row["scenarios"] if scenario["native_required"]
        ]
        self.assertTrue(native)
        self.assertTrue(
            all(scenario["candidate"]["commit"] == "a" * 40 for scenario in native)
        )
        self.assertTrue(
            all(
                test["evidence"]["artifact"]["sha256"]
                for scenario in native
                for test in scenario["tests"]
            )
        )

    def test_skip_flaky_and_failure_never_become_pass(self) -> None:
        for tag, state in (
            ("skipped", "skipped"),
            ("failure", "failed"),
            ("flakyFailure", "flaky"),
        ):
            self.receipt(self.report(f"<{tag}/>"))
            row = q.ledger(self.path, self.registry)
            self.assertEqual(row["scenarios"][23]["native_fixture_result"], state)
            self.assertEqual(row["native_completion"], "incomplete")

    def test_missing_report_not_inferred_from_green_command(self) -> None:
        self.receipt(self.report(), junit=None)
        row = q.ledger(self.path, self.registry)
        self.assertEqual(row["scenarios"][23]["native_fixture_result"], "not_executed")
        self.assertEqual(row["native_completion"], "incomplete")

    def test_tampered_report_rejected(self) -> None:
        self.receipt(self.report())
        (self.path / "focused-tests.junit.xml").write_text(
            self.report("<skipped/>")
        )
        with self.assertRaises(ValueError):
            q.ledger(self.path, self.registry)

    def test_wrong_sha_boolean_exit_and_alternate_command_rejected(self) -> None:
        for change in (
            {"testedSha": "d" * 40},
            {"exitCode": False},
            {"arguments": ["echo", "passed"]},
        ):
            self.receipt(self.report(), **change)
            with self.subTest(change=change), self.assertRaises(ValueError):
                q.ledger(self.path, self.registry)

    def test_duplicate_tests_zero_tests_and_dtd_are_rejected(self) -> None:
        for xml in (
            "<testsuites/>",
            "<!DOCTYPE x><testsuites/>",
            '<testsuites><testsuite name="x"><testcase name="y"/>'
            '<testcase name="y"/></testsuite></testsuites>',
        ):
            with self.subTest(xml=xml), self.assertRaises(ValueError):
                q.parse_junit(xml.encode())

    def test_stale_registry_cannot_be_swapped_after_execution(self) -> None:
        self.receipt(self.report())
        path = self.path / "changed.json"
        row = dict(self.row)
        row["note"] = "different"
        self.write(path.name, row)
        with self.assertRaises(ValueError):
            q.ledger(self.path, path)

    def test_registry_inventory_is_closed_and_ordered(self) -> None:
        for scenarios in (
            self.row["scenarios"][:-1],
            list(reversed(self.row["scenarios"])),
        ):
            row = dict(self.row)
            row["scenarios"] = scenarios
            path = self.path / "inventory.json"
            self.write(path.name, row)
            with self.subTest(count=len(scenarios)), self.assertRaises(ValueError):
                q.load_registry(path)

    def test_registry_tests_exist_in_native_source(self) -> None:
        for scenario in self.row["scenarios"]:
            for test in scenario["tests"]:
                needle = "fn " + test["test"].split("::")[-1] + "("
                self.assertIn(needle, (ROOT / test["source"]).read_text())


if __name__ == "__main__":
    unittest.main()
