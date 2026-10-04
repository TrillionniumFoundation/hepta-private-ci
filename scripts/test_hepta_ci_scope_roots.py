"""Exercise the real scope CLI against real temporary Git/Cargo source trees.

No resolver, compiler or candidate build script is executed by these tests.
"""

from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

SCRIPT = Path(__file__).with_name("hepta_ci_scope.py")


class ScopeOwnerRootsTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.git("init", "-q")
        self.git("config", "user.name", "Scope Fixture")
        self.git("config", "user.email", "fixture@example.invalid")

    def git(self, *args):
        return subprocess.run(
            ["git", "-C", str(self.root), *args],
            check=True,
            capture_output=True,
            text=True,
            timeout=10,
        ).stdout.strip()

    def write(self, path, text):
        target = self.root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")

    def workspace(self, folder, package, included="docs/feature.md"):
        self.write("codex-rs/Cargo.toml", f'[workspace]\nmembers = ["{folder}"]\n')
        self.write(
            f"codex-rs/{folder}/Cargo.toml",
            f'[package]\nname = "{package}"\nversion = "0.0.0"\nedition = "2024"\n',
        )
        self.write(
            f"codex-rs/{folder}/src/lib.rs",
            f'const INPUT: &str = include_str!("../../../{included}");\n',
        )
        self.write(included, "before\n")
        self.git("add", ".")
        self.git("commit", "-qm", "fixture baseline")
        return self.git("rev-parse", "HEAD")

    def changed(self):
        self.git("add", "-A")
        self.git("commit", "-qm", "fixture candidate")
        return self.git("rev-parse", "HEAD")

    def scope(self, base, head):
        result = subprocess.run(
            [sys.executable, str(SCRIPT), "--base", base, "--head", head],
            cwd=self.root,
            check=True,
            capture_output=True,
            text=True,
            timeout=20,
        )
        return json.loads(result.stdout)["scope"]

    def test_renamed_package_uses_its_actual_owner_root(self):
        base = self.workspace("hepta-plasticity", "plugin-with-unrelated-name")
        self.write("docs/feature.md", "after\n")
        scope = self.scope(base, self.changed())
        self.assertTrue(scope["native"] and scope["lifecycle"] and scope["learning"])
        self.assertFalse(scope["full_repo"])
        self.assertFalse(scope["objective"] or scope["effects"] or scope["inference"])

    def test_hepta_name_cannot_disguise_non_hepta_source_root(self):
        base = self.workspace("core", "codex-hepta-neuron")
        self.write("docs/feature.md", "after\n")
        self.assertTrue(self.scope(base, self.changed())["full_repo"])

    def test_embedded_json_is_not_misclassified_as_inert_documentation(self):
        base = self.workspace(
            "hepta-plasticity", "codex-hepta-plasticity", "docs/plugin.json"
        )
        self.write("docs/plugin.json", '{"revision":2}\n')
        scope = self.scope(base, self.changed())
        self.assertTrue(scope["native"] and scope["lifecycle"])
        self.assertFalse(scope["full_repo"])

    def test_unembedded_json_remains_static(self):
        base = self.workspace("hepta-plasticity", "codex-hepta-plasticity")
        self.write("docs/explanation.json", '{"note":"navigation"}\n')
        scope = self.scope(base, self.changed())
        self.assertFalse(scope["native"] or scope["full_repo"])
        self.assertTrue(scope["derived"])

    def test_source_plus_unembedded_guide_preserves_local_scope(self):
        base = self.workspace("hepta-plasticity", "codex-hepta-plasticity")
        self.write("codex-rs/hepta-plasticity/src/lib.rs", "pub fn example() {}\n")
        self.write("docs/modules/learning.plasticity/TECHNICAL.md", "owned guide\n")
        scope = self.scope(base, self.changed())
        self.assertTrue(scope["learning"] and scope["lifecycle"])
        self.assertFalse(scope["full_repo"] or scope["effects"] or scope["inference"])

    def test_computed_include_consumers_are_not_skipped_for_json_changes(self):
        base = self.workspace("hepta-plasticity", "codex-hepta-plasticity")
        self.write(
            "codex-rs/hepta-plasticity/src/lib.rs",
            'const X: &str = include_str!(concat!(env!("OUT_DIR"), "/data"));\n',
        )
        base = self.changed()
        self.write("docs/plugin.json", '{"revision":2}\n')
        scope = self.scope(base, self.changed())
        self.assertTrue(scope["native"] and scope["lifecycle"])
        self.assertFalse(scope["full_repo"])

    def test_removed_include_keeps_the_baseline_consumer(self):
        base = self.workspace("hepta-plasticity", "codex-hepta-plasticity")
        self.write("codex-rs/hepta-plasticity/src/lib.rs", "pub fn example() {}\n")
        self.write("docs/feature.md", "after\n")
        scope = self.scope(base, self.changed())
        self.assertTrue(scope["native"] and scope["lifecycle"])
        self.assertFalse(scope["full_repo"])

    def test_unavailable_base_graph_does_not_authorize_a_skip(self):
        base = self.workspace("hepta-plasticity", "codex-hepta-plasticity")
        self.write("codex-rs/Cargo.toml", "not toml [\n")
        invalid = self.changed()
        self.write(
            "codex-rs/Cargo.toml", '[workspace]\nmembers = ["hepta-plasticity"]\n'
        )
        self.write("docs/feature.md", "after\n")
        self.assertTrue(self.scope(invalid, self.changed())["full_repo"])


if __name__ == "__main__":
    unittest.main()
