"""Qualified entrypoints bind a direct method to its Rust impl owner."""

import unittest

from source_entrypoints import qualified_rust_method


class QualifiedEntrypointTests(unittest.TestCase):
    def test_direct_methods_with_supported_owners_and_modifiers(self):
        sources = [
            "impl Owner { pub fn tick() {} }",
            "impl Owner { pub const fn tick() {} }",
            "impl Owner { pub(crate) async fn tick() {} }",
            "impl<W: Bound> Owner<W> { pub fn tick(&self) {} }",
            "impl<'a, W: Bound> Owner<'a, W> where W: Other { fn tick() {} }",
            "impl<W: Fn() -> X> Owner<W> { fn tick() {} }",
            "impl Trait for Owner { fn tick() {} }",
            "unsafe impl Trait for Owner { fn tick() {} }",
            "impl crate::Owner { fn tick() {} }",
            "mod nested { impl Owner { fn tick() {} } }",
            "pub mod nested { impl Owner { fn tick() {} } }",
            "pub(crate) mod nested { impl Owner { fn tick() {} } }",
            "#[cfg(any())] impl Owner { #[cfg(any())] fn tick() {} }",
            "impl Owner { fn other() {} fn tick<T>(&self) where T: Bound {} }",
            "impl Owner { const C: char = '}'; fn tick() {} }",
        ]
        for source in sources:
            with self.subTest(source=source):
                self.assertTrue(qualified_rust_method(source, "Owner::tick"))

    def test_other_owners_nested_functions_calls_and_macros_do_not_qualify(self):
        sources = [
            "struct Owner; impl Other { fn tick() {} }",
            "impl Owner { fn wrapper() { fn tick() {} } }",
            "fn run() { Owner::tick(); }",
            "trait Owner { fn tick() {} }",
            "impl<Owner> Other<Owner> { fn tick() {} }",
            "impl Owner for Other { fn tick() {} }",
            "impl Wrapper<Owner> { fn tick() {} }",
            "impl Trait<Owner> for Other { fn tick() {} }",
            "macro_rules! fake { () => { impl Owner { fn tick() {} } }; }",
            "fake! { impl Owner { fn tick() {} } }",
            "fake!(impl Owner { fn tick() {} });",
            "fake![impl Owner { fn tick() {} }];",
            "macro_rules! r#mod { ($($t:tt)*) => {} } r#mod! { impl Owner { fn tick() {} } }",
            "impl Owner { fake! { fn tick() {} } }",
            "impl Owner { fake!(fn tick() {}); }",
            "fn make() -> impl Owner { fn tick() {} }",
            "impl Owner { fn tick(); }",
            "impl Owner { fn ticker() {} }",
        ]
        for source in sources:
            with self.subTest(source=source):
                self.assertFalse(qualified_rust_method(source, "Owner::tick"))

    def test_comments_and_all_string_forms_cannot_supply_definitions(self):
        body = "impl Owner { fn tick() {} }"
        sources = [
            "// " + body,
            "/* " + body + " */",
            "/* outer /* nested */ " + body + " */",
            'const S: &str = "' + body + '";',
            'const S: &[u8] = b"' + body + '";',
            'const S: &str = r"' + body + '";',
            'const S: &str = r##"' + body + '"##;',
            'const S: &[u8] = br#"' + body + '"#;',
            'const S: &str = r###" inner "# ' + body + '"###;',
            '#[doc = "' + body + '"] struct Owner;',
        ]
        for source in sources:
            with self.subTest(source=source):
                self.assertFalse(qualified_rust_method(source, "Owner::tick"))

    def test_malformed_source_or_qualified_registration_fails_closed(self):
        good = "impl Owner { fn tick() {} }"
        for source in (
            good + " {",
            good + " }",
            good + " /*",
            good + ' r#"',
            good + ' "',
        ):
            with self.subTest(source=source):
                self.assertFalse(qualified_rust_method(source, "Owner::tick"))
        for symbol in (
            "Owner::tick::extra",
            "Owner::tick / other",
            "Owner::",
            "Owner.tick",
        ):
            with self.subTest(symbol=symbol):
                self.assertFalse(qualified_rust_method(good, symbol))
