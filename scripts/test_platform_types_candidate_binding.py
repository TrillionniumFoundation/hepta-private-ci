#!/usr/bin/env python3
"""Regression tests using real Git objects; no mocked ref resolution."""
from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

import platform_types_candidate_binding as binding


class CandidateBindingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.git("init", "-b", "main")
        self.git("config", "user.email", "test@invalid.local")
        self.git("config", "user.name", "Candidate Binding Test")
        (self.root / "tracked.txt").write_text("base\n", encoding="utf-8")
        self.git("add", "tracked.txt")
        self.git("commit", "-m", "base")
        self.base = self.git("rev-parse", "HEAD")
        self.git("checkout", "-b", "candidate")
        (self.root / "tracked.txt").write_text("candidate\n", encoding="utf-8")
        self.git("commit", "-am", "candidate")
        self.source = self.git("rev-parse", "HEAD")

    def git(self, *args: str) -> str:
        return binding.git(self.root, *args)

    def test_explicit_non_default_candidate(self) -> None:
        result = binding.resolve_binding(self.root, "candidate", "main")
        self.assertEqual(result["source_sha"], self.source)
        self.assertEqual(result["base_sha"], self.base)
        self.assertNotEqual(result["source_sha"], result["base_sha"])
        self.assertFalse(result["qualification_passed"])

    def test_full_sha_and_annotated_tag(self) -> None:
        self.git("tag", "-a", "frozen", "-m", "candidate tag")
        for ref in (self.source, "frozen"):
            with self.subTest(ref=ref):
                self.assertEqual(binding.resolve_binding(self.root, ref, self.base)["source_sha"], self.source)

    def test_checkout_mismatch_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "checkout"):
            binding.resolve_binding(self.root, "main", "main")

    def test_unknown_ref_has_no_fallback(self) -> None:
        with self.assertRaises(ValueError):
            binding.resolve_binding(self.root, "not-a-ref", "main")

    def test_invalid_refs_rejected(self) -> None:
        for ref in ("", "--help", "candidate\ninjected=x", "candidate\x00", "candidate\x7f"):
            with self.subTest(ref=ref), self.assertRaises(ValueError):
                binding.resolve_binding(self.root, ref, "main")

    def test_dirty_tracked_file_rejected(self) -> None:
        (self.root / "tracked.txt").write_text("dirty\n", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "dirty"):
            binding.resolve_binding(self.root, "candidate", "main")
        self.git("add", "tracked.txt")
        with self.assertRaisesRegex(ValueError, "dirty"):
            binding.verify_checkout(self.root, self.source, self.base)

    def test_untracked_evidence_is_not_a_source_change(self) -> None:
        (self.root / "diagnostic.json").write_text("{}\n", encoding="utf-8")
        self.assertEqual(binding.verify_checkout(self.root, self.source, self.base)["source_sha"], self.source)

    def test_verifier_requires_full_commit_ids(self) -> None:
        tree = self.git("rev-parse", "HEAD^{tree}")
        for value in ("candidate", self.source[:12], tree, "0" * 40):
            with self.subTest(value=value), self.assertRaises(ValueError):
                binding.verify_checkout(self.root, value, self.base)

    def test_frozen_pair_survives_ref_movement(self) -> None:
        result = binding.resolve_binding(self.root, "candidate", "main")
        self.git("checkout", "--detach", self.source)
        self.git("branch", "-f", "main", self.source)
        self.git("branch", "-f", "candidate", self.base)
        actual = binding.verify_checkout(self.root, result["source_sha"], result["base_sha"])
        self.assertEqual(actual["base_sha"], self.base)
        with self.assertRaisesRegex(ValueError, "checkout"):
            binding.resolve_binding(self.root, "candidate", "main")

    def test_verifier_rejects_later_checkout(self) -> None:
        self.git("checkout", "--detach", self.base)
        with self.assertRaisesRegex(ValueError, "checkout"):
            binding.verify_checkout(self.root, self.source, self.base)

    def cli(self, source: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(Path(binding.__file__).resolve()), "--repo-root", str(self.root),
             "resolve", "--source-ref", source, "--base-ref", "main",
             "--output", str(self.root / "binding.json"),
             "--github-output", str(self.root / "github-output")],
            text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False,
        )

    def test_successful_cli_emits_only_validated_object_ids(self) -> None:
        result = self.cli("candidate")
        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads((self.root / "binding.json").read_text(encoding="utf-8"))
        outputs = dict(line.split("=", 1) for line in (self.root / "github-output").read_text().splitlines())
        self.assertEqual(set(outputs), {"source_sha", "source_tree", "base_sha", "base_tree"})
        for key, value in outputs.items():
            self.assertRegex(value, binding.SHA_RE)
            self.assertEqual(value, payload[key])
        self.assertFalse(payload["qualification_passed"])

    def test_failed_cli_emits_neither_evidence_nor_job_outputs(self) -> None:
        result = self.cli("does-not-exist")
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse((self.root / "binding.json").exists())
        self.assertFalse((self.root / "github-output").exists())


if __name__ == "__main__":
    unittest.main()
