"""Regression tests for static Rust source/test discovery, not Rust execution."""
import tempfile
import unittest
from pathlib import Path

from verify_prompt_optimizer_map import discover_sources, test_inventory


class SourceDiscoveryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "src"
        self.root.mkdir()

    def write(self, path, text):
        target = self.root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")

    def inventory(self):
        return test_inventory(discover_sources(self.root))

    def test_inline_tests_are_found_without_test_filename(self):
        self.write("lib.rs", 'pub mod canonical;\n')
        self.write("canonical.rs", '#[cfg(test)]\nmod tests {\n    #[test]\n    fn inline_regression() {}\n}\n')
        self.assertEqual(self.inventory(), {"inline_regression"})

    def test_explicit_paths_and_cfg_test_modules_are_traversed(self):
        self.write("lib.rs", '#[cfg(test)]\n#[path = "special.rs"]\nmod tests;\n')
        self.write("special.rs", '#[test]\nfn linked_regression() {}\n')
        self.assertEqual(self.inventory(), {"linked_regression"})

    def test_orphan_and_unannotated_helper_do_not_count(self):
        self.write("lib.rs", 'fn helper() {}\n// #[test]\n// fn commented_test() {}\n')
        self.write("orphan_tests.rs", '#[test]\nfn not_linked() {}\n')
        self.assertEqual(self.inventory(), set())

    def test_normal_submodule_resolution(self):
        self.write("lib.rs", 'mod outer;\n')
        self.write("outer.rs", 'pub(crate) mod inner;\n')
        self.write("outer/inner/mod.rs", '#[test]\nfn nested_regression() {}\n')
        self.assertEqual(self.inventory(), {"nested_regression"})

    def test_missing_or_ambiguous_module_rejected(self):
        self.write("lib.rs", 'mod missing;\n')
        with self.assertRaisesRegex(ValueError, "missing or ambiguous"):
            self.inventory()
        self.write("missing.rs", '')
        self.write("missing/mod.rs", '')
        with self.assertRaisesRegex(ValueError, "missing or ambiguous"):
            self.inventory()

    def test_explicit_path_cannot_escape_source_root(self):
        self.write("lib.rs", '#[path = "../outside.rs"]\nmod outside;\n')
        outside = self.root.parent / "outside.rs"
        outside.write_text('', encoding="utf-8")
        self.addCleanup(outside.unlink)
        with self.assertRaisesRegex(ValueError, "escapes"):
            self.inventory()

    def test_repeated_explicit_paths_terminate(self):
        self.write("lib.rs", '#[path = "cycle.rs"]\nmod cycle;\n')
        self.write("cycle.rs", '#[path = "lib.rs"]\nmod root_again;\n#[test]\nfn once() {}\n')
        self.assertEqual(self.inventory(), {"once"})

    def test_async_tests_and_extra_attributes(self):
        self.write("lib.rs", '#[tokio::test]\n#[ignore]\nasync fn async_regression() {}\n#[test]\nfn ordinary() {}\n')
        self.assertEqual(self.inventory(), {"async_regression", "ordinary"})

    def test_comments_and_fixture_strings_cannot_invent_tests(self):
        self.write("lib.rs", '/* nested /* comment */\n#[test]\nfn fake() {}\n*/\n'
                   'const FIXTURE: &str = r##"\n#[test]\nfn fake_string() {}\nmod absent;\n"##;\n'
                   '#[test]\nfn real() {}\n')
        self.assertEqual(self.inventory(), {"real"})

    def test_byte_strings_and_character_literals_are_not_declarations(self):
        self.write("lib.rs", "const C: char = '\"';\n"
                   'const B: &[u8] = b"/* not a comment */";\n'
                   '/* #[path = "missing.rs"]\nmod missing; */\n'
                   '#[test]\nfn real() {}\n')
        self.assertEqual(self.inventory(), {"real"})

    def test_unterminated_lexical_construct_rejected(self):
        self.write("lib.rs", '/* no close')
        with self.assertRaisesRegex(ValueError, "unterminated"):
            self.inventory()


if __name__ == "__main__":
    unittest.main()
