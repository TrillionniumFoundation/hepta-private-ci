import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from control_engineering_v2.candidate import _git_bytes
from control_engineering_v2.control_plane import EngineeringError
from control_engineering_v2.git_security import git_environment, run_git


class GitIdentityBoundaryTests(unittest.TestCase):
    def repository(self, path: Path, content: str) -> str:
        path.mkdir()
        for arguments in (
            ("init", "-q"),
            ("config", "user.email", "review@example.invalid"),
            ("config", "user.name", "Review fixture"),
            ("config", "remote.origin.url", "https://github.com/owner/expected.git"),
        ):
            subprocess.run(["git", "-C", str(path), *arguments], check=True,
                           stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                           env=git_environment())
        (path / "source.txt").write_text(content)
        for arguments in (("add", "source.txt"), ("commit", "-qm", content)):
            subprocess.run(["git", "-C", str(path), *arguments], check=True,
                           stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                           env=git_environment())
        return run_git(path, "rev-parse", "HEAD")

    def test_inherited_git_directory_cannot_substitute_source_identity(self):
        with tempfile.TemporaryDirectory() as temporary:
            parent = Path(temporary)
            expected = parent / "expected"
            foreign = parent / "foreign"
            expected_head = self.repository(expected, "expected source")
            self.repository(foreign, "foreign source")
            with patch.dict(os.environ, {"GIT_DIR": str(foreign / ".git"),
                                         "GIT_WORK_TREE": str(foreign)}):
                self.assertEqual(run_git(expected, "rev-parse", "HEAD"), expected_head)
                self.assertEqual(_git_bytes(expected, "rev-parse", "HEAD").decode().strip(), expected_head)

    def test_inherited_config_cannot_substitute_repository_registration(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "repository"
            self.repository(root, "source")
            with patch.dict(os.environ, {"GIT_CONFIG_COUNT": "1",
                "GIT_CONFIG_KEY_0": "remote.origin.url",
                "GIT_CONFIG_VALUE_0": "https://github.com/attacker/substitute.git"}):
                self.assertEqual(run_git(root, "config", "--get", "remote.origin.url"),
                                 "https://github.com/owner/expected.git")
                self.assertEqual(_git_bytes(root, "config", "--get", "remote.origin.url").decode().strip(),
                                 "https://github.com/owner/expected.git")

    @unittest.skipUnless(os.name == "posix", "POSIX fsmonitor hook fixture")
    def test_read_only_status_does_not_execute_repository_fsmonitor(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "repository"
            self.repository(root, "source")
            marker = root / "hook-ran"
            hook = root / ".git" / "fsmonitor-hook"
            hook.write_text(f"#!/bin/sh\nprintf invoked > '{marker}'\nprintf 'token\\0'\n")
            hook.chmod(0o700)
            subprocess.run(["git", "-C", str(root), "config", "core.fsmonitor", str(hook)],
                           check=True, env=git_environment())
            self.assertEqual(run_git(root, "status", "--porcelain"), "")
            self.assertFalse(marker.exists())

    @unittest.skipUnless(os.name == "posix", "POSIX clean filter fixture")
    def test_status_refuses_executable_filters_before_refreshing_worktree(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "repository"
            self.repository(root, "source")
            marker = root / "filter-ran"
            hook = root / ".git" / "clean-filter"
            hook.write_text(f"#!/bin/sh\nprintf invoked > '{marker}'\ncat\n")
            hook.chmod(0o700)
            (root / ".gitattributes").write_text("source.txt filter=hostile\n")
            subprocess.run(["git", "-C", str(root), "add", ".gitattributes"],
                           check=True, env=git_environment())
            # Same-length mutation forces Git to read and clean the file rather
            # than reporting a size difference from stat metadata alone.
            (root / "source.txt").write_text("mutate")
            for driver in ("clean", "process"):
                with self.subTest(driver=driver):
                    subprocess.run(["git", "-C", str(root), "config",
                                    f"filter.hostile.{driver}", str(hook)],
                                   check=True, env=git_environment())
                    for read in (run_git, _git_bytes):
                        with self.assertRaisesRegex(EngineeringError, "repository_git_filter_unsupported"):
                            read(root, "status", "--porcelain", "--untracked-files=all")
                    self.assertFalse(marker.exists())
                    subprocess.run(["git", "-C", str(root), "config", "--unset",
                                    f"filter.hostile.{driver}"],
                                   check=True, env=git_environment())
            included = root / ".git" / "filter-config"
            included.write_text(f'[filter "hostile"]\n\tclean = {hook}\n')
            subprocess.run(["git", "-C", str(root), "config", "include.path", str(included)],
                           check=True, env=git_environment())
            for read in (run_git, _git_bytes):
                with self.assertRaisesRegex(EngineeringError, "repository_git_filter_unsupported"):
                    read(root, "status", "--porcelain")
            self.assertFalse(marker.exists())


if __name__ == "__main__":
    unittest.main()
