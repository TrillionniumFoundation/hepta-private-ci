#!/usr/bin/env python3
"""Exercise destructive prewarm behavior in real Git worktrees."""

from pathlib import Path
import json
import subprocess
import sys
import tempfile
import textwrap
import unittest

from hepta_ci_chef import checkout_identity, prewarm


class ChefSourceCustodyTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="chef fixture ")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.repo = self.root / "repository with spaces"
        self.repo.mkdir()
        self.git("init", "--quiet")
        self.workspace = self.repo / "codex-rs"
        (self.workspace / "src").mkdir(parents=True)
        self.manifest = self.workspace / "Cargo.toml"
        self.source = self.workspace / "src/lib.rs"
        self.manifest.write_text(
            '[package]\nname = "source-custody"\nversion = "0.0.0"\n'
        )
        self.source.write_text(
            'compile_error!("actual source must still be checked");\n'
        )
        self.git("add", "--all")
        self.git("commit", "--quiet", "--no-gpg-sign", "-m", "original source")
        self.head = self.git("rev-parse", "HEAD")
        self.original = {
            self.manifest: self.manifest.read_bytes(),
            self.source: self.source.read_bytes(),
        }
        self.calls = self.root / "cargo-calls.jsonl"
        self.fake_cargo = self.root / "destructive_cargo.py"
        self.fake_cargo.write_text(
            textwrap.dedent("""\
            import json, pathlib, sys
            trace, failure, *args = sys.argv[1:]
            with open(trace, 'a') as out:
                out.write(json.dumps({'cwd': str(pathlib.Path.cwd()), 'args': args}) + '\\n')
            if args == ['chef', '--version']:
                print('cargo-chef-chef 0.1.78')
            elif args[:2] == ['chef', 'prepare']:
                pathlib.Path(args[args.index('--recipe-path') + 1]).write_text('{}')
            elif args[:2] == ['chef', 'cook']:
                pathlib.Path('Cargo.toml').write_text('[package]\\nname="source-custody"\\nversion="0.0.1"\\n')
                pathlib.Path('src/lib.rs').write_text('')
                sys.exit(int(failure))
            else:
                raise RuntimeError(args)
            """)
        )

    def git(self, *args):
        return subprocess.check_output(
            [
                "git",
                "-c",
                "user.name=CI fixture",
                "-c",
                "user.email=ci@example.invalid",
                *args,
            ],
            cwd=self.repo,
            text=True,
        ).strip()

    def warm(self, *, failure=0, expected=None):
        prewarm(
            self.repo,
            target="fixture-target",
            expected_sha=expected or self.head,
            runner_temp=self.root / "runner temp",
            target_dir=self.root / "shared target",
            cargo=(sys.executable, str(self.fake_cargo), str(self.calls), str(failure)),
        )

    def assert_original_retained(self):
        self.assertEqual(checkout_identity(self.repo, self.head)["head"], self.head)
        for path, data in self.original.items():
            self.assertEqual(path.read_bytes(), data)
        self.assertEqual(
            self.git("worktree", "list", "--porcelain").count("worktree "), 1
        )
        self.assertEqual(list((self.root / "runner temp").glob("chef-*")), [])

    def test_destructive_cook_cannot_hide_actual_source_error(self):
        self.warm()
        self.assert_original_retained()
        calls = [json.loads(line) for line in self.calls.read_text().splitlines()]
        cook = next(row for row in calls if row["args"][:2] == ["chef", "cook"])
        self.assertNotEqual(Path(cook["cwd"]).resolve(), self.workspace.resolve())
        self.assertIn(str((self.root / "shared target").resolve()), cook["args"])
        receipt = json.loads(
            (self.root / "runner temp/cargo-chef-source-custody.json").read_text()
        )
        self.assertEqual(receipt["before"], receipt["after"])
        self.assertEqual(
            set(receipt["prewarm_source_changes"]),
            {"codex-rs/Cargo.toml", "codex-rs/src/lib.rs"},
        )

    def test_failed_cook_propagates_and_keeps_original_source(self):
        with self.assertRaises(subprocess.CalledProcessError) as error:
            self.warm(failure=23)
        self.assertEqual(error.exception.returncode, 23)
        self.assert_original_retained()

    def test_dirty_checkout_is_rejected_before_any_prewarm(self):
        self.source.write_text("changed source\n")
        with self.assertRaises(subprocess.CalledProcessError):
            self.warm()
        self.assertEqual(self.source.read_text(), "changed source\n")
        self.assertFalse(self.calls.exists())

    def test_different_head_is_rejected_before_any_prewarm(self):
        with self.assertRaises(RuntimeError):
            self.warm(expected="0" * 40)
        self.assertFalse(self.calls.exists())


if __name__ == "__main__":
    unittest.main()
