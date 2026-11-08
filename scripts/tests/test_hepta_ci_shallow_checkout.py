"""Exact endpoint checkout regressions using real shallow Git fetches."""

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from scripts import hepta_ci_dependencies as dependencies


SCOPE_SCRIPT = Path(__file__).resolve().parents[1] / "hepta_ci_scope.py"


class ShallowEndpointTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.directory = Path(temporary.name)
        self.full = self.directory / "source"
        self.full.mkdir()
        self.git(self.full, "init", "-q")
        self.git(self.full, "config", "user.name", "Shallow scope regression")
        self.git(self.full, "config", "user.email", "scope@example.invalid")
        packages = ("hepta-infer-core", "hepta-control-plane", "hepta-neuron")
        self.write(
            "codex-rs/Cargo.toml",
            "[workspace]\nmembers = " + json.dumps(packages) + "\n",
        )
        for package in packages:
            self.write(
                f"codex-rs/{package}/Cargo.toml",
                f'[package]\nname = "{package}"\nversion = "0.1.0"\n',
            )
            self.write(
                f"codex-rs/{package}/src/lib.rs", "pub fn value() -> u32 { 1 }\n"
            )
        self.write(
            "codex-rs/hepta-control-plane/Cargo.toml",
            '[package]\nname = "hepta-control-plane"\nversion = "0.1.0"\n'
            '[dependencies]\nhepta-infer-core = { path = "../hepta-infer-core" }\n',
        )
        self.write(
            "codex-rs/hepta-infer-core/src/lib.rs",
            'pub const GUIDE: &str = include_str!("../../../docs/guide.md");\n',
        )
        self.write("docs/guide.md", "# Common input\n")
        self.common = self.commit("common ancestor")
        self.git(self.full, "checkout", "-qb", "base")
        self.write("docs/guide.md", "# Base input\n")
        self.base = self.commit("base endpoint")
        self.git(self.full, "checkout", "-qb", "candidate", self.common)
        self.write("docs/guide.md", "# Candidate input\n")
        self.head = self.commit("candidate endpoint")

    def git(self, root, *args, check=True):
        return subprocess.run(
            ["git", "--no-replace-objects", "-C", str(root), *args],
            check=check,
            capture_output=True,
            text=True,
            timeout=15,
        )

    def write(self, name, text):
        path = self.full / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")

    def commit(self, message):
        self.git(self.full, "add", ".")
        self.git(self.full, "commit", "-qm", message)
        return self.git(self.full, "rev-parse", "HEAD").stdout.strip()

    def empty_checkout(self, name):
        root = self.directory / name
        root.mkdir()
        self.git(root, "init", "-q")
        self.git(root, "config", "gc.auto", "0")
        self.git(root, "remote", "add", "origin", self.full.as_uri())
        return root

    def fetch_checkout(self, root, revision):
        self.git(
            root,
            "-c",
            "protocol.file.allow=always",
            "fetch",
            "--depth=1",
            "--no-tags",
            "--prune",
            "origin",
            revision,
        )
        self.git(root, "checkout", "--force", "--detach", "FETCH_HEAD")
        self.assertEqual(self.git(root, "rev-parse", "HEAD").stdout.strip(), revision)

    def scope(self, root, *args, check=True):
        return subprocess.run(
            [sys.executable, str(SCOPE_SCRIPT), "--head", self.head, *args],
            cwd=root,
            check=check,
            capture_output=True,
            text=True,
            timeout=15,
        )

    def test_diverged_depth_one_endpoints_preserve_scope_and_graphs(self):
        shallow = self.empty_checkout("two-endpoints")
        self.fetch_checkout(shallow, self.base)
        self.git(shallow, "clean", "-ffdx")
        self.git(shallow, "reset", "--hard", "HEAD")
        self.fetch_checkout(shallow, self.head)

        self.assertEqual(
            self.git(shallow, "rev-parse", "--is-shallow-repository").stdout.strip(),
            "true",
        )
        for revision in (self.base, self.head):
            self.git(shallow, "cat-file", "-e", revision + "^{commit}")
            self.git(shallow, "cat-file", "-e", revision + "^{tree}")
        self.assertNotEqual(
            self.git(
                shallow, "cat-file", "-e", self.common + "^{commit}", check=False
            ).returncode,
            0,
        )
        self.assertEqual(
            self.git(self.full, "merge-base", self.base, self.head).stdout.strip(),
            self.common,
        )
        self.assertNotEqual(
            self.git(
                shallow, "merge-base", self.base, self.head, check=False
            ).returncode,
            0,
        )

        full_scope = json.loads(self.scope(self.full, "--base", self.base).stdout)
        shallow_scope = json.loads(self.scope(shallow, "--base", self.base).stdout)
        self.assertEqual(shallow_scope, full_scope)
        self.assertEqual(shallow_scope["paths"], ["docs/guide.md"])
        self.assertTrue(shallow_scope["scope"]["native"])
        self.assertFalse(shallow_scope["scope"]["full_repo"])
        for revision in (self.base, self.head):
            self.assertEqual(
                dependencies.graph(shallow, revision),
                dependencies.graph(self.full, revision),
            )
        impact = dependencies.plan(shallow, self.base, self.head)
        self.assertEqual(impact, dependencies.plan(self.full, self.base, self.head))
        self.assertEqual(
            impact["packages"], ["hepta-control-plane", "hepta-infer-core"]
        )
        self.assertFalse(impact["full_workspace"])

    def test_head_only_fetch_requires_explicit_full_selection(self):
        shallow = self.empty_checkout("head-only")
        self.fetch_checkout(shallow, self.head)
        self.assertNotEqual(
            self.git(
                shallow, "cat-file", "-e", self.base + "^{commit}", check=False
            ).returncode,
            0,
        )
        missing = self.scope(shallow, "--base", self.base, check=False)
        self.assertNotEqual(missing.returncode, 0)
        full = json.loads(self.scope(shallow, "--full").stdout)
        self.assertTrue(all(full["scope"].values()))
        self.assertEqual(full["paths"], [])


if __name__ == "__main__":
    unittest.main()
