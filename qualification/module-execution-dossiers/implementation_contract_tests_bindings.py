"""Real Git checkout regressions for current native source observations."""

import json
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path

import native_source_bindings as bindings


class CurrentNativeBindingTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.source = self.root / "native/demo/lib.rs"
        self.source.parent.mkdir(parents=True)
        self.source.write_text("pub struct Demo;\n", encoding="utf-8")
        self.registry = self.root / "docs/modules/SOURCE_BINDINGS.json"
        self.registry.parent.mkdir(parents=True)
        self.registry.write_text(
            json.dumps(
                {
                    "bindings": [
                        {"module": "demo", "declaredRoots": ["native/demo"]},
                    ]
                }
            ),
            encoding="utf-8",
        )
        other = self.root / "native/other/lib.rs"
        other.parent.mkdir(parents=True)
        other.write_text("pub struct Demo;\n", encoding="utf-8")
        bindings.git(self.root, "init", "-q")
        self.commit()
        self.rows = [
            {
                "module": "demo",
                "path": "native/demo/lib.rs",
                "blobSha": bindings.git_blob(self.source.read_bytes()),
                "exports": ["Demo"],
            }
        ]

    def commit(self):
        bindings.git(self.root, "add", ".")
        bindings.git(
            self.root,
            "-c",
            "user.name=Binding Test",
            "-c",
            "user.email=binding-test@example.invalid",
            "commit",
            "-qm",
            "fixture",
        )

    def observe(self):
        return bindings.observe_native_bindings(self.root, self.rows, ["demo"])

    def test_committed_implementation_evolves_without_rewriting_history(self):
        first = self.observe()
        self.source.write_text(
            "pub struct Demo { pub revision: u64 }\n", encoding="utf-8"
        )
        self.commit()
        current = self.observe()
        self.assertNotEqual(current["sourceSha"], first["sourceSha"])
        self.assertNotEqual(current["sourceTree"], first["sourceTree"])
        self.assertEqual(
            current["sourceSha"],
            bindings.git(self.root, "rev-parse", "HEAD").decode().strip(),
        )
        self.assertEqual(
            current["observations"],
            [
                {
                    **self.rows[0],
                    "blobSha": bindings.git_blob(self.source.read_bytes()),
                    "historicalBlobSha": self.rows[0]["blobSha"],
                }
            ],
        )
        self.assertNotEqual(
            current["observations"][0]["blobSha"], self.rows[0]["blobSha"]
        )
        self.assertFalse(current["productExecutionProved"])

    def test_uncommitted_or_staged_source_is_not_attributed_to_head(self):
        self.source.write_text(
            "pub struct Demo { pub changed: bool }\n", encoding="utf-8"
        )
        with self.assertRaisesRegex(bindings.BindingError, "uncommitted native source"):
            self.observe()
        bindings.git(self.root, "add", "native/demo/lib.rs")
        with self.assertRaisesRegex(bindings.BindingError, "uncommitted native source"):
            self.observe()

    def test_removed_export_cannot_survive_only_as_a_comment_or_string(self):
        self.source.write_text(
            '// pub struct Demo;\npub const TEXT: &str = "Demo";\n', encoding="utf-8"
        )
        self.commit()
        with self.assertRaisesRegex(bindings.BindingError, "missing native symbols"):
            self.observe()

    def test_registered_owner_and_committed_ownership_are_required(self):
        wrong = deepcopy(self.rows)
        wrong[0]["path"] = "native/other/lib.rs"
        with self.assertRaisesRegex(
            bindings.BindingError, "outside declared module roots"
        ):
            bindings.observe_native_bindings(self.root, wrong, ["demo"])
        self.registry.write_text('{"bindings": []}', encoding="utf-8")
        with self.assertRaisesRegex(
            bindings.BindingError, "uncommitted module ownership"
        ):
            self.observe()


class QualifiedRustSourceBindingTests(unittest.TestCase):
    def has(self, source, symbol="Owner::run"):
        return bindings.source_symbol_exists(Path("fixture.rs"), source.encode(), symbol)

    def test_real_generic_inherent_impl_and_exact_module_are_supported(self):
        source = "pub struct Owner<T>(T); impl<T: Store> Owner<T> { pub async fn run(&self) {} }"
        self.assertTrue(self.has(source))
        self.assertTrue(self.has("mod exact { " + source + " }", "exact::Owner::run"))
        self.assertFalse(self.has("mod other { " + source + " }", "exact::Owner::run"))
        self.assertFalse(self.has("mod other { " + source + " }"))

    def test_type_method_and_impl_owner_cannot_be_combined_across_items(self):
        for source in (
            "struct Owner; impl Other { fn run() {} }",
            "struct Other; impl Other { fn run() {} }",
            "impl Owner { fn different() {} } fn run() {}",
            "trait Owner { fn run(); }",
            "impl Trait for Other { fn run() {} } struct Owner;",
            "impl Trait for Owner { fn run() {} }",
            "impl Owner { fn other() { fn run() {} } }",
            "fn wrapper() { impl Owner { fn run() {} } }",
            "trait Owner {} fn wrapper() -> impl Owner { fn run() {} value }",
        ):
            with self.subTest(source=source):
                self.assertFalse(self.has(source))

    def test_comments_literals_and_macro_tokens_cannot_define_the_owner(self):
        fake = "impl Owner { fn run() {} }"
        for source in (
            "// " + fake,
            "/* outer /* nested */ " + fake + " */",
            'const X: &str = "' + fake + '";',
            'const X: &str = r"' + fake + '";',
            'const X: &[u8] = br##"' + fake + '"##;',
            "macro_rules! fake { () => { " + fake + " } }",
            "fake!(" + fake + ");",
            "fake! { " + fake + " }",
        ):
            with self.subTest(source=source):
                self.assertFalse(self.has(source))

    def test_bare_symbol_observation_and_invalid_qualified_names(self):
        self.assertTrue(self.has("pub struct Owner;", "Owner"))
        for symbol in ("Owner::", "::Owner::run", "Owner / run", "Owner::run::"):
            with self.subTest(symbol=symbol):
                self.assertFalse(self.has("impl Owner { fn run() {} }", symbol))
