"""Regression tests for learning.eval's lexical API inventory."""
import unittest
from hepta_rust_identifiers import contains_rust_identifier

RAW = "ProductEvaluationRunnerV1"


class RustIdentifierTests(unittest.TestCase):
    def test_recorded_runner_is_not_raw_runner(self):
        self.assertFalse(contains_rust_identifier("RecordedProductEvaluationRunnerV1::new(owner)", RAW))

    def test_qualified_import_and_alias_are_detected(self):
        self.assertTrue(contains_rust_identifier(f"use eval::{RAW} as LocalRunner;", RAW))

    def test_generic_and_macro_references_are_detected(self):
        for source in (f"Vec<{RAW}<Store>>", f"factory!({RAW})"):
            with self.subTest(source=source):
                self.assertTrue(contains_rust_identifier(source, RAW))

    def test_raw_identifier_is_detected(self):
        self.assertTrue(contains_rust_identifier(f"use eval::r#{RAW};", RAW))

    def test_identifier_extensions_are_not_matches(self):
        for source in (f"_{RAW}", f"{RAW}2", f"Some{RAW}"):
            with self.subTest(source=source):
                self.assertFalse(contains_rust_identifier(source, RAW))

    def test_comments_are_not_callers(self):
        self.assertFalse(contains_rust_identifier(f"// {RAW}\n/* outer /* {RAW} */ end */", RAW))

    def test_string_literals_are_not_callers(self):
        for source in (f'"{RAW}"', f'r###"{RAW}"###', f'br#"{RAW}"#', f'cr"{RAW}"'):
            with self.subTest(source=source):
                self.assertFalse(contains_rust_identifier(source, RAW))

    def test_escaped_quotes_do_not_expose_literal_contents(self):
        self.assertFalse(contains_rust_identifier('"escaped \\" ' + RAW + '"', RAW))

    def test_lifetime_does_not_hide_reference(self):
        self.assertTrue(contains_rust_identifier(f"fn run<'a>(x: &'a {RAW}) {{}}", RAW))

    def test_character_literals_do_not_hide_following_reference(self):
        self.assertTrue(contains_rust_identifier("let x = '\\''; " + RAW, RAW))

    def test_cfg_and_macro_bodies_are_conservatively_retained(self):
        self.assertTrue(contains_rust_identifier(f"#[cfg(test)] fn test() {{ {RAW}::new(x); }}", RAW))

    def test_eof_comment_does_not_match(self):
        self.assertFalse(contains_rust_identifier(f"let x = 1; // {RAW}", RAW))


if __name__ == "__main__":
    unittest.main()
