"""Adversarial receipt tests; no Rust success is inferred from this suite."""
import copy
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

SPEC = importlib.util.spec_from_file_location(
    "artifact_qualification", Path(__file__).with_name("hepta-artifact-qualification.py"))
Q = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(Q)
SHA = "a" * 40
XML = b'<testsuites><testsuite tests="1" failures="0" errors="0"><testcase classname="crate" name="boundary"/></testsuite></testsuites>'


class QualificationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.ctx = {"sourceSha": SHA, "testedTree": "b" * 40, "runId": "local"}

    def report(self, data=XML):
        path = self.root / "junit.xml"
        path.write_bytes(data)
        return path

    def receipt(self, lane="all", directory=None):
        directory = directory or self.root
        directory.mkdir(parents=True, exist_ok=True)
        body = {"schema": Q.SCHEMA, "lane": lane, "context": copy.deepcopy(self.ctx),
                "testedCommit": SHA, "job": "local", "passed": True, "activation": False,
                "release": False, "commands": [], "outputs": {}, "testSummary": None}
        for i, argv in enumerate(Q.commands(lane)):
            name = f"command-{i}.log"
            (directory / name).write_bytes(b"verified output\n")
            body["commands"].append({"argv": argv, "exitCode": 0, "reason": None})
        if lane in Q.FILTERS:
            (directory / "junit.xml").write_bytes(XML)
            body["testSummary"] = Q.suite_summary(directory / "junit.xml")
        for path in directory.iterdir():
            if path.name != "receipt.json":
                body["outputs"][path.name] = {"bytes": path.stat().st_size, "sha256": Q.digest(path.read_bytes())}
        return Q.seal(body)

    def reject(self, mutate):
        record = self.receipt()
        record.pop("receiptDigest")
        mutate(record)
        with self.assertRaises((ValueError, TypeError, KeyError)):
            Q.validate(Q.seal(record), "all", self.ctx, self.root)

    def test_valid_receipt(self):
        Q.validate(self.receipt(), "all", self.ctx, self.root)

    def test_digest_tampering(self):
        record = self.receipt()
        record["passed"] = False
        with self.assertRaises(ValueError):
            Q.validate(record, "all", self.ctx, self.root)

    def test_failed_lane(self):
        self.reject(lambda r: r.update(passed=False))

    def test_truthy_string_is_not_success(self):
        self.reject(lambda r: r.update(passed="true"))

    def test_activation_cannot_be_granted(self):
        self.reject(lambda r: r.update(activation=True))

    def test_release_cannot_be_granted(self):
        self.reject(lambda r: r.update(release=True))

    def test_stale_source(self):
        self.reject(lambda r: r["context"].update(sourceSha="c" * 40))

    def test_stale_tree(self):
        self.reject(lambda r: r["context"].update(testedTree="c" * 40))

    def test_wrong_run(self):
        self.reject(lambda r: r["context"].update(runId="old"))

    def test_wrong_tested_commit(self):
        self.reject(lambda r: r.update(testedCommit="d" * 40))

    def test_wrong_job(self):
        self.reject(lambda r: r.update(job="unrelated"))

    def test_wrong_lane(self):
        self.reject(lambda r: r.update(lane="owner"))

    def test_missing_command(self):
        self.reject(lambda r: r["commands"].pop())

    def test_failed_command(self):
        self.reject(lambda r: r["commands"][0].update(exitCode=1))

    def test_timeout(self):
        self.reject(lambda r: r["commands"][0].update(reason="timeout"))

    def test_boolean_exit_code(self):
        self.reject(lambda r: r["commands"][0].update(exitCode=False))

    def test_command_substitution(self):
        self.reject(lambda r: r["commands"][0].update(argv=["true"]))

    def test_missing_output(self):
        self.reject(lambda r: r["outputs"].pop("junit.xml"))

    def test_output_path_escape(self):
        self.reject(lambda r: r["outputs"].update({"../escape": {"bytes": 0, "sha256": ""}}))

    def test_output_content_tampering(self):
        record = self.receipt()
        (self.root / "command-0.log").write_bytes(b"changed")
        with self.assertRaises(ValueError):
            Q.validate(record, "all", self.ctx, self.root)

    def test_symlinked_output(self):
        record = self.receipt()
        path = self.root / "command-0.log"
        path.rename(self.root / "original")
        path.symlink_to("original")
        with self.assertRaises(ValueError):
            Q.validate(record, "all", self.ctx, self.root)

    def test_test_summary_tampering(self):
        self.reject(lambda r: r["testSummary"].update(tests=2))

    def test_junit_missing(self):
        with self.assertRaises(ValueError):
            Q.suite_summary(self.root / "absent.xml")

    def test_junit_success(self):
        self.assertEqual(Q.suite_summary(self.report())["tests"], 1)

    def test_junit_negative_cases(self):
        payloads = [b'<testsuites/>', XML.replace(b'tests="1"', b'tests="2"'),
                    XML.replace(b'name="boundary"', b''),
                    XML.replace(b'failures="0"', b'failures="1"'),
                    XML.replace(b'<testcase ', b'<testcase status="notrun" '),
                    b'<!DOCTYPE testsuites [<!ENTITY x "boom">]>' + XML,
                    XML.decode().encode('utf-16')]
        for tag in (b"failure", b"error", b"skipped", b"rerunFailure", b"flakyFailure"):
            payloads.append(XML.replace(b'name="boundary"/>', b'name="boundary"><' + tag + b'/></testcase>'))
        for payload in payloads:
            with self.subTest(payload=payload), self.assertRaises((ValueError, UnicodeError)):
                Q.suite_summary(self.report(payload))

    def test_duplicate_case(self):
        case = b'<testcase classname="crate" name="boundary"/>'
        with self.assertRaises(ValueError):
            Q.suite_summary(self.report(XML.replace(case, case + case).replace(b'tests="1"', b'tests="2"')))

    def test_exact_sha(self):
        for value in ("main", "0" * 40, "abc", "A" * 40, "x" * 40):
            with self.subTest(value=value), self.assertRaises(ValueError):
                Q.checked_sha(value)
        self.assertEqual(Q.checked_sha(SHA), SHA)

    def test_process_exit_and_timeout(self):
        result = Q.execute([sys.executable, "-c", "raise SystemExit(7)"], self.root, self.root / "exit.log")
        self.assertEqual(result["exitCode"], 7)
        result = Q.execute([sys.executable, "-c", "import time; time.sleep(10)"], self.root,
                           self.root / "timeout.log", timeout=0.15)
        self.assertEqual(result["reason"], "timeout_or_output_limit")
        self.assertNotEqual(result["exitCode"], 0)

    def test_never_uses_cargo_test(self):
        for lane in Q.LANES:
            for command in Q.commands(lane):
                self.assertNotEqual(command[:2], ["cargo", "test"])
        for lane in Q.FILTERS:
            self.assertEqual(Q.commands(lane)[0][:2], ["cargo", "check"])
            self.assertEqual(Q.commands(lane)[1][:2], ["just", "test"])

    def test_collector_requires_all_receipts_and_successful_jobs(self):
        destination = self.root / "receipts"
        for lane in Q.LANES:
            folder = destination / lane
            (folder).mkdir(parents=True)
            (folder / "receipt.json").write_bytes(Q.canonical(self.receipt(lane, folder)))
        needs = {name: {"result": "success"} for name in ("metadata", "native", "synthetic")}
        output = self.root / "summary.json"
        with patch.object(Q, "context", return_value=self.ctx), patch("builtins.print"):
            self.assertEqual(Q.collect(self.root, SHA, "b" * 40, destination, output, needs), 0)
            for value in ("skipped", "failure", "cancelled", "queued"):
                needs["native"]["result"] = value
                self.assertEqual(Q.collect(self.root, SHA, "b" * 40, destination, output, needs), 1)
            needs["native"]["result"] = "success"
            (destination / "owner/receipt.json").unlink()
            self.assertEqual(Q.collect(self.root, SHA, "b" * 40, destination, output, needs), 1)
        summary = json.loads(output.read_bytes())
        self.assertFalse(summary["qualified"])
        self.assertFalse(summary["activation"])

    def test_git_source_binding(self):
        subprocess.run(["git", "init", "-q", str(self.root)], check=True)
        path = self.root / "codex-rs/hepta-learning-artifacts/src/lib.rs"
        path.parent.mkdir(parents=True)
        path.write_text("// qualification fixture, not project source\n")
        subprocess.run(["git", "add", "."], cwd=self.root, check=True)
        subprocess.run(["git", "-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid",
                        "commit", "-qm", "fixture"], cwd=self.root, check=True)
        source = Q.git(self.root, "rev-parse", "HEAD")
        with patch.dict(os.environ, {"GITHUB_RUN_ID": "123", "GITHUB_RUN_ATTEMPT": "2"}):
            ctx = Q.context(self.root, source, "", False)
        self.assertEqual(ctx["sourceSha"], source)
        self.assertEqual(ctx["runAttempt"], "2")
        self.assertIn("codex-rs/hepta-learning-artifacts/src/lib.rs", ctx["sourceBlobs"])


if __name__ == "__main__":
    unittest.main()
