"""Exact-Git coverage for Cargo source entrypoints outside conventional .rs roots.

These exercise the real dependency planner without running candidate build code.
"""

from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path

try:
    from scripts.hepta_ci_dependencies import graph, plan, select_packages
except ModuleNotFoundError as error:
    if error.name != "scripts":
        raise
    from hepta_ci_dependencies import graph, plan, select_packages


class CargoEntrypointTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.git("init", "-q")
        self.git("config", "user.name", "CI fixture")
        self.git("config", "user.email", "fixture@example.invalid")
        self.manifest = '[package]\nname="feature"\nversion="0.1.0"\nedition="2024"\n'
        self.commit(
            {
                "codex-rs/Cargo.toml": '[workspace]\nresolver="2"\nmembers=["hepta-feature","hepta-consumer","hepta-unrelated"]\n',
                "codex-rs/hepta-feature/Cargo.toml": self.manifest,
                "codex-rs/hepta-feature/src/lib.rs": "pub fn feature() {}\n",
                "codex-rs/hepta-consumer/Cargo.toml": '[package]\nname="consumer"\nversion="0.1.0"\n[dependencies]\nfeature={path="../hepta-feature"}\n',
                "codex-rs/hepta-consumer/src/lib.rs": "pub fn consumer() {}\n",
                "codex-rs/hepta-unrelated/Cargo.toml": '[package]\nname="unrelated"\nversion="0.1.0"\n',
                "codex-rs/hepta-unrelated/src/lib.rs": "pub fn unrelated() {}\n",
                "docs/source.md": "pub fn from_nonstandard_path() {}\n",
                "docs/navigation.md": "Human-readable navigation.\n",
            }
        )

    def git(self, *arguments):
        return (
            subprocess.run(
                ["git", "--no-replace-objects", "-C", str(self.root), *arguments],
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            .stdout.decode()
            .strip()
        )

    def commit(self, files):
        for relative, text in files.items():
            path = self.root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8")
        self.git("add", "--all")
        self.git("commit", "-qm", "fixture")
        return self.git("rev-parse", "HEAD")

    def target(self, kind, path="../../docs/source.md"):
        header = "[lib]" if kind == "lib" else f'[[{kind}]]\nname="extra"'
        return self.manifest + f"{header}\npath={json.dumps(path)}\n"

    def assert_feature_impact(self, result):
        self.assertFalse(result["full_workspace"], result)
        self.assertEqual(result["packages"], ["consumer", "feature"])

    def test_explicit_library_path_is_source_even_with_markdown_suffix(self):
        before = self.commit({"codex-rs/hepta-feature/Cargo.toml": self.target("lib")})
        after = self.commit({"docs/source.md": "pub fn changed() {}\n"})
        self.assert_feature_impact(plan(self.root, before, after))

    def test_all_executable_target_kinds_bind_their_declared_path(self):
        for kind in ("bin", "example", "test", "bench"):
            with self.subTest(kind=kind):
                revision = self.commit(
                    {"codex-rs/hepta-feature/Cargo.toml": self.target(kind)}
                )
                observed = graph(self.root, revision)
                self.assert_feature_impact(
                    select_packages(["docs/source.md"], observed, observed)
                )

    def test_explicit_build_script_path_is_not_treated_as_prose(self):
        before = self.commit(
            {
                "codex-rs/hepta-feature/Cargo.toml": self.manifest
                + 'build="../../docs/build.md"\n',
                "docs/build.md": "fn main() {}\n",
            }
        )
        after = self.commit(
            {
                "docs/build.md": 'fn main() { println!("cargo:rerun-if-changed=payload"); }\n'
            }
        )
        self.assert_feature_impact(plan(self.root, before, after))

    def test_nested_include_in_external_entrypoint_keeps_its_consumer(self):
        before = self.commit(
            {
                "codex-rs/hepta-feature/Cargo.toml": self.target("lib"),
                "docs/source.md": 'include!("fragment.inc");\n',
                "docs/fragment.inc": 'pub const DATA: &str = include_str!("payload.json");\n',
                "docs/payload.json": '{"value":1}\n',
            }
        )
        after = self.commit({"docs/payload.json": '{"value":2}\n'})
        self.assert_feature_impact(plan(self.root, before, after))

    def test_removed_target_binding_is_preserved_from_the_base(self):
        before = self.commit({"codex-rs/hepta-feature/Cargo.toml": self.target("lib")})
        after = self.commit({"codex-rs/hepta-feature/Cargo.toml": self.manifest})
        self.assert_feature_impact(
            select_packages(
                ["docs/source.md"], graph(self.root, before), graph(self.root, after)
            )
        )

    def test_unrelated_prose_does_not_select_external_entrypoint_owner(self):
        before = self.commit({"codex-rs/hepta-feature/Cargo.toml": self.target("lib")})
        after = self.commit(
            {"docs/navigation.md": "Updated human-readable navigation.\n"}
        )
        selected = plan(self.root, before, after)
        self.assertFalse(selected["full_workspace"])
        self.assertEqual(selected["packages"], [])

    def test_computed_include_in_external_entrypoint_keeps_opaque_owner(self):
        revision = self.commit(
            {
                "codex-rs/hepta-feature/Cargo.toml": self.target("lib"),
                "docs/source.md": 'include!(concat!(env!("CARGO_MANIFEST_DIR"), "/generated"));\n',
            }
        )
        observed = graph(self.root, revision)
        self.assertEqual(observed.opaque_input_consumers, frozenset({"feature"}))
        self.assert_feature_impact(
            select_packages(["docs/navigation.md"], observed, observed)
        )

    def test_target_path_cannot_escape_the_exact_repository(self):
        for invalid in (
            "/tmp/unreviewed.rs",
            "../../../outside.rs",
            "",
            "C:\\outside.rs",
        ):
            with self.subTest(path=invalid):
                revision = self.commit(
                    {"codex-rs/hepta-feature/Cargo.toml": self.target("lib", invalid)}
                )
                with self.assertRaises(ValueError):
                    graph(self.root, revision)

    def test_non_string_target_path_is_rejected(self):
        revision = self.commit(
            {
                "codex-rs/hepta-feature/Cargo.toml": self.manifest
                + "[lib]\npath=false\n",
            }
        )
        with self.assertRaises(ValueError):
            graph(self.root, revision)

    def test_missing_entrypoint_retains_opaque_dependency_instead_of_no_tests(self):
        revision = self.commit(
            {
                "codex-rs/hepta-feature/Cargo.toml": self.target(
                    "lib", "../../docs/missing.md"
                )
            }
        )
        observed = graph(self.root, revision)
        self.assert_feature_impact(
            select_packages(["docs/navigation.md"], observed, observed)
        )


if __name__ == "__main__":
    unittest.main()
