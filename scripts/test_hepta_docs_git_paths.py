"""Git changes retain literal filenames while declarations keep strict grammar."""

import importlib.util
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

SCRIPTS = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS))
SPEC = importlib.util.spec_from_file_location(
    "hepta_docs_git_paths", SCRIPTS / "hepta-docs.py"
)
DOCS = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(DOCS)


class GitChangedPathTests(unittest.TestCase):
    def test_git_changed_paths_preserve_literal_metacharacters(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)

            def git(*arguments):
                return subprocess.check_output(
                    ["git", "-C", str(root), *arguments],
                    stderr=subprocess.PIPE,
                    text=True,
                ).strip()

            git("init", "-q")
            (root / "seed.txt").write_text("base\n", encoding="utf-8")
            git("add", "--", "seed.txt")
            identity = [
                "-c",
                "user.name=path-fixture",
                "-c",
                "user.email=path@example.invalid",
            ]
            git(*identity, "commit", "-qm", "base")
            base = git("rev-parse", "HEAD")
            paths = {
                "vendor/array[0].snippet",
                "vendor/Symbol List%3A {}!.snippet",
                "vendor/unicode-路径.snippet",
            }
            for name in paths:
                path = root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("literal fixture\n", encoding="utf-8")
            git("add", "--", "vendor")
            git(*identity, "commit", "-qm", "literal filenames")
            source = git("rev-parse", "HEAD")
            context = {
                "base": base,
                "source": source,
                "number": 1,
                "event": {"repository": {"id": DOCS.REPO_ID, "full_name": DOCS.REPO}},
            }
            with (
                patch.object(DOCS, "ROOT", root),
                patch.object(DOCS, "event_context", return_value=context),
            ):
                self.assertEqual(DOCS.pull_request_changed_paths(), paths)

    def test_manifest_paths_still_reject_literal_pattern_characters(self):
        for character in "*?[]{}!%":
            path = f"vendor/literal{character}.txt"
            with self.subTest(character=character):
                self.assertEqual(DOCS.canonical_repository_path(path, "Git path"), path)
                with self.assertRaisesRegex(SystemExit, "canonical exact POSIX path"):
                    DOCS.canonical_exact_path(path, "manifest path")

    def test_both_path_sources_reject_aliases_escapes_and_control_characters(self):
        for path in (
            "/absolute",
            "~home/file",
            "../escape",
            "a/../b",
            "a/./b",
            "a//b",
            "a\\b",
            "a/",
            ".git/config",
            " leading",
            "trailing ",
            "line\nbreak",
            "tab\tname",
            "nul\0name",
            "delete\x7fname",
        ):
            for validate in (DOCS.canonical_repository_path, DOCS.canonical_exact_path):
                with self.subTest(path=path, validator=validate.__name__):
                    with self.assertRaises(SystemExit):
                        validate(path, "untrusted path")


if __name__ == "__main__":
    unittest.main()
