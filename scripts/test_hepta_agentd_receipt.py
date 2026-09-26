"""Real subprocess/temporary-Git tests; these do not qualify the Rust daemon."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from scripts.hepta_agentd_receipt import REQUIRED_STEPS, fingerprint, validate_steps

SCRIPT = Path(__file__).with_name("hepta_agentd_receipt.py")


class ReceiptTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.repo = self.root / "repo"
        self.repo.mkdir()
        self.git("init", "-q")
        self.git("config", "user.name", "Receipt test")
        self.git("config", "user.email", "receipt@example.invalid")
        (self.repo / "source").write_text("initial\n")
        self.git("add", "source")
        self.git("commit", "-qm", "fixture")
        self.sha = self.git("rev-parse", "HEAD")
        self.binary = self.root / "fixture"
        self.binary.write_bytes(b"#!/bin/sh\nexit 0\n")
        self.binary.chmod(0o700)
        self.output = self.root / "receipts"
        self.steps = {name: {"outcome": "success", "conclusion": "success"} for name in REQUIRED_STEPS}
        self.env = {**os.environ, "SOURCE_SHA": self.sha, "EXPECTED_SHA": self.sha,
                    "BASE_SHA": self.sha, "GITHUB_RUN_ID": "1", "GITHUB_RUN_ATTEMPT": "1",
                    "RUNNER_OS": "Linux", "RUNNER_ARCH": "X64", "HEPTA_CI_LANE": "source-head"}

    def git(self, *args):
        return subprocess.check_output(["git", *args], cwd=self.repo, text=True, stderr=subprocess.PIPE).strip()

    def run_receipt(self, phase):
        return subprocess.run(
            [sys.executable, str(SCRIPT), phase, "--directory", str(self.output), "--binary", str(self.binary)],
            env={**self.env, "AGENTD_STEPS": json.dumps(self.steps)}, cwd=self.repo,
            capture_output=True, text=True, timeout=10,
        )

    def capture(self):
        result = self.run_receipt("capture")
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_pass_binds_fixture_bytes_and_current_commit(self):
        self.capture()
        result = self.run_receipt("finish")
        self.assertEqual(result.returncode, 0, result.stderr)
        record = json.loads((self.output / "qualification.json").read_text())
        self.assertEqual(record["context"]["EXPECTED_SHA"], self.sha)
        self.assertEqual(record["fixture"]["sha256"], hashlib.sha256(self.binary.read_bytes()).hexdigest())
        self.assertEqual(record["status"], "passed")
        self.assertFalse(record["production_activation"])

    def test_every_missing_skipped_failed_or_masked_step_rejects(self):
        for name in REQUIRED_STEPS:
            for outcome in ("skipped", "failure", "cancelled", None):
                with self.subTest(step=name, outcome=outcome):
                    steps = {**self.steps, name: {"outcome": outcome, "conclusion": "success"}}
                    self.assertTrue(validate_steps(steps))
            steps = dict(self.steps)
            del steps[name]
            self.assertTrue(validate_steps(steps))

    def test_missing_capture_writes_failed_receipt(self):
        self.assertNotEqual(self.run_receipt("finish").returncode, 0)
        self.assertEqual(json.loads((self.output / "qualification.json").read_text())["status"], "failed")

    def test_fixture_mutation_rejects(self):
        self.capture()
        self.binary.write_bytes(b"#!/bin/sh\nexit 7\n")
        self.assertNotEqual(self.run_receipt("finish").returncode, 0)

    def test_dirty_source_rejects(self):
        self.capture()
        (self.repo / "source").write_text("changed\n")
        self.assertNotEqual(self.run_receipt("finish").returncode, 0)

    def test_untracked_source_rejects(self):
        (self.repo / "untracked").write_text("not in exact SHA\n")
        self.assertNotEqual(self.run_receipt("capture").returncode, 0)

    def test_wrong_sha_rejects(self):
        self.env["EXPECTED_SHA"] = "f" * 40
        self.assertNotEqual(self.run_receipt("capture").returncode, 0)

    def test_old_attempt_cannot_be_reused(self):
        self.capture()
        self.env["GITHUB_RUN_ATTEMPT"] = "2"
        self.assertNotEqual(self.run_receipt("finish").returncode, 0)

    def test_existing_receipt_cannot_be_overwritten(self):
        self.capture()
        before = (self.output / "fixture.json").read_bytes()
        self.assertNotEqual(self.run_receipt("capture").returncode, 0)
        self.assertEqual((self.output / "fixture.json").read_bytes(), before)

    def test_symlink_and_nonexecutable_reject(self):
        link = self.root / "link"
        link.symlink_to(self.binary)
        with self.assertRaises(OSError):
            fingerprint(link)
        self.binary.chmod(0o600)
        with self.assertRaises(ValueError):
            fingerprint(self.binary)

    def test_receipts_inside_checkout_reject(self):
        self.output = self.repo / "receipts"
        self.assertNotEqual(self.run_receipt("capture").returncode, 0)
        self.assertFalse(self.output.exists())

    def test_false_green_conclusion_rejects(self):
        self.capture()
        self.steps["owner_libraries"] = {"outcome": "failure", "conclusion": "success"}
        self.assertNotEqual(self.run_receipt("finish").returncode, 0)

    def merge_fixture(self):
        tree = self.git("rev-parse", "HEAD^{tree}")
        source = self.git("commit-tree", tree, "-p", self.sha, "-m", "source")
        merged = self.git("commit-tree", tree, "-p", self.sha, "-p", source, "-m", "merge")
        self.git("checkout", "-q", "--detach", merged)
        self.env.update(SOURCE_SHA=source, EXPECTED_SHA=merged, HEPTA_CI_LANE="merge-candidate")
        return source, merged

    def test_exact_merge_is_independently_bound(self):
        self.merge_fixture()
        self.capture()
        self.assertEqual(self.run_receipt("finish").returncode, 0)

    def test_different_merge_parent_rejects(self):
        self.merge_fixture()
        self.env["BASE_SHA"] = "f" * 40
        self.assertNotEqual(self.run_receipt("capture").returncode, 0)

    def test_require_native_overrides_only_explicit_opt_in(self):
        source, merged = self.merge_fixture()
        planner = SCRIPT.with_name("hepta_ci_candidate.py")
        args = [sys.executable, str(planner), "--source", source, "--tested", merged,
                "--base", self.sha, "--lane", "base-merge"]
        for extra, expected in (([], False), (["--require-native"], True)):
            result = subprocess.run(args + extra, cwd=self.repo, text=True, capture_output=True, timeout=10)
            self.assertEqual(result.returncode, 0, result.stderr)
            plan = json.loads(result.stdout)
            self.assertEqual(plan["native_execution_required"], expected)
            self.assertEqual(plan["requires_source_head_success"], not expected)

    def test_no_step_object_rejects(self):
        for malformed in (None, [], "success"):
            with self.assertRaises(ValueError):
                validate_steps(malformed)


if __name__ == "__main__":
    unittest.main()
