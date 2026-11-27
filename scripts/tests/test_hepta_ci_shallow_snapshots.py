"""Compare exact snapshot scope with a real repository containing full history."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from scripts import hepta_ci_dependencies as ci

SCOPE = Path(__file__).resolve().parents[1] / "hepta_ci_scope.py"
PACKAGES = ("hepta-neuron", "hepta-plasticity", "hepta-ndu", "unrelated")


class ShallowSnapshotTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.directory = Path(temporary.name)
        self.root = self.directory / "full"
        self.root.mkdir()
        ci.git(self.root, "init", "-q")
        ci.git(self.root, "config", "user.name", "CI regression")
        ci.git(self.root, "config", "user.email", "ci@example.invalid")
        self.write("README.md", "# Ancestor\n")
        self.ancestor = self.commit()
        self.write(
            "codex-rs/Cargo.toml",
            "[workspace]\nmembers = " + json.dumps(PACKAGES) + "\n",
        )
        for package in PACKAGES:
            self.manifest(package)
            self.write(f"codex-rs/{package}/src/lib.rs", "pub fn value() {}\n")
        self.manifest("hepta-plasticity", "hepta-neuron")
        self.manifest("hepta-ndu", "hepta-plasticity")
        self.write(
            "codex-rs/hepta-neuron/src/lib.rs",
            'pub const SCHEMA: &str = include_str!("../../../docs/schema.json");\n',
        )
        self.write("codex-rs/hepta-neuron/src/old.rs", "// move this source\n")
        self.write("codex-rs/hepta-neuron/src/obsolete.rs", "// remove this source\n")
        self.write("docs/schema.json", '{"version": 1}\n')
        self.base = self.commit()

    def write(self, relative, text):
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")

    def manifest(self, package, dependency=None):
        text = f'[package]\nname = "{package}"\nversion = "0.1.0"\n'
        if dependency:
            text += f'[dependencies]\n{dependency} = {{ path = "../{dependency}" }}\n'
        self.write(f"codex-rs/{package}/Cargo.toml", text)

    def commit(self):
        ci.git(self.root, "add", ".")
        ci.git(self.root, "commit", "-qm", "fixture")
        return ci.git(self.root, "rev-parse", "HEAD").decode().strip()

    def shallow(self, head, *, include_base=True):
        target = self.directory / "snapshots"
        target.mkdir()
        ci.git(target, "init", "-q")
        ci.git(target, "remote", "add", "origin", self.root.as_uri())
        ci.git(target, "config", "gc.auto", "0")
        revisions = [self.base, head] if include_base else [head]
        for index, revision in enumerate(revisions):
            if index:
                # The pinned checkout action reuses the same repository and
                # cleans its worktree; these operations do not prune objects.
                ci.git(target, "clean", "-ffdx")
                ci.git(target, "reset", "--hard", "HEAD")
            ci.git(
                target,
                "-c",
                "protocol.version=2",
                "fetch",
                "--no-tags",
                "--prune",
                "--no-recurse-submodules",
                "--depth=1",
                "origin",
                revision,
            )
            ci.git(target, "checkout", "--force", revision)
        self.assertEqual(ci.git(target, "rev-parse", "HEAD").decode().strip(), head)
        self.assertEqual(
            ci.git(target, "rev-parse", "--is-shallow-repository"), b"true\n"
        )
        self.assertEqual(ci.git(target, "rev-list", "--count", "HEAD"), b"1\n")
        with self.assertRaises(subprocess.CalledProcessError):
            ci.git(target, "cat-file", "-e", f"{self.ancestor}^{{commit}}")
        if include_base:
            ci.git(target, "cat-file", "-e", f"{self.base}^{{commit}}")
        return target

    def scope(self, root, head, *, full=False):
        args = [sys.executable, str(SCOPE), "--head", head]
        args.extend(["--full"] if full else ["--base", self.base])
        return json.loads(subprocess.check_output(args, cwd=root))

    def compare(self, head):
        target = self.shallow(head)
        full_plan = ci.plan(self.root, self.base, head)
        self.assertEqual(ci.plan(target, self.base, head), full_plan)
        self.assertEqual(self.scope(target, head), self.scope(self.root, head))
        return full_plan

    def test_source_change_keeps_reverse_dependencies_without_ancestors(self):
        self.write("codex-rs/hepta-neuron/src/old.rs", "// changed source\n")
        plan = self.compare(self.commit())
        self.assertFalse(plan["full_workspace"])
        self.assertEqual(plan["packages"], sorted(PACKAGES[:3]))

    def test_rename_delete_and_removed_dependency_keep_old_graph_consumers(self):
        folder = self.root / "codex-rs/hepta-neuron/src"
        (folder / "old.rs").rename(folder / "renamed.rs")
        (folder / "obsolete.rs").unlink()
        self.manifest("hepta-plasticity")
        plan = self.compare(self.commit())
        self.assertFalse(plan["full_workspace"])
        self.assertEqual(plan["packages"], sorted(PACKAGES[:3]))

    def test_embedded_document_keeps_native_scope_from_both_complete_trees(self):
        self.write("docs/schema.json", '{"version": 2}\n')
        head = self.commit()
        plan = self.compare(head)
        self.assertEqual(plan["packages"], sorted(PACKAGES[:3]))
        scope = self.scope(self.root, head)["scope"]
        self.assertFalse(scope["full_repo"])
        for group in ("learning", "lifecycle", "objective", "native"):
            self.assertTrue(scope[group], group)

    def test_push_full_scope_requires_only_head_snapshot(self):
        self.write("README.md", "# Candidate\n")
        head = self.commit()
        target = self.shallow(head, include_base=False)
        self.assertEqual(
            ci.plan(target, None, head, force_full=True),
            ci.plan(self.root, None, head, force_full=True),
        )
        self.assertEqual(
            self.scope(target, head, full=True), self.scope(self.root, head, full=True)
        )
        self.assertTrue(self.scope(target, head, full=True)["scope"]["full_repo"])

    def test_missing_base_keeps_full_fallback_and_cannot_emit_empty_scope(self):
        self.write("docs/schema.json", '{"version": 2}\n')
        head = self.commit()
        target = self.shallow(head, include_base=False)
        plan = ci.plan(target, self.base, head)
        self.assertTrue(plan["full_workspace"])
        self.assertEqual(plan["packages"], sorted(PACKAGES))
        result = subprocess.run(
            [sys.executable, str(SCOPE), "--base", self.base, "--head", head],
            cwd=target,
            capture_output=True,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(result.stdout, b"")


if __name__ == "__main__":
    unittest.main()
