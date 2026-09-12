#!/usr/bin/env python3
"""Exercise historical retirement invariants on real, evolving Git trees."""

import importlib.util
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

spec = importlib.util.spec_from_file_location("hepta_docs_cleanup", Path(__file__).with_name("hepta-docs.py"))
DOCS = importlib.util.module_from_spec(spec)
spec.loader.exec_module(DOCS)


class HistoricalRetirementTests(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.git("init", "-q")
        self.git("config", "user.name", "retirement-test")
        self.git("config", "user.email", "test@example.invalid")
        self.git("config", "commit.gpgsign", "false")
        for path in ("legacy/snapshot/data.json", "legacy/plan.md", "later.txt", "kept.py"):
            target = self.root / path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text("# original\n", encoding="utf-8")
        self.commit("initial")
        base = self.git("rev-parse", "HEAD")
        self.system = {"knownLegacyDeletion": {
            "exactBaseHead": base,
            "exactBaseTree": self.git("rev-parse", "HEAD^{tree}"),
            "copiedSnapshotPath": "legacy/snapshot",
            "copiedSnapshotDescendantCount": 1,
            "directPaths": ["legacy/plan.md"],
            "exactPathCount": 2,
            "exactGitObjects": {"legacy/snapshot": self.git("rev-parse", "HEAD:legacy/snapshot")},
        }}
        self.git("rm", "-r", "legacy")
        self.commit("retire legacy")
        self.patch = mock.patch.object(DOCS, "ROOT", self.root)
        self.patch.start()
        self.addCleanup(self.patch.stop)

    def git(self, *args: str) -> str:
        return subprocess.check_output(["git", *args], cwd=self.root, text=True, stderr=subprocess.PIPE).strip()

    def commit(self, message: str) -> None:
        self.git("add", "-A")
        self.git("commit", "-qm", message)

    def test_later_cleanup_is_allowed_without_changing_original_inventory(self) -> None:
        before = DOCS.verify_cleanup_base(self.system)
        self.git("rm", "later.txt")
        self.commit("later reviewed retirement")
        after = DOCS.verify_cleanup_base(self.system)
        self.assertEqual(before["inventorySha256"], after["inventorySha256"])
        self.assertEqual((after["expectedDeletionCount"], after["observedDeletionCount"]), (2, 3))

    def test_reintroduced_legacy_file_remains_rejected(self) -> None:
        path = self.root / "legacy/plan.md"
        path.parent.mkdir(parents=True)
        path.write_text("revived\n", encoding="utf-8")
        self.commit("revival")
        with self.assertRaisesRegex(SystemExit, "retired legacy paths reintroduced"):
            DOCS.verify_cleanup_base(self.system)

    def test_retained_code_cannot_consume_deleted_json(self) -> None:
        (self.root / "kept.py").write_text('open("legacy/snapshot/data.json")\n', encoding="utf-8")
        self.commit("dangling consumer")
        with self.assertRaisesRegex(SystemExit, "deleted JSON consumer"):
            DOCS.verify_cleanup_base(self.system)

    def test_forged_base_identity_remains_rejected(self) -> None:
        self.system["knownLegacyDeletion"]["exactBaseTree"] = "0" * 40
        with self.assertRaisesRegex(SystemExit, "cleanup base tree"):
            DOCS.verify_cleanup_base(self.system)


if __name__ == "__main__":
    unittest.main()
