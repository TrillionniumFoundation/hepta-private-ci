"""Canonical inventory extensions must not require a second verifier allowlist."""

import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

SPEC = importlib.util.spec_from_file_location(
    "hepta_document_inventory", Path(__file__).with_name("hepta-docs.py")
)
DOCS = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(DOCS)


class DocumentInventoryTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        root_patch = patch.object(DOCS, "ROOT", self.root)
        root_patch.start()
        self.addCleanup(root_patch.stop)
        for path in ("README.md", "docs/modules/cognitive.store/PRODUCTION_CLOSURE.md"):
            target = self.root / path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text("# Reviewed document\n", encoding="utf-8")

    def verify(self, paths):
        DOCS.verify_document_inventory({"canonicalPaths": paths}, ["README.md"])

    def test_registered_module_extension_needs_no_second_inventory(self):
        self.verify(["README.md", "docs/modules/cognitive.store/PRODUCTION_CLOSURE.md"])

    def test_mandatory_inputs_cannot_be_removed(self):
        with self.assertRaisesRegex(SystemExit, "missing required canonical paths"):
            self.verify(["docs/modules/cognitive.store/PRODUCTION_CLOSURE.md"])

    def test_inventory_must_be_nonempty_bounded_list(self):
        for paths in (None, {}, "README.md", [], ["README.md"] * 16385):
            with self.subTest(paths_type=type(paths)), self.assertRaises(SystemExit):
                self.verify(paths)

    def test_duplicate_entries_are_rejected(self):
        with self.assertRaisesRegex(SystemExit, "duplicate canonical path"):
            self.verify(["README.md", "README.md"])

    def test_missing_extra_document_is_rejected(self):
        with self.assertRaisesRegex(SystemExit, "missing canonical path"):
            self.verify(["README.md", "docs/missing.md"])

    def test_noncanonical_paths_are_rejected(self):
        for path in (
            "/tmp/outside",
            "../outside",
            "docs/../README.md",
            "docs//file.md",
            "docs/*.md",
            ".git/config",
            "docs/\x00.md",
        ):
            with self.subTest(path=path), self.assertRaises(SystemExit):
                self.verify(["README.md", path])

    def test_symlink_escape_is_rejected(self):
        with tempfile.TemporaryDirectory() as outside:
            target = Path(outside) / "outside.md"
            target.write_text("not owned\n", encoding="utf-8")
            link = self.root / "docs/escape.md"
            try:
                link.symlink_to(target)
            except (OSError, NotImplementedError):
                self.skipTest("symlink creation is unavailable")
            with self.assertRaisesRegex(
                SystemExit, "canonical path escapes repository"
            ):
                self.verify(["README.md", "docs/escape.md"])

    def test_actual_registered_inventory_is_valid(self):
        with patch.object(DOCS, "ROOT", Path(__file__).resolve().parents[1]):
            system = DOCS.load("docs/governance/DOCUMENT_SYSTEM.json")
            DOCS.verify_document_inventory(system, ["README.md", "docs/DEVELOPMENT.md"])


if __name__ == "__main__":
    unittest.main()
