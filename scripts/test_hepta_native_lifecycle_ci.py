"""Real Git and receipt validation checks, not native execution substitutes."""

import copy
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch
import xml.etree.ElementTree as ET

import hepta_native_lifecycle_ci as ci

ROOT = Path(__file__).resolve().parents[1]


class JunitCollectionTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.report = (
            self.root / "apps/hepta-native/target/nextest/native-lifecycle/junit.xml"
        )
        self.report.parent.mkdir(parents=True)
        self.evidence = self.root / "evidence"
        self.evidence.mkdir()
        self.env = {
            **os.environ,
            "CARGO_TARGET_DIR": str(self.root / "separate-build-target"),
            "NATIVE_EVIDENCE": str(self.evidence),
        }

    def workflow_shell(self, name):
        workflow = (ROOT / ci.WORKFLOW).read_text()
        block = workflow.split(f"      - name: {name}\n", 1)[1].split(
            "      - name:", 1
        )[0]
        script = block.split("        run: |\n", 1)[1]
        return "\n".join(line[10:] for line in script.splitlines())

    def collect(self):
        script = self.workflow_shell("Retain JUnit and verify exact test coverage")
        # Execute the actual shell copy. Routing bytes are not synthetic JUnit
        # evidence, and the production verifier is never replaced or bypassed.
        copy_line = next(line for line in script.splitlines() if line.startswith("cp "))
        return subprocess.run(
            ["bash", "-euo", "pipefail", "-c", copy_line],
            cwd=self.root,
            env=self.env,
            capture_output=True,
        )

    def test_pinned_workspace_report_is_collected_with_separate_build_target(self):
        self.report.write_bytes(b"path-routing fixture bytes; not a JUnit report")
        result = self.collect()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            (self.evidence / "junit.xml").read_bytes(), self.report.read_bytes()
        )

    def test_missing_workspace_report_cannot_fall_back_to_build_target(self):
        wrong = (
            Path(self.env["CARGO_TARGET_DIR"]) / "nextest/native-lifecycle/junit.xml"
        )
        wrong.parent.mkdir(parents=True)
        wrong.write_bytes(b"wrong-location fixture")
        self.assertNotEqual(self.collect().returncode, 0)
        self.assertFalse((self.evidence / "junit.xml").exists())

    def test_preexisting_report_or_dangling_symlink_rejects_before_tests(self):
        script = self.workflow_shell(
            "Run complete ordinary native tests without retries"
        )
        guard = script.split("python3 scripts/hepta_ci_exec.py", 1)[0]
        self.assertRegex(guard, r"test ! -e .*/junit\.xml")
        self.assertRegex(guard, r"test ! -L .*/junit\.xml")
        self.report.write_bytes(b"old report fixture")
        for dangling in (False, True):
            if dangling:
                self.report.unlink()
                self.report.symlink_to(self.root / "absent-old-target")
            result = subprocess.run(
                ["bash", "-c", guard],
                cwd=self.root,
                env=self.env,
                capture_output=True,
            )
            self.assertNotEqual(result.returncode, 0)
        self.report.unlink()
        result = subprocess.run(["bash", "-c", guard], cwd=self.root, env=self.env)
        self.assertEqual(result.returncode, 0)


class CoverageTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.xml = Path(self.directory.name) / "junit.xml"
        self.inventory = {
            "rust-suites": {},
            "test-count": len(ci.REQUIRED | ci.IGNORED),
        }
        for binary, name in ci.REQUIRED | ci.IGNORED:
            suite = self.inventory["rust-suites"].setdefault(
                binary, {"status": "listed", "testcases": {}}
            )
            suite["testcases"][name] = {
                "ignored": (binary, name) in ci.IGNORED,
                "filter-match": {"status": "matches"},
            }
        self.junit = ET.Element("testsuites")
        for binary, name in sorted(ci.REQUIRED):
            ET.SubElement(self.junit, "testcase", classname=binary, name=name)

    def verify(self):
        ET.ElementTree(self.junit).write(self.xml)
        return ci.verify_tests(self.inventory, self.xml)

    def test_complete_executed_inventory_keeps_exclusions_explicit(self):
        result = self.verify()
        self.assertEqual(result["passed"], len(ci.REQUIRED))
        self.assertEqual(result["ignored"], [list(key) for key in sorted(ci.IGNORED)])

    def test_missing_ordinary_execution_is_rejected(self):
        self.junit.remove(self.junit[0])
        with self.assertRaisesRegex(ValueError, "differ from inventory"):
            self.verify()

    def test_failed_skipped_flaky_and_duplicate_execution_are_rejected(self):
        for marker in ("failure", "error", "skipped", "flakyFailure", "rerunFailure"):
            with self.subTest(marker=marker):
                child = ET.SubElement(self.junit[0], marker)
                with self.assertRaisesRegex(ValueError, "failed, skipped or retried"):
                    self.verify()
                self.junit[0].remove(child)
        self.junit.append(copy.deepcopy(self.junit[0]))
        with self.assertRaisesRegex(ValueError, "duplicate"):
            self.verify()

    def test_new_ignored_case_cannot_hide_a_regression(self):
        binary, name = sorted(ci.REQUIRED)[0]
        self.inventory["rust-suites"][binary]["testcases"][name]["ignored"] = True
        with self.assertRaisesRegex(ValueError, "ignored tests"):
            self.verify()

    def test_another_ignored_storage_child_is_not_admitted_by_prefix(self):
        name = "storage_qualification_tests::process_samples::another_worker"
        self.inventory["rust-suites"]["hepta-native"]["testcases"][name] = {
            "ignored": True,
            "filter-match": {"status": "matches"},
        }
        self.inventory["test-count"] += 1
        with self.assertRaisesRegex(ValueError, "ignored tests"):
            self.verify()

    def test_required_readiness_cannot_disappear_from_both_files(self):
        case = self.junit[0]
        del self.inventory["rust-suites"][case.get("classname")]["testcases"][
            case.get("name")
        ]
        self.inventory["test-count"] -= 1
        self.junit.remove(case)
        with self.assertRaisesRegex(ValueError, "required lifecycle"):
            self.verify()

    def test_filtered_inventory_is_rejected(self):
        binary, name = sorted(ci.REQUIRED)[0]
        self.inventory["rust-suites"][binary]["testcases"][name]["filter-match"] = {
            "status": "mismatch"
        }
        with self.assertRaisesRegex(ValueError, "filtered out"):
            self.verify()


class SubjectTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name) / "repo"
        self.root.mkdir()
        self.previous = Path.cwd()
        os.chdir(self.root)
        self.addCleanup(os.chdir, self.previous)
        self.run_git("init", "-q")
        self.run_git("config", "user.name", "Fixture")
        self.run_git("config", "user.email", "fixture@invalid")
        workflow = self.root / ci.WORKFLOW
        workflow.parent.mkdir(parents=True)
        workflow.write_text("name: fixture workflow\n")
        self.run_git("add", ".")
        self.run_git("commit", "-qm", "base")
        self.base = ci.git("rev-parse", "HEAD")
        (self.root / "changed").write_text("lifecycle extraction fixture\n")
        self.run_git("add", ".")
        self.run_git("commit", "-qm", "head")
        self.source = ci.git("rev-parse", "HEAD")
        self.event = Path(self.directory.name) / "event.json"
        self.event.write_text(
            json.dumps(
                {
                    "number": 1338,
                    "pull_request": {
                        "base": {"sha": self.base, "ref": ci.BASE_REF},
                        "head": {"sha": self.source},
                    },
                }
            )
        )
        self.env = {
            "SOURCE_SHA": self.source,
            "BASE_SHA": self.base,
            "TESTED_SHA": self.source,
            "WORKFLOW_SHA": self.source,
            "HEPTA_CI_LANE": "source-head",
            "GITHUB_EVENT_NAME": "pull_request",
            "GITHUB_EVENT_PATH": str(self.event),
            "GITHUB_RUN_ID": "123",
            "GITHUB_RUN_ATTEMPT": "1",
            "RUNNER_OS": "Linux",
            "RUNNER_ARCH": "X64",
            "ImageOS": "ubuntu24",
            "ImageVersion": "fixture",
        }
        self.enterContext(patch.object(ci, "BASE", self.base))
        self.enterContext(patch.dict(os.environ, self.env))

    def run_git(self, *args):
        subprocess.run(
            ["git", *args], check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE
        )

    def test_real_head_and_reusable_merge_action_have_distinct_exact_identity(self):
        head = ci.subject()
        action = (ROOT / ".github/actions/hepta-synthetic-merge/action.yml").read_text()
        script = "\n".join(
            line[8:] for line in action.split("      run: |\n", 1)[1].splitlines()
        )
        subprocess.run(
            ["bash", "-c", script],
            check=True,
            capture_output=True,
            env={
                **os.environ,
                "PR_NUMBER": "1338",
                "AUTHOR_NAME": "Native lifecycle CI",
                "AUTHOR_EMAIL": "native-lifecycle@invalid",
                "MESSAGE": "Synthetic native lifecycle merge",
                "GITHUB_OUTPUT": str(Path(self.directory.name) / "output"),
            },
        )
        os.environ.update(
            TESTED_SHA=ci.git("rev-parse", "HEAD"), HEPTA_CI_LANE="base-merge"
        )
        merge = ci.subject()
        self.assertNotEqual(merge["testedSha"], head["testedSha"])
        self.assertEqual(merge["git"]["tree"], head["git"]["tree"])
        self.assertEqual(merge["git"]["parents"], [self.base, self.source])

    def test_changed_pr_base_and_foreign_head_reject(self):
        for name, value in (("BASE_SHA", "f" * 40), ("SOURCE_SHA", "e" * 40)):
            with self.subTest(name=name), patch.dict(os.environ, {name: value}):
                with self.assertRaisesRegex(ValueError, "source/base differs"):
                    ci.subject()

    def test_dirty_source_and_wrong_workflow_reject(self):
        (self.root / "changed").write_text("uncommitted\n")
        with self.assertRaisesRegex(ValueError, "clean and exactly"):
            ci.subject()
        self.run_git("checkout", "--", "changed")
        (self.root / ci.WORKFLOW).write_text("name: changed workflow\n")
        self.run_git("add", ".")
        self.run_git("commit", "-qm", "changed workflow")
        os.environ["WORKFLOW_SHA"] = ci.git("rev-parse", "HEAD")
        self.run_git("checkout", "--detach", self.source)
        with self.assertRaisesRegex(ValueError, "workflow bytes differ"):
            ci.subject()

    def test_execution_receipt_requires_exact_run_exit_source_and_log(self):
        bound = ci.subject()
        directory = Path(self.directory.name)
        log = directory / "command.log"
        log.write_bytes(b"actual retained command output\n")
        record = {
            "source_sha": self.source,
            "base_sha": self.base,
            "tested_sha": self.source,
            "lane": "source-head",
            "run_id": "123",
            "run_attempt": "1",
            "status": "passed",
            "exit_code": 0,
            "command_exit_code": 0,
            "before": bound["git"],
            "after": bound["git"],
            "command": ci.COMMANDS["compile"],
            "log_file": log.name,
            "log_sha256": ci.sha(log.read_bytes()),
        }
        ci.verify_record(record, bound, directory, "compile")
        for key, value in (
            ("run_attempt", "2"),
            ("command_exit_code", 1),
            ("status", "running"),
            ("log_sha256", "0" * 64),
            ("command", ["echo", "compiled"]),
            ("after", {**bound["git"], "dirty": True}),
        ):
            with self.subTest(key=key), self.assertRaises(ValueError):
                ci.verify_record({**record, key: value}, bound, directory, "compile")


if __name__ == "__main__":
    unittest.main()
