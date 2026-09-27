"""Tests of build orchestration and binding; these do not execute Rust qualification."""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

from scripts import hepta_agentd_product_prerequisite as subject


@unittest.skipUnless(os.name == "posix", "Linux/macOS qualification helper")
class PrerequisiteTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name).resolve()
        self.root = self.directory / "repo"
        self.root.mkdir()
        self.target = self.directory / "target"
        self.target.mkdir()
        self.binary = self.target / "hepta-agentd"
        self.binary.write_bytes(b"#!/bin/sh\nexit 0\n")
        self.binary.chmod(0o700)
        self.log = self.directory / "cargo.jsonl"
        self.artifact = {
            "reason": "compiler-artifact",
            "target": {"name": "hepta-agentd", "kind": ["bin"]},
            "manifest_path": str(self.root / "codex-rs/hepta-agentd/Cargo.toml"),
            "profile": {"test": False}, "executable": str(self.binary),
        }

    def events(self, *events):
        self.log.write_text("".join(json.dumps(item) + "\n" for item in events))

    def select(self):
        return subject.select_artifact(self.log, self.root, self.target)

    def test_selects_only_successful_current_build_artifact(self):
        self.events(self.artifact, {"reason": "build-finished", "success": True})
        self.assertEqual(self.select(), self.binary)

    def test_existing_sibling_binary_is_not_evidence(self):
        self.events({"reason": "build-finished", "success": True})
        with self.assertRaises(ValueError):
            self.select()

    def test_requires_successful_build_finished(self):
        for value in (False, None, 1, "true"):
            self.events(self.artifact, {"reason": "build-finished", "success": value})
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.select()

    def test_rejects_duplicate_artifacts(self):
        self.events(self.artifact, self.artifact, {"reason": "build-finished", "success": True})
        with self.assertRaises(ValueError):
            self.select()

    def test_rejects_foreign_manifest(self):
        self.events({**self.artifact, "manifest_path": "/foreign/Cargo.toml"},
                    {"reason": "build-finished", "success": True})
        with self.assertRaises(ValueError):
            self.select()

    def test_rejects_test_harness_instead_of_product(self):
        self.events({**self.artifact, "profile": {"test": True}},
                    {"reason": "build-finished", "success": True})
        with self.assertRaises(ValueError):
            self.select()

    def test_rejects_binary_outside_build_directory(self):
        with self.assertRaises(ValueError):
            self.events(self.artifact, {"reason": "build-finished", "success": True})
            subject.select_artifact(self.log, self.root, self.directory / "elsewhere")

    def test_rejects_symlink_and_nonexecutable_artifacts(self):
        link = self.target / "linked"
        link.symlink_to(self.binary)
        self.events({**self.artifact, "executable": str(link)},
                    {"reason": "build-finished", "success": True})
        with self.assertRaises(ValueError):
            self.select()
        self.binary.chmod(0o600)
        self.events(self.artifact, {"reason": "build-finished", "success": True})
        with self.assertRaises(ValueError):
            self.select()

    def test_rejects_missing_and_malformed_cargo_messages(self):
        for text in ("", "not-json\n", '{"reason":"build-finished"}\n'):
            self.log.write_text(text)
            with self.subTest(text=text), self.assertRaises(ValueError):
                self.select()

    def test_atomic_publish_does_not_leave_temporary_files(self):
        path = self.directory / "receipt.json"
        subject.publish(path, {"status": "running"})
        subject.publish(path, {"status": "failed"})
        self.assertEqual(json.loads(path.read_text()), {"status": "failed"})
        self.assertEqual(list(self.directory.glob(".receipt-*")), [])

    def test_run_preserves_failure_and_bounds_logs(self):
        failure = subject.run_build([sys.executable, "-c", "raise SystemExit(3)"],
                                    self.root, self.directory, 3)
        self.assertEqual(failure["status"], "failed")
        self.assertEqual(failure["exitCode"], 3)
        overflow = subject.run_build([sys.executable, "-c", "print('x'*8192)"],
                                     self.root, self.directory, 3, 128)
        self.assertEqual(overflow["status"], "output_limit_exceeded")
        self.assertLessEqual((self.directory / "cargo.jsonl").stat().st_size, 128)

    def test_timeout_cannot_become_pass(self):
        result = subject.run_build([sys.executable, "-c", "import time; time.sleep(30)"],
                                   self.root, self.directory, 0.15)
        self.assertEqual(result["status"], "timeout")
        self.assertNotEqual(result["exitCode"], 0)

    def test_terminates_descendant_holding_parent_pipes(self):
        pid_path = self.directory / "child.pid"
        program = (
            "import subprocess,sys,pathlib; "
            "p=subprocess.Popen([sys.executable,'-c','import time; time.sleep(30)']); "
            f"pathlib.Path({str(pid_path)!r}).write_text(str(p.pid))"
        )
        result = subject.run_build([sys.executable, "-S", "-c", program],
                                   self.root, self.directory, 2)
        self.assertEqual(result["status"], "timeout")
        pid = int(pid_path.read_text())
        # An orphan may briefly be a zombie until the host reaper runs; zombies
        # are terminated, not running descendants. This check is Linux-specific.
        if Path("/proc").is_dir():
            status = Path(f"/proc/{pid}/stat")
            deadline = time.monotonic() + 1
            while status.exists() and not status.read_text().split(") ")[1].startswith("Z"):
                self.assertLess(time.monotonic(), deadline, "descendant survived group termination")
                time.sleep(0.01)

    def test_exact_identity_rejects_dirty_and_wrong_head(self):
        project = self.root / "codex-rs"
        project.mkdir()
        (project / "Cargo.lock").write_text("fixture-lock\n")
        (project / "rust-toolchain.toml").write_text('[toolchain]\nchannel="fixture"\n')
        subprocess.run(["git", "init", "-q", str(self.root)], check=True)
        subprocess.run(["git", "-C", str(self.root), "add", "."], check=True)
        subprocess.run(["git", "-C", str(self.root), "-c", "user.name=Fixture",
                        "-c", "user.email=fixture@example.invalid", "commit", "-qm", "fixture"], check=True)
        head = subprocess.check_output(["git", "-C", str(self.root), "rev-parse", "HEAD"], text=True).strip()
        self.assertEqual(subject.identity(self.root, head)["commit"], head)
        with self.assertRaises(ValueError):
            subject.identity(self.root, "a" * 40)
        (project / "Cargo.lock").write_text("changed\n")
        with self.assertRaises(ValueError):
            subject.identity(self.root, head)

    def test_failed_build_does_not_export_binary_or_qualify(self):
        output = self.directory / "evidence"
        env_file = self.directory / "env"
        with patch.object(subject, "identity", return_value={"commit": "a" * 40}), \
             patch.object(subject, "run_build", return_value={"status": "failed", "exitCode": 1}):
            self.assertEqual(subject.build(self.root, "a" * 40, output, self.target, 3, env_file), 1)
        self.assertFalse(env_file.exists())
        receipt = json.loads((output / "build-receipt.json").read_text())
        self.assertEqual(receipt["status"], "failed")
        for flag in ("testQualification", "deploymentQualification", "independentAcceptance"):
            self.assertIs(receipt[flag], False)

    def test_source_drift_after_build_prevents_export(self):
        output = self.directory / "evidence"
        env_file = self.directory / "env"
        with patch.object(subject, "identity", side_effect=[{"tree": "a"}, {"tree": "b"}]), \
             patch.object(subject, "run_build", return_value={"status": "passed", "exitCode": 0}), \
             patch.object(subject, "select_artifact", return_value=self.binary):
            self.assertEqual(subject.build(self.root, "a" * 40, output, self.target, 3, env_file), 1)
        self.assertFalse(env_file.exists())

    def test_success_exports_exact_binary_without_granting_authority(self):
        output = self.directory / "evidence"
        env_file = self.directory / "env"
        with patch.object(subject, "identity", return_value={"tree": "a"}), \
             patch.object(subject, "run_build", return_value={"status": "passed", "exitCode": 0}), \
             patch.object(subject, "select_artifact", return_value=self.binary):
            self.assertEqual(subject.build(self.root, "a" * 40, output, self.target, 3, env_file), 0)
        self.assertEqual(env_file.read_text(), f"HEPTA_AGENTD_TEST_BIN={self.binary}\n")
        receipt = json.loads((output / "build-receipt.json").read_text())
        self.assertEqual(receipt["artifact"]["sha256"], subject.digest_file(self.binary)["sha256"])
        self.assertNotIn("--features", receipt["command"])
        self.assertIs(receipt["testQualification"], False)

    def test_output_cannot_mutate_candidate(self):
        with self.assertRaises(ValueError):
            subject.build(self.root, "a" * 40, self.root / "evidence", self.target, 3)


if __name__ == "__main__":
    unittest.main()
