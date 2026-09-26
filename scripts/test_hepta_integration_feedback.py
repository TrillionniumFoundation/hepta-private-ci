#!/usr/bin/env python3
"""Exercise the real Git diagnostics and preserve conflict/failure distinctions."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import subprocess
import tarfile
import tempfile
import unittest
from unittest.mock import patch

SCRIPT = Path(__file__).with_name("hepta_integration_diagnostics.py")
spec = importlib.util.spec_from_file_location("diagnostics", SCRIPT)
subject = importlib.util.module_from_spec(spec)
spec.loader.exec_module(subject)


class IntegrationFeedbackTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.repo = self.root / "repo"
        self.repo.mkdir()
        self.git("init", "--quiet")
        self.write("record.txt", "base\n")
        self.base = self.commit()

    def git(self, *args):
        return subprocess.run(
            [
                "git",
                "--no-replace-objects",
                "-c",
                "user.name=Integration fixture",
                "-c",
                "user.email=fixture@example.invalid",
                *args,
            ],
            cwd=self.repo,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()

    def write(self, name, value):
        path = self.repo / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(value, encoding="utf-8")

    def commit(self):
        self.git("add", "--all")
        self.git("commit", "--quiet", "--no-gpg-sign", "-m", "fixture")
        return self.git("rev-parse", "HEAD")

    def branches(self, path="record.txt", conflict=True):
        self.write(path, "source\n")
        source = self.commit()
        self.git("checkout", "--quiet", "--detach", self.base)
        self.write(path if conflict else "target.txt", "target\n")
        target = self.commit()
        self.git("checkout", "--quiet", "--detach", source)
        return source, target

    def invoke(self, source, target, *extra):
        return subprocess.run(
            [
                "python3",
                str(SCRIPT),
                "--root",
                str(self.repo),
                "--source",
                source,
                "--target",
                target,
                "--output",
                str(self.root / "out"),
                *extra,
            ],
            capture_output=True,
            text=True,
        )

    def test_clean_merge_keeps_checkout_and_binds_exact_trees(self):
        source, target = self.branches(conflict=False)
        report = subject.diagnose(self.repo, source, target)
        self.assertTrue(report["mergeable"])
        self.assertFalse(report["qualification"])
        self.assertEqual(report["source_tree"], self.git("rev-parse", "HEAD^{tree}"))
        self.assertEqual([row["path"] for row in report["entries"]], ["target.txt"])
        self.assertEqual(self.git("rev-parse", "HEAD"), source)
        self.assertEqual(self.git("status", "--porcelain"), "")

    def test_conflict_is_failure_but_retains_all_three_real_blobs(self):
        source, target = self.branches()
        result = self.invoke(source, target)
        self.assertEqual(result.returncode, 1, result.stderr)
        report = json.loads((self.root / "out/integration.json").read_text())
        self.assertFalse(report["mergeable"])
        self.assertEqual(report["conflicts"], ["record.txt"])
        self.assertEqual({stage["stage"] for stage in report["stages"]}, {1, 2, 3})
        contents = {
            (self.root / "out/conflict-blobs" / row["object"]).read_bytes()
            for row in report["stages"]
        }
        self.assertEqual(contents, {b"base\n", b"source\n", b"target\n"})
        self.assertEqual(self.git("status", "--porcelain"), "")

    def test_tabs_newlines_spaces_and_globs_are_literal_paths(self):
        for name in ["a\tb.txt", "a\nb.txt", "a b.txt", "[x]*.txt"]:
            with self.subTest(name=name):
                self.git("checkout", "--quiet", "--detach", self.base)
                source, target = self.branches(name)
                report = subject.diagnose(self.repo, source, target)
                self.assertEqual(report["conflicts"], [name])
                self.assertEqual([row["path"] for row in report["entries"]], [name])

    def test_raw_diff_binds_modes_objects_and_literal_paths(self):
        self.write("executable", "before\n")
        self.write("link", "before\n")
        self.write("removed", "before\n")
        source = self.commit()
        names = [
            "[x]*.txt",
            ":(exclude)record.txt",
            "a\tb.txt",
            "a\nb.txt",
            "中文.txt",
            "nested/file",
        ]
        for name in names:
            self.write(name, "after\n")
        (self.repo / "executable").chmod(0o755)
        (self.repo / "link").unlink()
        (self.repo / "link").symlink_to("record.txt")
        (self.repo / "removed").unlink()
        target = self.commit()
        self.git("checkout", "--quiet", "--detach", source)
        report = subject.diagnose(self.repo, source, target)
        expected = [
            {
                "path": name,
                "mode": "100644",
                "type": "blob",
                "object": self.git("rev-parse", f"{target}:{name}"),
            }
            for name in names
        ]
        expected.extend(
            [
                {
                    "path": "executable",
                    "mode": "100755",
                    "type": "blob",
                    "object": self.git("rev-parse", f"{target}:executable"),
                },
                {
                    "path": "link",
                    "mode": "120000",
                    "type": "blob",
                    "object": self.git("rev-parse", f"{target}:link"),
                },
                {"path": "removed", "deleted": True},
            ]
        )
        self.assertEqual(
            report["entries"], sorted(expected, key=lambda row: row["path"])
        )

    def test_gitlink_is_a_commit_not_a_blob(self):
        source = self.base
        self.git("update-index", "--add", "--cacheinfo", f"160000,{source},submodule")
        self.git("commit", "--quiet", "--no-gpg-sign", "-m", "gitlink fixture")
        target = self.git("rev-parse", "HEAD")
        self.git("checkout", "--quiet", "--detach", source)
        report = subject.diagnose(self.repo, source, target)
        self.assertEqual(
            report["entries"],
            [
                {
                    "path": "submodule",
                    "mode": "160000",
                    "type": "commit",
                    "object": source,
                }
            ],
        )

    def test_git_process_count_does_not_grow_with_changed_files(self):
        counts = []
        for count in (1, 128):
            self.git("checkout", "--quiet", "--detach", self.base)
            for index in range(count):
                self.write(f"module_{index:03}/src/lib.rs", "pub fn value() {}\n")
            target = self.commit()
            self.git("checkout", "--quiet", "--detach", self.base)
            with patch.object(subject, "git", wraps=subject.git) as calls:
                report = subject.diagnose(self.repo, self.base, target)
            self.assertEqual(len(report["entries"]), count)
            self.assertTrue(all("object" in entry for entry in report["entries"]))
            counts.append(calls.call_count)
        self.assertEqual(counts[0], counts[1])

    def test_missing_commit_is_error_not_clean_merge(self):
        result = self.invoke(self.base, "f" * 40)
        self.assertEqual(result.returncode, 2)
        self.assertFalse((self.root / "out/integration.json").exists())

    def test_mutable_ref_rejected(self):
        result = self.invoke("HEAD", self.base)
        self.assertEqual(result.returncode, 2)

    def test_wrong_checkout_rejected(self):
        source, target = self.branches()
        self.git("checkout", "--quiet", "--detach", target)
        with self.assertRaisesRegex(ValueError, "checkout"):
            subject.diagnose(self.repo, source, target)

    def test_dirty_and_staged_source_are_rejected(self):
        for staged in (False, True):
            self.git("reset", "--hard", self.base)
            self.write("record.txt", "not committed\n")
            if staged:
                self.git("add", "record.txt")
            with self.assertRaises(ValueError):
                subject.diagnose(self.repo, self.base, self.base)

    def test_tag_or_tree_object_cannot_impersonate_commit(self):
        tree = self.git("rev-parse", "HEAD^{tree}")
        with self.assertRaisesRegex(ValueError, "commits"):
            subject.diagnose(self.repo, self.base, tree)

    def test_archives_exclude_git_and_untracked_files(self):
        source, target = self.branches(conflict=False)
        self.write("untracked-secret", "not source\n")
        result = self.invoke(source, target, "--archives")
        self.assertEqual(result.returncode, 0, result.stderr)
        with tarfile.open(self.root / "out/source.tar.gz") as archive:
            self.assertIn("record.txt", archive.getnames())
            self.assertNotIn("untracked-secret", archive.getnames())
            self.assertFalse(
                any(name.startswith(".git/") for name in archive.getnames())
            )

    def test_output_directory_cannot_be_overwritten(self):
        (self.root / "out").mkdir()
        result = self.invoke(self.base, self.base)
        self.assertEqual(result.returncode, 2)

    def test_deleted_path_is_explicit(self):
        source = self.base
        (self.repo / "record.txt").unlink()
        target = self.commit()
        self.git("checkout", "--quiet", "--detach", source)
        report = subject.diagnose(self.repo, source, target)
        self.assertEqual(report["entries"], [{"path": "record.txt", "deleted": True}])

    def test_unrelated_history_is_error_not_conflict(self):
        self.git("checkout", "--quiet", "--orphan", "unrelated")
        self.write("record.txt", "other root\n")
        other = self.commit()
        self.git("checkout", "--quiet", "--detach", self.base)
        result = self.invoke(self.base, other)
        self.assertEqual(result.returncode, 2)


if __name__ == "__main__":
    unittest.main()
