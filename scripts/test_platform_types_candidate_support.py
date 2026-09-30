#!/usr/bin/env python3
"""Regression tests for self-contained platform.types evidence records."""

from __future__ import annotations

import os
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import platform_types_candidate_support as support


class EvidenceContainmentTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.base = Path(self.temporary.name)
        self.root = self.base / "repo"
        self.root.mkdir()
        self.inside = self.root / "evidence" / "proof.json"
        self.inside.parent.mkdir()
        self.inside.write_text("{}\n", encoding="utf-8")
        self.outside = self.base / "outside.json"
        self.outside.write_text("{}\n", encoding="utf-8")

    def test_records_repository_relative_regular_file(self) -> None:
        records = support.evidence_records(
            ["proof=evidence/proof.json"],
            require_existing=True,
            root=self.root,
        )
        self.assertEqual(records["proof"]["path"], "evidence/proof.json")
        self.assertTrue(records["proof"]["exists"])
        self.assertGreater(records["proof"]["bytes"], 0)

    def test_rejects_absolute_outside_path(self) -> None:
        with self.assertRaises(support.CandidateBundleError):
            support.evidence_records(
                [f"proof={self.outside}"],
                require_existing=True,
                root=self.root,
            )

    def test_rejects_parent_traversal(self) -> None:
        with self.assertRaises(support.CandidateBundleError):
            support.evidence_records(
                ["proof=../outside.json"],
                require_existing=True,
                root=self.root,
            )

    def test_resolver_rejects_absolute_record(self) -> None:
        with self.assertRaises(support.CandidateBundleError):
            support.resolve_record_path(
                {"path": str(self.inside.resolve())},
                root=self.root,
            )

    @unittest.skipIf(os.name == "nt", "symlink creation is not portable on Windows runners")
    def test_rejects_symlink_evidence(self) -> None:
        link = self.root / "evidence" / "linked.json"
        link.symlink_to(self.outside)
        with self.assertRaises(support.CandidateBundleError):
            support.evidence_records(
                ["proof=evidence/linked.json"],
                require_existing=True,
                root=self.root,
            )


if __name__ == "__main__":
    unittest.main()
