#!/usr/bin/env python3
"""Actual runner/manifest regression tests in disposable Git repositories.

The miniature test plan is NOT the repository's qualification result. These
cases prove that substituted commands and weakened limits cannot borrow a pass.
"""
from __future__ import annotations

import copy
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

from cognitive_qualification_manifest import load_record
from cognitive_store_plan import SPEC_ENV, load_plan, resolve_plan, spec_sha256
import test_cognitive_qualification_manifest as reference_tests

SCRIPTS = Path(__file__).resolve().parent
PLAN = "docs/modules/cognitive.store/QUALIFICATION_PLAN.json"


def plan_for(command=None):
    return {"schema": "hepta.cognitive-store-qualification-plan.v1", "module": "cognitive.store",
            "commands": [{"record": "checks.json", "command": command or ["python3", "-V"],
                          "cwd": ".", "minimumTests": 0, "native": False, "timeoutSeconds": 20}],
            "evidence": [], "targetHostQualification": False}


class PlanTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name).resolve()
        self.plan = plan_for()
        self.env = {"RUNNER_TEMP": str(self.root.parent / "outside"), "SOURCE_SHA": "1" * 40}

    def resolve(self):
        return resolve_plan(self.plan, self.root, self.env)

    def test_exact_spec_includes_limits_and_workload(self):
        item = self.plan["commands"][0]
        item["env"] = {"HEPTA_COGNITIVE_PERF_RECORDS": "256"}
        specs, _ = self.resolve()
        self.assertEqual(specs[0]["minimum_tests"], 0)
        self.assertEqual(specs[0]["environment"], item["env"])
        changed = {**specs[0], "environment": {"HEPTA_COGNITIVE_PERF_RECORDS": "1"}}
        self.assertNotEqual(spec_sha256(changed), spec_sha256(specs[0]))

    def test_duplicate_records_rejected(self):
        self.plan["commands"].append(copy.deepcopy(self.plan["commands"][0]))
        with self.assertRaises(ValueError):
            self.resolve()

    def test_unsafe_names_rejected(self):
        for value in (".", "..", "../pass.json", "/pass.json", "x\\pass.json", "", "pass.log"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.plan["commands"][0]["record"] = value
                self.resolve()

    def test_identity_environment_cannot_be_overridden(self):
        for key in ("SOURCE_SHA", "TESTED_SHA", "BASE_SHA", "GITHUB_RUN_ID", "PATH", SPEC_ENV):
            with self.subTest(key=key), self.assertRaises(ValueError):
                self.plan["commands"][0]["env"] = {key: "fake"}
                self.resolve()

    def test_unknown_fields_rejected(self):
        self.plan["commands"][0]["skipOnFailure"] = True
        with self.assertRaises(ValueError):
            self.resolve()

    def test_bool_or_negative_test_minimum_rejected(self):
        for value in (True, False, -1, 1.0, "8"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.plan["commands"][0]["minimumTests"] = value
                self.resolve()

    def test_invalid_timeout_rejected(self):
        for value in (True, 0, -1, 21601, float("nan")):
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.plan["commands"][0]["timeoutSeconds"] = value
                self.resolve()

    def test_redirected_working_directory_rejected(self):
        (self.root / "redirect").symlink_to(self.root.parent, target_is_directory=True)
        self.plan["commands"][0]["cwd"] = "redirect"
        with self.assertRaises(ValueError):
            self.resolve()

    def test_parent_working_directory_rejected(self):
        self.plan["commands"][0]["cwd"] = ".."
        with self.assertRaises(ValueError):
            self.resolve()

    def test_duplicate_evidence_basename_rejected(self):
        self.plan["evidence"] = ["/tmp/a/report.json", "/tmp/b/report.json"]
        with self.assertRaises(ValueError):
            self.resolve()

    def test_evidence_cannot_modify_checkout(self):
        self.plan["evidence"] = [str(self.root / "report.json")]
        with self.assertRaises(ValueError):
            self.resolve()

    def test_unresolved_variable_rejected(self):
        self.plan["commands"][0]["command"] = ["$UNKNOWN_TOOL"]
        with self.assertRaises(KeyError):
            self.resolve()

    def test_duplicate_json_field_rejected(self):
        path = self.root / "plan.json"
        path.write_text('{"schema":"one","schema":"two"}')
        with self.assertRaises(ValueError):
            load_plan(path, self.root, self.env)

    def test_oversized_plan_rejected_before_parse(self):
        path = self.root / "plan.json"
        with path.open("wb") as stream:
            stream.truncate(1024 * 1024 + 1)
        with self.assertRaises(ValueError):
            load_plan(path, self.root, self.env)


class RecordBindingTests(unittest.TestCase):
    setUp = reference_tests.ManifestTests.setUp
    collect = reference_tests.ManifestTests.collect

    def invalid(self):
        self.assertEqual(self.collect()["status"], "evidence_invalid")

    def test_weaker_command_cannot_borrow_success(self):
        self.record["command"] = ["true"]
        self.invalid()

    def test_test_filter_change_rejected(self):
        self.record["command"] = [*self.expected["command"], "nonexistent_test"]
        self.invalid()

    def test_wrong_cwd_rejected(self):
        self.record["working_directory"] = "/tmp/another-checkout"
        self.invalid()

    def test_weaker_minimum_rejected(self):
        self.record["minimum_tests"] = 0
        self.invalid()

    def test_missing_minimum_rejected(self):
        del self.record["minimum_tests"]
        self.invalid()

    def test_workload_digest_drift_rejected(self):
        altered = {**self.expected, "environment": {"HEPTA_COGNITIVE_PERF_RECORDS": "1"}}
        self.record["command_spec_sha256"] = spec_sha256(altered)
        self.invalid()

    def test_timeout_drift_rejected(self):
        self.record["timeout_seconds"] = 9000
        self.invalid()

    def test_missing_spec_binding_rejected(self):
        del self.record["command_spec_sha256"]
        self.invalid()

    def test_inflated_test_counter_rejected(self):
        self.record["observed_passed_tests"] = 800
        self.invalid()

    def test_bool_test_counter_rejected(self):
        self.record["observed_failed_tests"] = False
        self.invalid()

    def test_boolean_exit_does_not_mean_success(self):
        self.record["command_exit_code"] = False
        self.assertNotEqual(self.collect()["status"], "passed")

    def test_no_plan_is_diagnostic_only(self):
        self.path.write_text(json.dumps(self.record))
        self.assertEqual(load_record(self.path, self.context)["status"], "evidence_invalid")

    def test_symlink_record_rejected(self):
        target = self.path.parent / "other.json"
        target.write_text(json.dumps(self.record))
        self.path.symlink_to(target)
        self.assertEqual(load_record(self.path, self.context, self.expected)["status"], "evidence_invalid")

    def test_fifo_record_rejected_without_waiting(self):
        os.mkfifo(self.path)
        self.assertEqual(load_record(self.path, self.context, self.expected)["status"], "evidence_invalid")

    def test_log_hardlink_rejected(self):
        os.link(self.log, self.log.with_name("duplicate.log"))
        self.invalid()

    def test_duplicate_record_fields_rejected(self):
        content = json.dumps(self.record)
        self.path.write_text(content[:-1] + ',"status":"passed"}')
        self.assertEqual(load_record(self.path, self.context, self.expected)["status"], "evidence_invalid")


class RunnerManifestTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix="cognitive-plan-")
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name).resolve()
        self.repo = self.root / "repo"
        (self.repo / "scripts").mkdir(parents=True)
        for name in ("cognitive_store_plan.py", "cognitive_store_qualify.py",
                     "cognitive_qualification_manifest.py", "hepta_ci_exec.py"):
            shutil.copyfile(SCRIPTS / name, self.repo / "scripts" / name)
        workflow = self.repo / ".github/workflows/cognitive-store-qualification.yml"
        workflow.parent.mkdir(parents=True)
        workflow.write_text("name: fixture-only\n")
        self.plan_path = self.repo / PLAN
        self.plan_path.parent.mkdir(parents=True)
        code = ("import unittest\nclass Smoke(unittest.TestCase):\n"
                " def test_one(self): self.assertEqual(1+1,2)\n"
                " def test_two(self): self.assertNotEqual(1,2)\n"
                "unittest.main()\n")
        self.plan = plan_for([sys.executable, "-c", code])
        self.plan["commands"][0]["minimumTests"] = 2
        self.git("init", "-q")
        self.git("config", "user.name", "fixture")
        self.git("config", "user.email", "fixture@example.invalid")
        self.records = self.root / "records"
        self.output = self.root / "manifest.json"
        self.commit_plan()

    def git(self, *args):
        return subprocess.check_output(["git", "-C", str(self.repo), *args],
                                       text=True, stderr=subprocess.PIPE).strip()

    def commit_plan(self):
        self.plan_path.write_text(json.dumps(self.plan))
        self.git("add", ".")
        self.git("commit", "-qm", "fixture plan")
        head = self.git("rev-parse", "HEAD")
        self.env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1", "SOURCE_SHA": head,
                    "BASE_SHA": head, "TESTED_SHA": head, "HEPTA_CI_LANE": "source-head",
                    "GITHUB_RUN_ID": "123", "GITHUB_RUN_ATTEMPT": "1", "GITHUB_JOB": "fixture",
                    "RUNNER_TEMP": str(self.root), "COGNITIVE_NATIVE_READY": "true"}

    def run_script(self, name, *args):
        return subprocess.run([sys.executable, str(self.repo / "scripts" / name), *map(str, args)],
                              cwd=self.repo, env=self.env, capture_output=True, text=True, timeout=20)

    def execute(self):
        return self.run_script("cognitive_store_qualify.py", "--plan", self.plan_path,
                               "--records", self.records)

    def collect(self, plan_path=None):
        return self.run_script("cognitive_qualification_manifest.py", "--plan", plan_path or self.plan_path,
                               "--records", self.records, "--output", self.output)

    def test_real_runner_and_committed_plan_complete(self):
        result = self.execute()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        result = self.collect()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        receipt = json.loads(self.output.read_text())
        self.assertEqual(receipt["result"], "terminal-success")
        self.assertEqual(receipt["commands"][0]["observedPassedTests"], 2)
        self.assertIs(receipt["targetHostQualified"], False)

    def test_actual_weaker_command_fails_collection(self):
        specs, _ = load_plan(self.plan_path, self.repo, self.env)
        self.env[SPEC_ENV] = spec_sha256(specs[0])
        result = self.run_script("hepta_ci_exec.py", "--output", self.records / "checks.json",
                                 "--timeout-seconds", 20, "--", sys.executable, "-c", "pass")
        self.assertEqual(result.returncode, 0, result.stderr)
        result = self.collect()
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertEqual(json.loads(self.output.read_text())["commands"][0]["status"], "evidence_invalid")

    def test_external_plan_is_not_committed_evidence(self):
        self.assertEqual(self.execute().returncode, 0)
        external = self.root / "uncommitted.json"
        external.write_bytes(self.plan_path.read_bytes())
        self.assertEqual(self.collect(external).returncode, 1)
        self.assertIn("canonical committed plan", self.output.read_text())

    def test_uncommitted_plan_never_dispatches(self):
        self.plan_path.write_text(self.plan_path.read_text() + "\n")
        result = self.execute()
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(self.records.exists())

    def test_malformed_late_entry_cannot_dispatch_first_command(self):
        self.plan["commands"].append({**self.plan["commands"][0], "record": "later.json",
                                      "env": {"SOURCE_SHA": "forged"}})
        self.commit_plan()
        result = self.execute()
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(self.records.exists())

    def test_native_preparation_failure_preserves_nonexecution(self):
        self.plan["commands"][0]["native"] = True
        self.commit_plan()
        self.env["COGNITIVE_NATIVE_READY"] = "false"
        self.assertEqual(self.execute().returncode, 1)
        self.assertEqual(self.collect().returncode, 1)
        self.assertEqual(json.loads(self.output.read_text())["commands"][0]["status"], "not_executed")

    def test_missing_plan_cannot_be_terminal_success(self):
        self.assertEqual(self.execute().returncode, 0)
        result = self.run_script("cognitive_qualification_manifest.py", "--required", "checks.json",
                                 "--records", self.records, "--output", self.output)
        self.assertEqual(result.returncode, 1)
        self.assertIn("committed qualification plan is required", self.output.read_text())

    def test_test_counters_cannot_override_actual_log(self):
        self.assertEqual(self.execute().returncode, 0)
        path = self.records / "checks.json"
        record = json.loads(path.read_text())
        record["observed_passed_tests"] = 200
        path.write_text(json.dumps(record))
        self.assertEqual(self.collect().returncode, 1)
        self.assertIn("differs from retained log", self.output.read_text())

    def test_valid_two_parent_synthetic_merge_is_checked(self):
        base = self.env["BASE_SHA"]
        (self.repo / "new-source-file").write_text("source change\n")
        self.git("add", ".")
        self.git("commit", "-qm", "source")
        source = self.git("rev-parse", "HEAD")
        tree = self.git("merge-tree", "--write-tree", base, source)
        merge = self.git("commit-tree", tree, "-p", base, "-p", source, "-m", "synthetic")
        self.git("checkout", "-q", "--detach", merge)
        self.env.update(SOURCE_SHA=source, TESTED_SHA=merge, HEPTA_CI_LANE="base-merge")
        result = self.execute()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        result = self.collect()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(json.loads(self.output.read_text())["parents"], [base, source])


if __name__ == "__main__":
    unittest.main()
