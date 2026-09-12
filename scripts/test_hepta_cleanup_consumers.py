"""Exercise the production cleanup verifier with real, disposable Git histories."""

from __future__ import annotations

import importlib.util
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch


SOURCE = Path(__file__).with_name("hepta-docs.py")
SPEC = importlib.util.spec_from_file_location("hepta_cleanup_verifier", SOURCE)
assert SPEC is not None and SPEC.loader is not None
VERIFIER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(VERIFIER)
FIXTURE_NAME = "hepta-cleanup-fixture-7c3d.json"


class CleanupConsumerTests(unittest.TestCase):
    def test_exact_workflow_reference_must_exist(self):
        with tempfile.TemporaryDirectory(prefix="hepta-workflow-reference-") as directory:
            root = Path(directory)
            (root / "docs").mkdir()
            (root / "scripts").mkdir()
            (root / "docs/reference.md").write_text(
                "`.github/workflows/missing.yml`\n", encoding="utf-8"
            )
            for relative in VERIFIER.WORKFLOW_REFERENCE_SCRIPTS:
                target = root / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text("", encoding="utf-8")
            with patch.object(VERIFIER, "ROOT", root):
                with self.assertRaisesRegex(
                    SystemExit, "stale exact workflow references"
                ):
                    VERIFIER.verify_exact_workflow_references()

    def test_exact_workflow_reference_accepts_existing_file(self):
        with tempfile.TemporaryDirectory(prefix="hepta-workflow-reference-") as directory:
            root = Path(directory)
            (root / "docs").mkdir()
            (root / "scripts").mkdir()
            workflow = root / ".github/workflows/current.yml"
            workflow.parent.mkdir(parents=True)
            workflow.write_text("name: current\n", encoding="utf-8")
            (root / "docs/reference.md").write_text(
                "`.github/workflows/current.yml`\n", encoding="utf-8"
            )
            for relative in VERIFIER.WORKFLOW_REFERENCE_SCRIPTS:
                target = root / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text("", encoding="utf-8")
            with patch.object(VERIFIER, "ROOT", root):
                VERIFIER.verify_exact_workflow_references()

    def check_history(self, text, name=FIXTURE_NAME, wrong_count=False):
        with tempfile.TemporaryDirectory(prefix="hepta-cleanup-test-") as directory:
            root = Path(directory)

            def git(*args):
                return subprocess.check_output(
                    ["git", "-C", str(root), *args],
                    text=True,
                    stderr=subprocess.PIPE,
                ).strip()

            git("init", "-q", "-b", "main")
            git("config", "user.name", "Hepta test fixture")
            git("config", "user.email", "fixture@example.invalid")
            old = "legacy/" + name
            snapshot_path = "legacy/snapshot"
            (root / "legacy").mkdir()
            (root / old).write_text("{}\n", encoding="utf-8")
            (root / snapshot_path).mkdir()
            copied = root / snapshot_path / "copied.txt"
            copied.write_text("historical fixture\n", encoding="utf-8")
            git("add", "--all")
            git("commit", "-q", "-m", "fixture baseline")
            base = git("rev-parse", "HEAD")
            policy = {
                "exactBaseHead": base,
                "exactBaseTree": git("rev-parse", "HEAD^{tree}"),
                "exactGitObjects": {old: git("rev-parse", "HEAD:" + old)},
                "copiedSnapshotPath": snapshot_path,
                "copiedSnapshotDescendantCount": 1,
                "directPaths": [old],
                "exactPathCount": 3 if wrong_count else 2,
            }
            (root / old).unlink()
            copied.unlink()
            (root / "consumer.py").write_text(text + "\n", encoding="utf-8")
            git("add", "--all")
            git("commit", "-q", "-m", "fixture cleanup")
            with patch.object(VERIFIER, "ROOT", root):
                receipt = VERIFIER.verify_cleanup_base({"knownLegacyDeletion": policy})
            self.assertEqual(receipt["head"], git("rev-parse", "HEAD"))
            self.assertEqual(receipt["tree"], git("rev-parse", "HEAD^{tree}"))
            self.assertEqual(receipt["observedDeletionCount"], 2)
            self.assertEqual(receipt["retainedDeletedJsonConsumerHits"], 0)
            return receipt

    def test_longer_filename_prefix_is_not_a_consumer(self):
        self.check_history('url = "https://example.invalid/bazel_' + FIXTURE_NAME + '"')

    def test_longer_filename_suffix_is_not_a_consumer(self):
        self.check_history('backup = "' + FIXTURE_NAME + '.backup"')

    def test_other_filename_characters_are_not_boundaries(self):
        for character in ["a", "0", "_", "-", "."]:
            with self.subTest(character=character):
                self.check_history('value = "' + character + FIXTURE_NAME + '"')

    def test_standalone_filename_is_still_rejected(self):
        with self.assertRaisesRegex(SystemExit, "deleted JSON consumer"):
            self.check_history('value = "' + FIXTURE_NAME + '"')

    def test_path_separators_are_still_rejected(self):
        for separator in ["/", "\\"]:
            with self.subTest(separator=separator):
                with self.assertRaisesRegex(SystemExit, "deleted JSON consumer"):
                    self.check_history(
                        'value = "other' + separator + FIXTURE_NAME + '"'
                    )

    def test_explicit_old_path_is_still_rejected(self):
        with self.assertRaisesRegex(SystemExit, "deleted JSON consumer"):
            self.check_history('value = "legacy/' + FIXTURE_NAME + '"')

    def test_regex_metacharacters_in_filename_are_literal(self):
        name = "hepta-cleanup-fixture-[7c3d].json"
        self.check_history('value = "hepta-cleanup-fixture-c.json"', name=name)
        with self.assertRaisesRegex(SystemExit, "deleted JSON consumer"):
            self.check_history('value = "' + name + '"', name=name)

    def test_full_path_detection_remains_conservative(self):
        with self.assertRaisesRegex(SystemExit, "deleted JSON consumer"):
            self.check_history('value = "legacy/' + FIXTURE_NAME + '.backup"')

    def test_exact_deletion_inventory_is_not_relaxed(self):
        with self.assertRaisesRegex(SystemExit, "cleanup exact inventory count"):
            self.check_history("no_consumer = True", wrong_count=True)


if __name__ == "__main__":
    unittest.main()
