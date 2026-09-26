"""Source navigation must survive formatting without accepting literal decoys."""

import tempfile
import unittest
from pathlib import Path

from lane_a_foundation_core import VerificationError, validate_anchor


class AnchorIdentifierTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.source = self.root / "owner.rs"
        self.anchor = {"path": "owner.rs", "requiredIdentifiers": ["shutdown_owner"]}

    def test_formatting_and_comments_do_not_change_code_identity(self):
        for source in (
            "pub async fn shutdown_owner() {}",
            "pub /* doc */ async\nfn shutdown_owner ( ) { }",
            "fn shutdown_owner() { let x = 1; }",
        ):
            with self.subTest(source=source):
                self.source.write_text(source)
                validate_anchor("owner", self.anchor, self.root)

    def test_comments_and_strings_do_not_supply_missing_identifiers(self):
        for source in (
            "// shutdown_owner\nfn other() {}",
            "/* shutdown_owner */ fn other() {}",
            'const TEXT: &str = "shutdown_owner";',
            'const TEXT: &str = r##"shutdown_owner"##;',
        ):
            with self.subTest(source=source):
                self.source.write_text(source)
                with self.assertRaises(VerificationError):
                    validate_anchor("owner", self.anchor, self.root)

    def test_renamed_or_removed_code_rejects(self):
        self.source.write_text("fn shutdown_other() {}")
        with self.assertRaises(VerificationError):
            validate_anchor("owner", self.anchor, self.root)

    def test_malformed_and_duplicate_identifiers_reject(self):
        self.source.write_text("fn shutdown_owner() {}")
        for value in (
            None,
            [],
            "shutdown_owner",
            [7],
            ["fn shutdown_owner"],
            ["shutdown_owner", "shutdown_owner"],
        ):
            with self.subTest(value=value), self.assertRaises(VerificationError):
                validate_anchor(
                    "owner", {**self.anchor, "requiredIdentifiers": value}, self.root
                )

    def test_legacy_negative_boundary_is_still_enforced(self):
        self.source.write_text("fn shutdown_owner() {}\nforbidden_entry();")
        with self.assertRaises(VerificationError):
            validate_anchor(
                "owner",
                {**self.anchor, "mustNotContain": ["forbidden_entry"]},
                self.root,
            )

    def test_repository_escape_rejects(self):
        with self.assertRaises(VerificationError):
            validate_anchor("owner", {**self.anchor, "path": "../owner.rs"}, self.root)


if __name__ == "__main__":
    unittest.main()
