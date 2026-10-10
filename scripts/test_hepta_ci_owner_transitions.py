"""Exercise Cargo ownership changes with graphs and actual temporary Git trees.

These tests execute the selector, not Rust builds or deployed module changes.
"""

from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from hepta_ci_dependencies import Graph, git, plan, select_packages


class OwnerTransitionTests(unittest.TestCase):
    def setUp(self):
        self.outer = Graph(
            {
                "codex-rs/outer": "outer",
                "codex-rs/host": "host",
                "codex-rs/unrelated": "unrelated",
            },
            frozenset({("outer", "host", False)}),
        )
        self.nested = Graph(
            self.outer.owners | {"codex-rs/outer/plugin": "plugin"},
            self.outer.edges,
        )
        self.path = "codex-rs/outer/plugin/src/lib.rs"

    def test_split_selects_both_revision_owners_and_old_consumers(self):
        result = select_packages([self.path], self.outer, self.nested)
        self.assertEqual(
            result,
            {
                "packages": ["host", "outer", "plugin"],
                "full_workspace": False,
                "changed_packages": ["outer", "plugin"],
                "reasons": [],
            },
        )

    def test_merge_selects_surviving_outer_owner(self):
        result = select_packages([self.path], self.nested, self.outer)
        self.assertEqual(
            result,
            {
                "packages": ["host", "outer"],
                "full_workspace": False,
                "changed_packages": ["outer", "plugin"],
                "reasons": [],
            },
        )

    def test_stable_nested_package_does_not_select_unrelated_parent(self):
        result = select_packages([self.path], self.nested, self.nested)
        self.assertEqual(result["packages"], ["plugin"])
        self.assertEqual(result["changed_packages"], ["plugin"])
        self.assertFalse(result["full_workspace"])

    def test_moving_nested_boundary_keeps_old_and_new_reverse_consumers(self):
        before = Graph(
            self.nested.owners | {"codex-rs/consumer": "consumer"},
            self.nested.edges | {("plugin", "consumer", False)},
        )
        after = Graph(
            self.outer.owners
            | {
                "codex-rs/consumer": "consumer",
                "codex-rs/outer/plugin/deeper": "deeper",
            },
            self.outer.edges,
        )
        result = select_packages(
            ["codex-rs/outer/plugin/deeper/src/lib.rs"], before, after
        )
        self.assertEqual(result["packages"], ["consumer", "deeper"])
        self.assertEqual(result["changed_packages"], ["deeper", "plugin"])
        self.assertFalse(result["full_workspace"])

    def test_multiple_paths_preserve_each_revision_owner_once(self):
        result = select_packages(
            [self.path, self.path, "codex-rs/outer/src/lib.rs"], self.outer, self.nested
        )
        self.assertEqual(result["packages"], ["host", "outer", "plugin"])
        self.assertEqual(result["changed_packages"], ["outer", "plugin"])

    def test_directory_prefix_is_not_ownership(self):
        result = select_packages(
            ["codex-rs/outer-other/src/lib.rs"], self.outer, self.nested
        )
        self.assertTrue(result["full_workspace"])
        self.assertEqual(result["changed_packages"], [])
        self.assertEqual(result["packages"], ["host", "outer", "plugin", "unrelated"])

    def test_shared_and_unknown_changes_still_select_full_workspace(self):
        for path in (
            "codex-rs/Cargo.lock",
            "docs/new-contract.json",
            ".github/workflows/a.yml",
            "codex-rs/outer/plugin/build.rs",
        ):
            with self.subTest(path=path):
                result = select_packages([self.path, path], self.outer, self.nested)
                self.assertTrue(result["full_workspace"])
                self.assertEqual(
                    result["packages"], ["host", "outer", "plugin", "unrelated"]
                )

    def test_dev_only_consumers_do_not_expand_to_production_downstream(self):
        before = Graph(
            self.outer.owners | {"codex-rs/downstream": "downstream"},
            frozenset({("outer", "host", True), ("host", "downstream", False)}),
        )
        after = Graph(before.owners | {"codex-rs/outer/plugin": "plugin"}, before.edges)
        result = select_packages([self.path], before, after)
        self.assertEqual(result["packages"], ["host", "outer", "plugin"])


class GitOwnerTransitionTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.command("init", "-q")
        self.command("config", "user.name", "Owner transition test")
        self.command("config", "user.email", "test@example.invalid")
        self.write(
            "codex-rs/Cargo.toml",
            """[workspace]
members = ["outer", "outer/plugins/*", "host", "unrelated"]
""",
        )
        for folder, name in (
            ("outer", "outer"),
            ("outer/plugins/existing", "existing"),
            ("host", "host"),
            ("unrelated", "unrelated"),
        ):
            self.package(folder, name)
        with (self.root / "codex-rs/host/Cargo.toml").open("a") as stream:
            stream.write('[dependencies]\nouter = { path = "../outer" }\n')
        self.write(
            "codex-rs/outer/src/lib.rs",
            'pub const DATA: &str = include_str!("../plugins/new/data.txt");\n',
        )
        self.write("codex-rs/outer/plugins/new/data.txt", "before\n")
        self.base = self.commit()

    def command(self, *args):
        return git(self.root, *args).decode().strip()

    def write(self, path, content):
        target = self.root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")

    def package(self, folder, name):
        self.write(
            f"codex-rs/{folder}/Cargo.toml",
            f'[package]\nname = "{name}"\nversion = "0.1.0"\n',
        )
        self.write(f"codex-rs/{folder}/src/lib.rs", "pub fn value() -> u32 { 1 }\n")

    def commit(self):
        self.command("add", "-A")
        self.command("commit", "-qm", "ownership fixture")
        return self.command("rev-parse", "HEAD")

    def split(self):
        self.package("outer/plugins/new", "new-plugin")
        self.write("codex-rs/outer/plugins/new/data.txt", "after\n")
        return self.commit()

    def test_glob_member_addition_without_workspace_edit_keeps_outer_consumer(self):
        head = self.split()
        self.assertEqual(
            self.command(
                "diff", "--name-only", self.base, head, "--", "codex-rs/Cargo.toml"
            ),
            "",
        )
        self.assertEqual(
            plan(self.root, self.base, head),
            {
                "packages": ["host", "new-plugin", "outer"],
                "full_workspace": False,
                "changed_packages": ["new-plugin", "outer"],
                "reasons": [],
            },
        )

    def test_nested_package_removal_does_not_turn_owned_diff_into_no_tests(self):
        base = self.split()
        (self.root / "codex-rs/outer/plugins/new/Cargo.toml").unlink()
        self.write("codex-rs/outer/plugins/new/data.txt", "merged back\n")
        head = self.commit()
        self.assertEqual(
            plan(self.root, base, head),
            {
                "packages": ["host", "outer"],
                "full_workspace": False,
                "changed_packages": ["new-plugin", "outer"],
                "reasons": [],
            },
        )

    def test_unrelated_local_change_remains_local_after_split(self):
        base = self.split()
        self.write("codex-rs/unrelated/src/lib.rs", "pub fn value() -> u32 { 2 }\n")
        result = plan(self.root, base, self.commit())
        self.assertEqual(result["packages"], ["unrelated"])
        self.assertFalse(result["full_workspace"])

    def test_exact_same_tree_keeps_empty_plan(self):
        self.assertEqual(
            plan(self.root, self.base, self.base),
            {
                "packages": [],
                "full_workspace": False,
                "changed_packages": [],
                "reasons": [],
            },
        )


if __name__ == "__main__":
    unittest.main()
