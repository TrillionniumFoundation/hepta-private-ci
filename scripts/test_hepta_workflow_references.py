"""Check complete workflow path identities against real temporary files."""

import importlib.util
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch


SCRIPTS = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS))
SPEC = importlib.util.spec_from_file_location(
    "hepta_workflow_reference_verifier", SCRIPTS / "hepta-docs.py"
)
VERIFIER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(VERIFIER)


class WorkflowReferenceTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="hepta-workflow-reference-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        root_patch = patch.object(VERIFIER, "ROOT", self.root)
        root_patch.start()
        self.addCleanup(root_patch.stop)
        for relative in VERIFIER.WORKFLOW_REFERENCE_SCRIPTS:
            self.write(relative, "")

    def write(self, relative, content):
        target = self.root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        return target

    def test_nested_workflow_is_checked_by_its_complete_identity(self):
        nested = "codex-rs/third_party/imbl-6.1.0/.github/workflows/ci.yml"
        self.write(nested, "name: dependency CI\n")
        self.write(
            "qualification/memory-cell-v2/sources/github-history.json",
            '{"files": ["' + nested + '"]}\n',
        )
        self.assertFalse((self.root / ".github/workflows/ci.yml").exists())
        VERIFIER.verify_exact_workflow_references()

    def test_missing_nested_workflow_cannot_borrow_the_root_identity(self):
        nested = "codex-rs/third_party/imbl-6.1.0/.github/workflows/ci.yml"
        self.write(".github/workflows/ci.yml", "name: root CI\n")
        self.write("qualification/history.json", '{"file": "' + nested + '"}\n')
        with self.assertRaises(SystemExit) as raised:
            VERIFIER.verify_exact_workflow_references()
        self.assertIn("qualification/history.json:1: " + nested, str(raised.exception))

    def test_nested_reference_does_not_exempt_other_references_in_the_file(self):
        nested = "codex-rs/third_party/imbl-6.1.0/.github/workflows/ci.yml"
        self.write(nested, "name: dependency CI\n")
        self.write(
            "qualification/history.json",
            '{"files": ["' + nested + '", ".github/workflows/missing.yml"]}\n',
        )
        with self.assertRaisesRegex(
            SystemExit, r"history.json:1: \.github/workflows/missing.yml"
        ):
            VERIFIER.verify_exact_workflow_references()

    def test_missing_root_reference_is_rejected_in_every_existing_scope(self):
        locations = (
            "docs/reference.md",
            "qualification/reference.json",
            *VERIFIER.WORKFLOW_REFERENCE_SCRIPTS,
        )
        for relative in locations:
            with self.subTest(relative=relative):
                target = self.write(relative, '".github/workflows/missing.yml"\n')
                with self.assertRaises(SystemExit) as raised:
                    VERIFIER.verify_exact_workflow_references()
                self.assertIn(
                    relative + ":1: .github/workflows/missing.yml",
                    str(raised.exception),
                )
                target.write_text("", encoding="utf-8")

    def test_existing_root_and_nested_references_can_coexist(self):
        nested = "vendor/package/.github/workflows/ci.yaml"
        self.write(nested, "name: dependency CI\n")
        self.write(".github/workflows/current.yml", "name: current\n")
        self.write(
            "docs/reference.md",
            "`" + nested + "` and `.github/workflows/current.yml`\n",
        )
        VERIFIER.verify_exact_workflow_references()

    def test_url_and_document_relative_missing_root_checks_are_retained(self):
        prefixes = (
            "https://github.com/TrillionniumFoundation/hepta-private-ci/blob/main/",
            "https://raw.githubusercontent.com/TrillionniumFoundation/hepta-private-ci/main/",
            "./",
            "../",
            "../../",
        )
        for prefix in prefixes:
            with self.subTest(prefix=prefix):
                self.write(
                    "docs/reference.md",
                    "[CI](" + prefix + ".github/workflows/missing.yml)\n",
                )
                with self.assertRaisesRegex(
                    SystemExit, r"reference.md:1: \.github/workflows/missing.yml"
                ):
                    VERIFIER.verify_exact_workflow_references()

    def test_url_and_document_relative_existing_root_checks_are_retained(self):
        self.write(".github/workflows/current.yml", "name: current\n")
        prefixes = (
            "https://github.com/TrillionniumFoundation/hepta-private-ci/blob/main/",
            "./",
            "../",
        )
        for prefix in prefixes:
            with self.subTest(prefix=prefix):
                self.write(
                    "docs/reference.md",
                    "[CI](" + prefix + ".github/workflows/current.yml)\n",
                )
                VERIFIER.verify_exact_workflow_references()


if __name__ == "__main__":
    unittest.main()
