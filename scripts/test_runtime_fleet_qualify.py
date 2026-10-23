#!/usr/bin/env python3
"""Fault-injection tests of the receipt runner, never Rust/product evidence.

Cargo is deliberately replaced with an exit-17 fixture in isolated Git repos.
Every execution receipt produced by these tests must remain failed.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

RUNNER = Path(__file__).with_name("runtime_fleet_qualify.py")


class QualificationFaultTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "checkout"
        self.root.mkdir()
        (self.root / "scripts").mkdir()
        (self.root / "codex-rs").mkdir()
        (self.root / "codex-rs" / "fixture.txt").write_text("not a Rust workspace\n")
        shutil.copyfile(RUNNER, self.root / "scripts" / RUNNER.name)
        for name in ("test_runtime_fleet_status.py", "test_runtime_fleet_qualify.py"):
            (self.root / "scripts" / name).write_text("# Isolated runner fixture, not real module tests.\n")
        self.git("init", "-q")
        self.git("config", "user.name", "Qualification fault fixture")
        self.git("config", "user.email", "fixture@invalid.example")
        self.git("add", ".")
        self.git("commit", "-qm", "fixture base")
        self.base = self.git("rev-parse", "HEAD")
        (self.root / "source.txt").write_text("source\n")
        self.git("add", ".")
        self.git("commit", "-qm", "fixture source")
        self.source = self.git("rev-parse", "HEAD")
        self.output = Path(self.temp.name) / "evidence"
        fake_bin = Path(self.temp.name) / "fault-bin"
        fake_bin.mkdir()
        cargo = fake_bin / "cargo"
        cargo.write_text("#!/bin/sh\necho 'deliberate harness fault, not Cargo'\nexit 17\n")
        cargo.chmod(0o700)
        self.env = {key: value for key, value in os.environ.items() if not key.startswith("GITHUB_")}
        self.env["PATH"] = str(fake_bin) + os.pathsep + os.environ["PATH"]
        self.env["PYTHONDONTWRITEBYTECODE"] = "1"

    def git(self, *args):
        return subprocess.check_output(["git", *args], cwd=self.root, text=True, stderr=subprocess.DEVNULL).strip()

    def qualify(self, lane="exact-source", source=None, output=None):
        return subprocess.run(
            [sys.executable, str(self.root / "scripts" / RUNNER.name),
             "--source", source or self.source, "--base", self.base,
             "--lane", lane, "--output", str(output or self.output)],
            cwd=self.root, env=self.env, capture_output=True, text=True, check=False,
        )

    def test_failed_commands_cannot_become_a_passing_receipt(self):
        result = self.qualify()
        self.assertEqual(result.returncode, 1, result.stderr)
        receipt = json.loads((self.output / "receipt.json").read_text())
        self.assertFalse(receipt["passed"])
        self.assertFalse(receipt["product_execution_accepted"])
        self.assertFalse(receipt["production_release_approved"])
        self.assertEqual(receipt["source_commit"], self.source)
        self.assertTrue(receipt["clean_tree"])
        failures = [row for row in receipt["commands"] if row["command"][0] == "cargo"]
        self.assertTrue(failures)
        self.assertTrue(all(row["exit_code"] == 17 for row in failures))
        manifest = json.loads((self.output / "manifest.json").read_text())
        for name, digest in manifest.items():
            self.assertEqual(hashlib.sha256((self.output / name).read_bytes()).hexdigest(), digest)

    def test_wrong_source_is_rejected_before_execution(self):
        self.assertEqual(self.qualify(source="0" * 40).returncode, 2)
        self.assertFalse(self.output.exists())

    def test_dirty_checkout_is_rejected_before_execution(self):
        (self.root / "source.txt").write_text("not the committed source\n")
        self.assertEqual(self.qualify().returncode, 2)
        self.assertFalse(self.output.exists())

    def test_output_inside_source_is_rejected(self):
        output = self.root / "receipt-output"
        self.assertEqual(self.qualify(output=output).returncode, 2)
        self.assertFalse(output.exists())

    def test_unmerged_checkout_cannot_claim_synthetic_merge(self):
        self.assertEqual(self.qualify(lane="synthetic-merge").returncode, 2)
        self.assertFalse(self.output.exists())

    def test_real_git_merge_tree_is_bound_even_when_commands_fail(self):
        self.git("checkout", "-q", "--detach", self.base)
        (self.root / "base-change.txt").write_text("base change\n")
        self.git("add", ".")
        self.git("commit", "-qm", "fixture base update")
        self.base = self.git("rev-parse", "HEAD")
        self.git("checkout", "-q", "--detach", self.source)
        self.git("merge", "--no-ff", "--no-commit", self.base)
        tree = self.git("write-tree")
        merge = self.git("commit-tree", tree, "-p", self.source, "-p", self.base, "-m", "fixture merge")
        self.git("checkout", "-q", "--detach", merge)
        result = self.qualify(lane="synthetic-merge")
        self.assertEqual(result.returncode, 1, result.stderr)
        receipt = json.loads((self.output / "receipt.json").read_text())
        self.assertEqual(receipt["tested_commit"], merge)
        self.assertEqual(receipt["tested_tree"], tree)
        self.assertEqual(receipt["ordered_parents"], [self.source, self.base])
        self.assertFalse(receipt["passed"])
        self.assertFalse(self.git("status", "--porcelain"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
