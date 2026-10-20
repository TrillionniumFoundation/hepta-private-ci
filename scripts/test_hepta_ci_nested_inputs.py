"""Exact-Git regressions for transitive embedded inputs; no Cargo execution."""

from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path

try:
    from scripts.hepta_ci_dependencies import (
        embedded_inputs,
        graph,
        plan,
        select_packages,
    )
except ModuleNotFoundError as error:
    if error.name != "scripts":
        raise
    from hepta_ci_dependencies import embedded_inputs, graph, plan, select_packages


class NestedInputTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.command("init", "-q")
        self.command("config", "user.name", "CI fixture")
        self.command("config", "user.email", "fixture@example.invalid")
        self.owners = {
            "codex-rs/hepta-feature": "feature",
            "codex-rs/hepta-consumer": "consumer",
            "codex-rs/hepta-unrelated": "unrelated",
        }
        files = {
            "codex-rs/Cargo.toml": (
                '[workspace]\nresolver = "2"\nmembers = '
                '["hepta-feature", "hepta-consumer", "hepta-unrelated"]\n'
            )
        }
        for folder, name in self.owners.items():
            files[f"{folder}/Cargo.toml"] = (
                f'[package]\nname = "{name}"\nversion = "0.1.0"\nedition = "2024"\n'
            )
            files[f"{folder}/src/lib.rs"] = "// fixture\n"
        files["codex-rs/hepta-consumer/Cargo.toml"] += (
            '[dependencies]\nfeature = { path = "../hepta-feature" }\n'
        )
        self.commit(files)

    def command(self, *args):
        return (
            subprocess.run(
                ["git", "--no-replace-objects", "-C", str(self.root), *args],
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            .stdout.decode()
            .strip()
        )

    def commit(self, files):
        for relative, content in files.items():
            path = self.root / relative
            if content is None:
                path.unlink()
            else:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(content, encoding="utf-8")
        self.command("add", "--all")
        self.command("commit", "-qm", "fixture")
        return self.command("rev-parse", "HEAD")

    def source(self, fragment):
        return self.commit(
            {
                "codex-rs/hepta-feature/src/lib.rs": 'include!("../../../shared/feature.inc");\n',
                "shared/feature.inc": fragment,
                "docs/feature.md": "original\n",
            }
        )

    def test_non_rs_source_fragment_keeps_transitive_prose_consumer(self):
        before = self.source('const TEXT: &str = include_str!("../docs/feature.md");\n')
        after = self.commit({"docs/feature.md": "changed\n"})
        selected = plan(self.root, before, after)
        self.assertFalse(selected["full_workspace"])
        self.assertEqual(selected["packages"], ["consumer", "feature"])
        self.assertEqual(selected["changed_packages"], ["feature"])

    def test_computed_include_inside_fragment_keeps_opaque_consumer(self):
        revision = self.source(
            'const TEXT: &str = include_str!(concat!(env!("CARGO_MANIFEST_DIR"), "/text"));\n'
        )
        observed = graph(self.root, revision)
        self.assertEqual(observed.opaque_input_consumers, frozenset({"feature"}))
        selected = select_packages(["docs/new.md"], observed, observed)
        self.assertEqual(selected["packages"], ["consumer", "feature"])
        self.assertFalse(selected["full_workspace"])

    def test_removed_nested_edge_remains_in_before_graph(self):
        before = self.source('const TEXT: &str = include_str!("../docs/feature.md");\n')
        after = self.commit({"shared/feature.inc": 'const TEXT: &str = "fixed";\n'})
        selected = select_packages(
            ["docs/feature.md"], graph(self.root, before), graph(self.root, after)
        )
        self.assertEqual(selected["packages"], ["consumer", "feature"])

    def test_recursive_fragments_terminate_without_losing_input_edges(self):
        revision = self.commit(
            {
                "codex-rs/hepta-feature/src/lib.rs": 'include!("../../../shared/a.inc");\n',
                "shared/a.inc": 'include!("b.inc");\n',
                "shared/b.inc": 'include!("a.inc");\nconst TEXT: &str = include_str!("../docs/feature.md");\n',
                "docs/feature.md": "text\n",
            }
        )
        inputs, opaque = embedded_inputs(self.root, revision, self.owners)
        self.assertIn(("docs/feature.md", "feature"), inputs)
        self.assertIn(("shared/a.inc", "feature"), inputs)
        self.assertIn(("shared/b.inc", "feature"), inputs)
        self.assertEqual(opaque, frozenset())

    def test_missing_rust_fragment_never_suppresses_consumer_tests(self):
        revision = self.commit(
            {
                "codex-rs/hepta-feature/src/lib.rs": 'include!("../../../shared/missing.inc");\n',
            }
        )
        observed = graph(self.root, revision)
        self.assertEqual(observed.opaque_input_consumers, frozenset({"feature"}))
        selected = select_packages(["docs/unknown.md"], observed, observed)
        self.assertEqual(selected["packages"], ["consumer", "feature"])

    def test_byte_payload_is_not_recursively_parsed_as_source(self):
        revision = self.commit(
            {
                "codex-rs/hepta-feature/src/lib.rs": (
                    'const BYTES: &[u8] = include_bytes!("../../../shared/blob.inc");\n'
                ),
                "shared/blob.inc": 'include!("missing.inc");\n',
            }
        )
        inputs, opaque = embedded_inputs(self.root, revision, self.owners)
        self.assertEqual(inputs, frozenset({("shared/blob.inc", "feature")}))
        self.assertEqual(opaque, frozenset())

    def test_module_code_and_unembedded_prose_stay_scoped(self):
        before = self.source("const VALUE: u8 = 1;\n")
        after = self.commit(
            {
                "codex-rs/hepta-feature/src/lib.rs": 'include!("../../../shared/feature.inc");\npub fn value() -> u8 { VALUE }\n',
                "docs/feature.md": "updated explanation\n",
            }
        )
        selected = plan(self.root, before, after)
        self.assertFalse(selected["full_workspace"])
        self.assertEqual(selected["packages"], ["consumer", "feature"])


if __name__ == "__main__":
    unittest.main()
