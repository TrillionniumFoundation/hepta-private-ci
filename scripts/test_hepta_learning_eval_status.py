"""Adversarial checks for formatting-stable lexical source call inventory."""
import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest import mock

SPEC = importlib.util.spec_from_file_location(
    "learning_eval_status", Path(__file__).with_name("hepta-learning-eval-status.py")
)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


class SourceCallInventoryTests(unittest.TestCase):
    def require_fixture(self, source, call="archive.verify(verifier, now)", literals=()):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "source.rs").write_text(source, encoding="utf-8")
            with (
                mock.patch.object(MODULE, "ROOT", root),
                mock.patch.object(MODULE, "REQUIRED_TOKENS", {"source.rs": literals}),
                mock.patch.object(MODULE, "REQUIRED_CODE_CALLS", {"source.rs": [call]}),
            ):
                MODULE.require_tokens()

    def test_rustfmt_method_chain_line_break_keeps_archive_verification(self):
        self.require_fixture(
            "let decision = archive\n"
            "    .verify(verifier, now)\n"
            "    .map_err(RecordedProductEvaluationErrorV1::Evaluation)?;\n"
        )

    def test_cursor_nested_arguments_can_wrap_without_changing_identity(self):
        self.require_fixture(
            "cursor\n .save(\n Some(\n &id\n )\n )?;\n",
            call="cursor.save(Some(&id))",
        )

    def test_removed_or_changed_verification_call_is_rejected(self):
        for source in (
            "let decision = archive;",
            "archive.check(verifier, now);",
            "self.verify(verifier, now);",
            "other_archive.verify(verifier, now);",
            "object.archive.verify(verifier, now);",
            "module::archive.verify(verifier, now);",
            "archive.verify(now, verifier);",
            "archive.verify(other_verifier, now);",
            "archive.verify(verifier, now + 1);",
        ):
            with self.subTest(source=source), self.assertRaisesRegex(
                SystemExit, "missing code call"
            ):
                self.require_fixture(source)

    def test_whitespace_cannot_join_distinct_identifiers(self):
        for source in (
            "arch ive.verify(verifier, now);",
            "archive.ver ify(verifier, now);",
            "archive.verify(veri fier, now);",
        ):
            with self.subTest(source=source), self.assertRaisesRegex(
                SystemExit, "missing code call"
            ):
                self.require_fixture(source)

    def test_comments_and_literals_cannot_replace_the_code_call(self):
        for source in (
            "// archive.verify(verifier, now)\n",
            "/* outer /* archive.verify(verifier, now) */ end */",
            'let text = "archive.verify(verifier, now)";',
            'let text = r###"archive.verify(verifier, now)"###;',
            'let text = br#"archive.verify(verifier, now)"#;',
            'archive "literal barrier" .verify(verifier, now);',
        ):
            with self.subTest(source=source), self.assertRaisesRegex(
                SystemExit, "missing code call"
            ):
                self.require_fixture(source)

    def test_comments_between_code_tokens_preserve_the_call(self):
        self.require_fixture(
            "archive /* outer /* inner */ end */ .verify(\n"
            "verifier, // current verifier\n now\n);"
        )

    def test_documentation_text_checks_stay_exact(self):
        with self.assertRaisesRegex(SystemExit, "missing 'No decoder callback'"):
            self.require_fixture(
                "// No decoder\n// callback\narchive.verify(verifier, now);",
                literals=("No decoder callback",),
            )

    def test_formatted_repository_required_source_inventory_is_present(self):
        MODULE.require_tokens()


if __name__ == "__main__":
    unittest.main()
