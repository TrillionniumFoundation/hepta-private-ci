#!/usr/bin/env python3
"""Exercise JUnit retention with synthetic receipts and real temporary files.

No recorded command is executed. These tests qualify the collector behavior,
not the synthetic source identity, Rust tests, or any product adoption.
"""

from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


SCRIPT = Path(__file__).resolve().with_name("hepta_ci_junit.py")
PASS_XML = (
    b'<testsuites><testsuite name="synthetic" tests="2">'
    b'<testcase name="executed"/>'
    b'<testcase name="not-executed"><skipped/></testcase>'
    b"</testsuite></testsuites>\n"
)
FAIL_XML = (
    b'<testsuites><testsuite name="synthetic" tests="4">'
    b'<testcase name="passed"/>'
    b'<testcase name="failed"><failure>synthetic failure</failure></testcase>'
    b'<testcase name="errored"><error>synthetic error</error></testcase>'
    b'<testcase name="not-executed"><skipped/></testcase>'
    b"</testsuite></testsuites>\n"
)
DTD_XML = (
    '<!DOCTYPE testsuite [<!ENTITY injected "synthetic entity">]>'
    '<testsuite><testcase name="executed">'
    "<system-out>&injected;</system-out></testcase></testsuite>"
)


class JUnitCollectionTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name).resolve()
        self.source = "a" * 40
        self.tree = "b" * 40
        self.started = datetime(2026, 1, 1, tzinfo=timezone.utc)
        self.finished = self.started + timedelta(seconds=10)

    def fixture(self, name, data=PASS_XML, *, failed=0):
        self.case = self.base / name
        self.case.mkdir()
        self.execution = self.case / "scoped-tests.json"
        self.native = self.case / "native-junit.xml"
        self.output = self.case / "junit-scoped.xml"
        self.summary_path = self.output.with_suffix(".summary.json")
        self.native.write_bytes(data)
        self.stamp_native(self.started.timestamp() + 5)
        log = f"Summary [0.001s] {1 + failed} tests run: 1 passed, {failed} failed, 1 skipped\n".encode()
        (self.case / "synthetic-runner.log").write_bytes(log)
        before = {
            "commit": self.source,
            "tree": self.tree,
            "parents": [],
            "dirty": False,
        }
        code = 101 if failed else 0
        self.record = {
            "schema_version": 1,
            "source_sha": self.source,
            "tested_sha": self.source,
            "base_sha": self.source,
            "lane": "source-head",
            "before": before,
            "after": dict(before),
            "command": ["just", "test", "--locked", "-p", "synthetic-collector-only"],
            "working_directory": str(self.case),
            "run_id": "synthetic-collector-only",
            "run_attempt": "1",
            "job": "synthetic-collector-only",
            "started_at": self.started.isoformat(),
            "finished_at": self.finished.isoformat(),
            "status": "failed" if failed else "passed",
            "exit_code": code,
            "command_exit_code": code,
            "returncode": code,
            "timed_out": False,
            "output_limit_exceeded": False,
            "observed_passed_tests": 1,
            "observed_failed_tests": failed,
            "minimum_tests": 1,
            "log_file": "synthetic-runner.log",
            "log_bytes": len(log),
            "log_sha256": hashlib.sha256(log).hexdigest(),
        }
        self.save_record()

    def stamp_native(self, timestamp):
        os.utime(self.native, (timestamp, timestamp))

    def save_record(self):
        self.execution.write_text(json.dumps(self.record), encoding="utf-8")

    def collect(self):
        result = subprocess.run(
            [
                sys.executable,
                str(SCRIPT),
                "--execution",
                str(self.execution),
                "--junit",
                str(self.native),
                "--output",
                str(self.output),
            ],
            cwd=self.case,
            env={
                **os.environ,
                "SOURCE_SHA": self.source,
                "PYTHONDONTWRITEBYTECODE": "1",
            },
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        self.assertEqual(result.stderr, "")
        return result.returncode, json.loads(result.stdout)

    def assert_rejected(self, code, summary, *, retained=False):
        self.assertNotEqual(code, 0)
        self.assertEqual(summary["status"], "rejected")
        self.assertTrue(summary["error"])
        self.assertEqual(json.loads(self.summary_path.read_text()), summary)
        self.assertEqual(self.output.exists(), retained)
        if retained:
            self.assertEqual(self.output.read_bytes(), self.native.read_bytes())

    def test_fresh_report_retains_exact_bytes_and_execution_identity(self):
        self.fixture("fresh")
        original = {
            path: (path.read_bytes(), path.stat().st_mtime_ns)
            for path in (self.native, self.execution)
        }
        code, summary = self.collect()
        self.assertEqual(code, 0)
        self.assertEqual(summary["status"], "passed")
        self.assertEqual(summary["source_sha"], self.source)
        self.assertEqual(summary["source_tree"], self.tree)
        self.assertEqual(summary["command"], self.record["command"])
        self.assertEqual(summary["run_id"], "synthetic-collector-only")
        self.assertEqual(
            summary["execution_sha256"],
            hashlib.sha256(original[self.execution][0]).hexdigest(),
        )
        self.assertEqual(summary["junit_sha256"], hashlib.sha256(PASS_XML).hexdigest())
        self.assertEqual(summary["junit_bytes"], len(PASS_XML))
        self.assertEqual(summary["junit_mtime_ns"], original[self.native][1])
        self.assertEqual(summary["total_testcases"], 2)
        self.assertEqual(summary["skipped_in_xml"], 1)
        self.assertEqual(summary["failures"], 0)
        self.assertEqual(summary["errors"], 0)
        self.assertEqual(self.output.read_bytes(), PASS_XML)
        self.assertEqual(json.loads(self.summary_path.read_text()), summary)
        for path, observation in original.items():
            self.assertEqual((path.read_bytes(), path.stat().st_mtime_ns), observation)

    def test_failed_execution_retains_xml_but_never_passes(self):
        for name in ("failing-cases", "nonzero-process", "failed-status"):
            with self.subTest(name=name):
                data = FAIL_XML if name == "failing-cases" else PASS_XML
                self.fixture(name, data, failed=2 if name == "failing-cases" else 0)
                if name == "nonzero-process":
                    self.record.update(exit_code=101, command_exit_code=101)
                elif name == "failed-status":
                    self.record["status"] = "failed"
                self.save_record()
                code, summary = self.collect()
                self.assertNotEqual(code, 0)
                self.assertEqual(summary["status"], "retained-failed")
                self.assertEqual(self.output.read_bytes(), data)
                self.assertEqual(json.loads(self.summary_path.read_text()), summary)
                if name == "failing-cases":
                    self.assertEqual(summary["total_testcases"], 4)
                    self.assertEqual(summary["failures"], 1)
                    self.assertEqual(summary["errors"], 1)
        self.fixture("missing-terminal-state")
        del self.record["status"]
        self.save_record()
        self.assert_rejected(*self.collect(), retained=True)

    def test_missing_or_stale_xml_cannot_qualify_a_success_or_failure(self):
        for name in ("missing-pass", "missing-failure", "stale", "future"):
            with self.subTest(name=name):
                self.fixture(name)
                if name.startswith("missing"):
                    self.native.unlink()
                    if name == "missing-failure":
                        self.record.update(
                            status="failed", exit_code=101, command_exit_code=101
                        )
                        self.save_record()
                elif name == "stale":
                    self.stamp_native(self.started.timestamp() - 1)
                else:
                    self.stamp_native(self.finished.timestamp() + 1)
                self.assert_rejected(*self.collect())

    def test_source_lane_schema_and_command_must_match_the_receipt(self):
        mutations = {
            "source": lambda r: r.update(source_sha="c" * 40),
            "tested-source": lambda r: r.update(tested_sha="c" * 40),
            "source-before": lambda r: r["before"].update(commit="c" * 40),
            "changed-tree": lambda r: r["after"].update(tree="c" * 40),
            "lane": lambda r: r.update(lane="base-merge"),
            "command": lambda r: r.update(command=["just", "clippy", "--locked"]),
            "schema": lambda r: r.update(schema_version=2),
            "boolean-schema": lambda r: r.update(schema_version=True),
        }
        for name, mutate in mutations.items():
            with self.subTest(name=name):
                self.fixture(name)
                mutate(self.record)
                self.save_record()
                self.assert_rejected(*self.collect())

    def test_dirty_execution_receipts_are_rejected(self):
        for name in ("dirty-throughout", "dirty-after"):
            with self.subTest(name=name):
                self.fixture(name)
                self.record["after"]["dirty"] = True
                if name == "dirty-throughout":
                    self.record["before"]["dirty"] = True
                self.save_record()
                self.assert_rejected(*self.collect())

    def test_independent_case_counts_must_match_integer_runner_counts(self):
        cases = (
            ("missing-passed", "observed_passed_tests", 0),
            ("extra-passed", "observed_passed_tests", 2),
            ("extra-failed", "observed_failed_tests", 1),
            ("boolean-count", "observed_passed_tests", True),
            ("float-count", "observed_failed_tests", 0.0),
            ("negative-count", "observed_failed_tests", -1),
        )
        for name, field, value in cases:
            with self.subTest(name=name):
                self.fixture(name)
                self.record[field] = value
                self.save_record()
                self.assert_rejected(*self.collect(), retained=True)

    def test_empty_unsafe_and_oversized_reports_never_qualify(self):
        cases = {
            "empty": b"",
            "zero-cases": b"<testsuites/>",
            "skipped-only": b'<testsuite><testcase name="skip"><skipped/></testcase></testsuite>',
            "wrong-root": b'<not-junit><testcase name="case"/></not-junit>',
            "ascii-dtd": DTD_XML.encode(),
            "utf16-dtd": ('<?xml version="1.0" encoding="UTF-16"?>' + DTD_XML).encode(
                "utf-16"
            ),
            "oversized": b"",
        }
        for name, data in cases.items():
            with self.subTest(name=name):
                self.fixture(name, data)
                if name == "oversized":
                    with self.native.open("wb") as stream:
                        stream.truncate(64 * 1024 * 1024 + 1)
                    self.stamp_native(self.started.timestamp() + 5)
                self.assert_rejected(
                    *self.collect(), retained=name in ("zero-cases", "skipped-only")
                )

    def test_existing_xml_or_summary_is_never_overwritten(self):
        for name in ("xml", "summary", "both", "completed"):
            with self.subTest(name=name):
                self.fixture(name)
                if name == "completed":
                    code, summary = self.collect()
                    self.assertEqual(code, 0)
                    self.assertEqual(summary["status"], "passed")
                else:
                    if name in ("xml", "both"):
                        self.output.write_bytes(b"original XML evidence\n")
                    if name in ("summary", "both"):
                        self.summary_path.write_text(
                            '{"status":"rejected","error":"prior attempt"}\n',
                            encoding="utf-8",
                        )
                originals = {
                    path: (path.read_bytes(), path.stat().st_mtime_ns)
                    for path in (self.output, self.summary_path)
                    if path.exists()
                }
                code, summary = self.collect()
                self.assertNotEqual(code, 0)
                self.assertEqual(summary["status"], "rejected")
                self.assertTrue(summary["error"])
                for path, original in originals.items():
                    self.assertEqual(
                        (path.read_bytes(), path.stat().st_mtime_ns), original
                    )
                if name == "summary":
                    self.assertFalse(self.output.exists())

    def test_execution_interval_must_be_aware_and_ordered(self):
        for name in ("naive-start", "naive-finish", "reversed"):
            with self.subTest(name=name):
                self.fixture(name)
                if name == "naive-start":
                    self.record["started_at"] = self.started.replace(
                        tzinfo=None
                    ).isoformat()
                elif name == "naive-finish":
                    self.record["finished_at"] = self.finished.replace(
                        tzinfo=None
                    ).isoformat()
                else:
                    self.record["finished_at"] = (
                        self.started - timedelta(seconds=1)
                    ).isoformat()
                self.save_record()
                self.assert_rejected(*self.collect())


if __name__ == "__main__":
    unittest.main()
