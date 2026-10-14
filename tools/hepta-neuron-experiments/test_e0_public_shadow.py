"""Model-free source provenance tests for the opt-in public E0 shadow runner.

These controls never load/download ModernBERT and prove no Encoder accuracy.
"""
from __future__ import annotations
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import e0_public_shadow as m


def git(path, *args):
    return subprocess.run(["git", "-C", str(path), *args],
                          check=True, text=True, capture_output=True).stdout.strip()


class PinnedPublicSourceTests(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.TemporaryDirectory()
        self.addCleanup(self.root.cleanup)
        self.research = Path(self.root.name) / "research"
        self.audit = Path(self.root.name) / "audit"
        for directory in (self.research, self.audit):
            directory.mkdir()
            git(directory, "init", "-q")
            (directory / "pinned.py").write_text("x = 3\n")
            git(directory, "add", "pinned.py")
            git(directory, "-c", "user.name=E0 Fixture",
                "-c", "user.email=e0@example.invalid", "commit", "-qm", "frozen")

    def freeze(self):
        return mock.patch.multiple(m, STEM_RESEARCH_SHA=git(self.research, "rev-parse", "HEAD"),
                                   STEM_AUDIT_SHA=git(self.audit, "rev-parse", "HEAD"))

    def test_exact_clean_owners_are_admitted_for_preflight_only(self):
        with self.freeze():
            m.require_research_roots(self.research, self.audit)

    def test_tracked_research_source_mutation_fails_closed(self):
        with self.freeze():
            (self.research / "pinned.py").write_text("x = 4\n")
            with self.assertRaisesRegex(ValueError, "tracked file drift"):
                m.require_research_roots(self.research, self.audit)

    def test_tracked_audited_source_mutation_fails_closed(self):
        with self.freeze():
            (self.audit / "pinned.py").write_text("x = 5\n")
            with self.assertRaisesRegex(ValueError, "tracked file drift"):
                m.require_research_roots(self.research, self.audit)

    def test_changed_source_commit_is_rejected(self):
        with self.freeze():
            (self.audit / "pinned.py").write_text("x = 6\n")
            git(self.audit, "add", "pinned.py")
            git(self.audit, "-c", "user.name=E0 Fixture",
                "-c", "user.email=e0@example.invalid", "commit", "-qm", "changed")
            with self.assertRaisesRegex(ValueError, "frozen exact commits"):
                m.require_research_roots(self.research, self.audit)

    def test_wrong_research_head_rejected_before_model_import(self):
        with mock.patch.multiple(
            m,
            STEM_RESEARCH_SHA="f" * 40,
            STEM_AUDIT_SHA=git(self.audit, "rev-parse", "HEAD"),
        ):
            with self.assertRaisesRegex(ValueError, "frozen exact commits"):
                m.require_research_roots(self.research, self.audit)


if __name__ == "__main__":
    unittest.main()
