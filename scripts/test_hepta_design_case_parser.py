"""Design identities are independent of typography, never test-pass receipts."""

import importlib.util
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
SPEC = importlib.util.spec_from_file_location(
    "technical_case_parser", ROOT / "scripts/hepta-technical-closure.py"
)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class DesignCaseParserTests(unittest.TestCase):
    def parse(self, text, root=None):
        return MODULE.named_test_design_ids(text, root or ROOT)

    def test_plain_code_bold_and_bold_title_keep_the_same_identity(self):
        for line in [
            "- EVID-01: distinct principals",
            "- `EVID-01`: distinct principals",
            "- **EVID-01:** distinct principals",
            "- **EVID-01**: distinct principals",
            "- **EVID-01 — distinct principals:** rejected shared identity",
        ]:
            with self.subTest(line=line):
                self.assertEqual(self.parse(line), ["EVID-01"])

    def test_cross_format_duplicate_is_rejected(self):
        with self.assertRaisesRegex(MODULE.Invalid, "duplicate"):
            self.parse("- EVID-01: first\n- **EVID-01:** second")

    def test_fenced_examples_do_not_supply_designs(self):
        for fence in ["```", "~~~"]:
            with self.assertRaises(MODULE.Invalid):
                self.parse(f"{fence}\n- EVID-01: example only\n{fence}")

    def test_malformed_unclosed_or_unnamed_cases_are_rejected(self):
        for line in [
            "- **EVID-01: unclosed",
            "- EVID-001: wrong identity",
            "- evidence: no identity",
            "",
        ]:
            with self.subTest(line=line), self.assertRaises(MODULE.Invalid):
                self.parse(line)

    def fixture(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        root = Path(temp.name)
        subprocess.run(["git", "init", "-q", str(root)], check=True)
        source = root / "codex-rs/example/src/owner_tests.rs"
        source.parent.mkdir(parents=True)
        source.write_text("#[test] fn exact_owner() {}\n")
        subprocess.run(["git", "-C", str(root), "add", "."], check=True)
        subprocess.run(
            [
                "git",
                "-C",
                str(root),
                "-c",
                "user.name=Test",
                "-c",
                "user.email=test@example.invalid",
                "-c",
                "commit.gpgsign=false",
                "commit",
                "-qm",
                "fixture",
            ],
            check=True,
        )
        return root, source.relative_to(root).as_posix()

    def test_existing_source_identity_needs_no_invented_numbered_alias(self):
        root, path = self.fixture()
        self.assertEqual(
            self.parse(f"- `{path}`: explicit owner regression", root),
            ["source:" + path],
        )

    def test_untracked_test_source_is_not_committed_design_evidence(self):
        root, _ = self.fixture()
        path = "codex-rs/example/src/untracked_tests.rs"
        (root / path).write_text("#[test] fn untracked() {}\n")
        with self.assertRaisesRegex(MODULE.Invalid, "committed regular file"):
            self.parse(f"- `{path}`: absent from candidate", root)

    def test_parent_escape_and_directory_alias_are_rejected(self):
        for path in [
            "codex-rs/../outside_tests.rs",
            "codex-rs/example/./src/owner_tests.rs",
        ]:
            with (
                self.subTest(path=path),
                self.assertRaisesRegex(MODULE.Invalid, "invalid named"),
            ):
                self.parse(f"- `{path}`: invalid path")

    def test_duplicate_source_design_is_rejected(self):
        root, path = self.fixture()
        with self.assertRaisesRegex(MODULE.Invalid, "duplicate"):
            self.parse(f"- `{path}`: first\n- `{path}`: second", root)

    def test_committed_symlink_does_not_stand_in_for_test_source(self):
        root, path = self.fixture()
        alias = root / "codex-rs/example/src/alias_tests.rs"
        target = (
            subprocess.check_output(
                ["git", "-C", str(root), "hash-object", "-w", "--stdin"],
                input=Path(path).name.encode(),
            )
            .decode()
            .strip()
        )
        subprocess.run(
            [
                "git",
                "-C",
                str(root),
                "update-index",
                "--add",
                "--cacheinfo",
                "120000",
                target,
                alias.relative_to(root).as_posix(),
            ],
            check=True,
        )
        subprocess.run(
            [
                "git",
                "-C",
                str(root),
                "-c",
                "user.name=Test",
                "-c",
                "user.email=test@example.invalid",
                "-c",
                "commit.gpgsign=false",
                "commit",
                "-qm",
                "symlink",
            ],
            check=True,
        )
        with self.assertRaisesRegex(MODULE.Invalid, "committed regular file"):
            self.parse(f"- `{alias.relative_to(root).as_posix()}`: symlink", root)

    def test_current_registered_guides_parse_without_rewriting_their_descriptions(self):
        for path in (ROOT / "qualification/module-execution-dossiers/detail").glob(
            "*.md"
        ):
            with self.subTest(module=path.name):
                self.assertTrue(self.parse(path.read_text()))


if __name__ == "__main__":
    unittest.main()
