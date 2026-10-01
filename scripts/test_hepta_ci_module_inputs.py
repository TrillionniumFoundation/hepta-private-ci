"""Real-Git regressions for source modules that happen to look like prose.

No compiler or candidate build script executes during dependency discovery.
"""

import importlib.util
import pathlib
import subprocess
import sys
import tempfile
import unittest

SPEC = importlib.util.spec_from_file_location(
    "hepta_ci_module_input_subject",
    pathlib.Path(__file__).with_name("hepta_ci_dependencies.py"),
)
SUBJECT = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = SUBJECT
SPEC.loader.exec_module(SUBJECT)


class ModuleInputTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = pathlib.Path(self.temporary.name)
        self.git("init", "-q")
        self.git("config", "user.name", "Fixture")
        self.git("config", "user.email", "fixture@example.invalid")
        self.put(
            "codex-rs/Cargo.toml",
            '[workspace]\nmembers=["hepta-a","hepta-b","hepta-unrelated"]\n',
        )
        for name in ("hepta-a", "hepta-b", "hepta-unrelated"):
            self.put(
                f"codex-rs/{name}/Cargo.toml",
                f'[package]\nname="{name}"\nversion="0.1.0"\n',
            )
            self.put(f"codex-rs/{name}/src/lib.rs", "pub fn fixture() {}\n")
        self.put(
            "codex-rs/hepta-b/Cargo.toml",
            '[package]\nname="hepta-b"\nversion="0.1.0"\n[dependencies]\nhepta-a={path="../hepta-a"}\n',
        )

    def git(self, *args):
        return (
            subprocess.run(
                ["git", "-C", str(self.root), *args],
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            .stdout.decode()
            .strip()
        )

    def put(self, path, text):
        target = self.root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")

    def commit(self):
        self.git("add", ".")
        self.git("commit", "-qm", "fixture")
        return self.git("rev-parse", "HEAD")

    def check_changed(self, path, expected=("hepta-a", "hepta-b")):
        before = self.commit()
        target = self.root / path
        self.put(path, target.read_text() + "\n// changed\n")
        after = self.commit()
        impact = SUBJECT.plan(self.root, before, after)
        self.assertFalse(impact["full_workspace"], impact)
        self.assertEqual(sorted(expected), impact["packages"], impact)

    def test_top_level_path_module_is_not_prose(self):
        self.put(
            "codex-rs/hepta-a/src/lib.rs",
            '#[path = "../../../docs/module.md"]\npub mod external;\n',
        )
        self.put("docs/module.md", "pub fn value() {}\n")
        self.check_changed("docs/module.md")

    def test_path_module_payload_is_transitive(self):
        self.put(
            "codex-rs/hepta-a/src/lib.rs",
            '#[path = "../../../docs/module.md"]\nmod external;\n',
        )
        self.put(
            "docs/module.md", 'pub const DATA: &str = include_str!("payload.md");\n'
        )
        self.put("docs/payload.md", "payload\n")
        self.check_changed("docs/payload.md")

    def test_recursive_path_modules_are_traversed(self):
        self.put(
            "codex-rs/hepta-a/src/lib.rs",
            '#[path = "../../../docs/one.md"]\nmod external;\n',
        )
        self.put("docs/one.md", '#[path = "two.md"]\nmod child;\n')
        self.put("docs/two.md", 'pub const DATA: &str = include_str!("payload.md");\n')
        self.put("docs/payload.md", "payload\n")
        self.check_changed("docs/payload.md")

    def test_raw_string_path_module(self):
        self.put(
            "codex-rs/hepta-a/src/lib.rs",
            '#[path = r#"../../../docs/module.md"#]\nmod external;\n',
        )
        self.put("docs/module.md", "pub fn value() {}\n")
        self.check_changed("docs/module.md")

    def test_removed_path_edge_survives_in_old_graph(self):
        self.put(
            "codex-rs/hepta-a/src/lib.rs",
            '#[path = "../../../docs/module.md"]\nmod external;\n',
        )
        self.put("docs/module.md", "pub fn value() {}\n")
        old = SUBJECT.graph(self.root, self.commit())
        self.put("codex-rs/hepta-a/src/lib.rs", "pub fn value() {}\n")
        new = SUBJECT.graph(self.root, self.commit())
        impact = SUBJECT.select_packages(["docs/module.md"], old, new)
        self.assertEqual(["hepta-a", "hepta-b"], impact["packages"])
        self.assertFalse(impact["full_workspace"])

    def test_inline_path_ambiguity_keeps_consumer(self):
        self.put(
            "codex-rs/hepta-a/src/lib.rs",
            'mod inline { #[path = "../../../../docs/module.md"] mod external; }\n',
        )
        self.put("docs/module.md", "pub fn value() {}\n")
        self.check_changed("docs/module.md")

    def test_conditional_path_does_not_disappear(self):
        self.put(
            "codex-rs/hepta-a/src/lib.rs",
            '#[cfg_attr(unix, path = "../../../docs/unix.md")]\nmod external;\n',
        )
        self.put("docs/unix.md", "pub fn value() {}\n")
        self.check_changed("docs/unix.md")

    def test_unrelated_prose_remains_lightweight(self):
        self.put(
            "codex-rs/hepta-a/src/lib.rs",
            '#[path = "../../../docs/module.md"]\nmod external;\n',
        )
        self.put("docs/module.md", "pub fn value() {}\n")
        self.put("docs/explanation.md", "An explanation.\n")
        self.check_changed("docs/explanation.md", ())

    def test_outlined_child_of_external_module_is_traversed(self):
        self.put(
            "codex-rs/hepta-a/src/lib.rs",
            '#[path = "../../../docs/external.rs"]\nmod external;\n',
        )
        self.put("docs/external.rs", "mod nested;\n")
        self.put(
            "docs/external/nested.rs",
            'pub const DATA: &str = include_str!("../payload.md");\n',
        )
        self.put("docs/payload.md", "payload\n")
        self.check_changed("docs/payload.md")

    def test_attribute_cycle_is_bounded(self):
        self.put(
            "codex-rs/hepta-a/src/lib.rs",
            '#[path = "../../../docs/module.md"]\nmod external;\n',
        )
        self.put("docs/module.md", '#[path="module.md"] mod again;\n')
        self.check_changed("docs/module.md")


if __name__ == "__main__":
    unittest.main()
