"""Execute the workflow's Git construction shell against isolated repositories."""

import os
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import shutil
import tempfile
import textwrap
import unittest

WORKFLOW = (
    Path(__file__).resolve().parents[1]
    / ".github/workflows/ui-native-qualification.yml"
)


def shell_step(name: str) -> str:
    section = WORKFLOW.read_text(encoding="utf-8").split(f"      - name: {name}\n", 1)[
        1
    ]
    body = section.split("        run: |\n", 1)[1].split("      - ", 1)[0]
    return textwrap.dedent(body)


class PlatformConstructionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "repo"
        self.root.mkdir()
        self.output = Path(self.temp.name) / "evidence"
        self.git("init", "--quiet")
        self.git("config", "user.name", "fixture")
        self.git("config", "user.email", "fixture@example.invalid")
        (self.root / "source.rs").write_text("source\n", encoding="utf-8")
        self.git("add", ".")
        self.git("commit", "--quiet", "-m", "base")
        self.base = self.git("rev-parse", "HEAD").strip()
        (self.root / "source.rs").write_text("candidate\n", encoding="utf-8")
        self.git("add", ".")
        self.git("commit", "--quiet", "-m", "candidate")
        self.candidate = self.git("rev-parse", "HEAD").strip()

    def git(self, *args):
        return subprocess.check_output(["git", *args], cwd=self.root, text=True)

    def construct(self, kind):
        return subprocess.run(
            [
                "bash",
                "-c",
                shell_step("Construct exact head or fixed ordered-parent merge"),
            ],
            cwd=self.root,
            env={
                **os.environ,
                "CANDIDATE": self.candidate,
                "BASE": self.base,
                "KIND": kind,
                "NATIVE_OUTPUT_ROOT": str(self.output),
                "GITHUB_ENV": str(Path(self.temp.name) / "github-env"),
            },
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )

    def test_exact_head_records_evidence_without_dirtying_checkout(self):
        result = self.construct("head")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.git("rev-parse", "HEAD").strip(), self.candidate)
        self.assertEqual(self.git("status", "--porcelain"), "")
        self.assertIn(
            f"commit={self.candidate}",
            (self.output / "native-evidence/source.txt").read_text(),
        )

    def test_merge_preserves_ordered_parents_and_clean_checkout(self):
        result = self.construct("merge")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            self.git("show", "-s", "--format=%P", "HEAD").strip(),
            f"{self.base} {self.candidate}",
        )
        self.assertEqual(self.git("status", "--porcelain"), "")
        self.assertTrue((self.output / "native-evidence/source.txt").is_file())

    def test_dirty_source_is_still_rejected(self):
        (self.root / "source.rs").write_text("dirty source\n", encoding="utf-8")
        result = self.construct("head")
        self.assertNotEqual(result.returncode, 0)


class RepositoryAggregateTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.storage_root = self.root / "storage-bundle"
        self.storage_root.mkdir()
        self.env = {
            **os.environ,
            "CANDIDATE": "a" * 40,
            "BASE": "b" * 40,
            "IMPLEMENTATION": "a" * 40,
            "WORKFLOW_SHA": "d" * 40,
            "GITHUB_RUN_ID": "101",
            "GITHUB_RUN_ATTEMPT": "1",
            "PYTHONPATH": str(Path(__file__).resolve().parent),
        }
        platform = {
            "qualificationPassed": True,
            "candidateSha": self.env["CANDIDATE"],
            "baseSha": self.env["BASE"],
            "implementationSourceSha": self.env["IMPLEMENTATION"],
            "workflowSha": self.env["WORKFLOW_SHA"],
            "runId": "101",
            "runAttempt": "1",
        }
        self.write("native-aggregate/platform-qualification.json", platform)
        outcomes = {
            "schema": "hepta.ui-native-storage-job-outcomes.v1",
            "sourceSha": self.env["IMPLEMENTATION"],
            "candidateSha": self.env["CANDIDATE"],
            "workflowSha": self.env["WORKFLOW_SHA"],
            "runId": "101",
            "runAttempt": "1",
            "compile": "success",
            "active": "success",
            "retired": "success",
            "validate": "success",
        }
        self.write("storage-bundle/job-outcomes.json", outcomes)
        spec = importlib.util.spec_from_file_location(
            "storage_aggregate_fixture",
            Path(__file__).with_name("test_hepta_ui_native_storage.py"),
        )
        fixtures = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(fixtures)
        fixture = fixtures.StorageQualificationTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        fixture.validate()
        self.write("apps/hepta-native/STORAGE_BUDGETS.json", fixture.budgets)
        self.write("storage-bundle/active.json", fixture.active)
        self.write("storage-bundle/retired.json", fixture.retired)
        shutil.copyfile(fixture.trace, self.storage_root / "active.strace.1")
        qualification = fixtures.storage.validate_storage(
            self.root / "apps/hepta-native/STORAGE_BUDGETS.json",
            self.storage_root / "active.json",
            self.storage_root / "retired.json",
            self.storage_root / "active.strace",
            self.env["IMPLEMENTATION"],
        )
        self.write("storage-bundle/qualification.json", qualification)

    def write(self, relative, value):
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value), encoding="utf-8")

    def digest(self, relative):
        return hashlib.sha256((self.root / relative).read_bytes()).hexdigest()

    def mutate(self, relative, key, value):
        path = self.root / relative
        data = json.loads(path.read_text())
        data[key] = value
        self.write(relative, data)

    def aggregate(self):
        return subprocess.run(
            ["bash", "-c", shell_step("Bind platform aggregate and storage artifact")],
            cwd=self.root,
            env=self.env,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )

    def test_same_run_retained_storage_inputs_are_accepted(self):
        result = self.aggregate()
        self.assertEqual(result.returncode, 0, result.stderr)
        final = json.loads(
            (self.root / "native-aggregate/qualification-result.json").read_text()
        )
        self.assertEqual(
            final["storageJobOutcomesSha256"],
            self.digest("storage-bundle/job-outcomes.json"),
        )

    def test_foreign_attempt_storage_is_rejected(self):
        self.mutate("storage-bundle/job-outcomes.json", "runAttempt", "2")
        self.assertNotEqual(self.aggregate().returncode, 0)

    def test_failed_storage_stage_is_rejected(self):
        self.mutate("storage-bundle/job-outcomes.json", "validate", "failure")
        self.assertNotEqual(self.aggregate().returncode, 0)

    def test_modified_raw_storage_inputs_are_rejected(self):
        self.mutate("storage-bundle/active.json", "fixture", False)
        self.assertNotEqual(self.aggregate().returncode, 0)

    def test_modified_trace_is_rejected(self):
        (self.storage_root / "active.strace.1").write_text("modified", encoding="utf-8")
        self.assertNotEqual(self.aggregate().returncode, 0)

    def test_foreign_platform_implementation_is_rejected(self):
        self.mutate(
            "native-aggregate/platform-qualification.json",
            "implementationSourceSha",
            "e" * 40,
        )
        self.assertNotEqual(self.aggregate().returncode, 0)

    def test_forged_pass_and_rehashed_over_budget_samples_are_rejected(self):
        path = self.storage_root / "active.json"
        active = json.loads(path.read_text())
        active["freshProcessOpenSamplesMilliseconds"] = [3000] * 20
        active["freshProcessOpenP95Milliseconds"] = 3000
        for observation in active["openProcessSamples"]:
            observation["elapsedMilliseconds"] = 3000
        self.write("storage-bundle/active.json", active)
        qualification = json.loads(
            (self.storage_root / "qualification.json").read_text()
        )
        qualification["activeEvidence"]["measurements"] = active
        qualification["activeEvidence"]["sha256"] = self.digest(
            "storage-bundle/active.json"
        )
        self.write("storage-bundle/qualification.json", qualification)
        result = self.aggregate()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("open p95 exceeded", result.stderr)


if __name__ == "__main__":
    unittest.main()
