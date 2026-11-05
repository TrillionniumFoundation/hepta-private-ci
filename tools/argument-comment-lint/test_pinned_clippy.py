"""Exercise the real Git compatibility alias without contacting the network."""

import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from with_pinned_clippy import CLIPPY_URL, git_environment, main, pinned_inputs, prepare_mirror


class PinnedClippyTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.env = git_environment(dict(os.environ))

    def git(self, *args, env=None):
        return subprocess.check_output(
            ["git", *args], env=env or self.env, text=True, stderr=subprocess.PIPE
        ).strip()

    def source_history(self):
        source = self.root / "upstream"
        self.git("init", "--quiet", "--initial-branch=main", str(source))
        self.git("-C", str(source), "config", "user.name", "Clippy fixture")
        self.git("-C", str(source), "config", "user.email", "clippy-fixture@example.invalid")
        toolchain = source / "rust-toolchain.toml"
        toolchain.write_text('[toolchain]\nchannel = "nightly-2025-09-18"\n', encoding="utf-8")
        self.git("-C", str(source), "add", ".")
        self.git("-C", str(source), "commit", "--quiet", "-m", "pinned nightly")
        revision = self.git("-C", str(source), "rev-parse", "HEAD")
        toolchain.write_text('[toolchain]\nchannel = "nightly-2026-01-01"\n', encoding="utf-8")
        self.git("-C", str(source), "commit", "--quiet", "-am", "new upstream main")
        return source, revision

    def test_original_clone_and_master_lookup_resolve_the_pinned_commit(self):
        source, revision = self.source_history()
        head = self.git("-C", str(source), "rev-parse", "HEAD")
        mirror = self.root / "mirror.git"
        prepare_mirror(source.as_uri(), revision, "nightly-2025-09-18", mirror, self.env)
        clone = self.root / "dylint-clone"
        child = git_environment(self.env, mirror)
        self.git("clone", "--quiet", CLIPPY_URL, str(clone), env=child)
        self.assertEqual(self.git("-C", str(clone), "rev-parse", "master"), revision)
        self.assertEqual(self.git("-C", str(clone), "rev-parse", "HEAD"), revision)
        self.assertEqual(self.git("-C", str(source), "rev-parse", "HEAD"), head)
        self.assertNotEqual(head, revision)
        self.assertFalse((mirror / "shallow").exists())

    def test_mismatched_nightly_is_rejected_before_running_the_command(self):
        source, revision = self.source_history()
        with self.assertRaisesRegex(ValueError, "different nightly"):
            prepare_mirror(
                source.as_uri(), revision, "nightly-2025-09-19",
                self.root / "wrong-channel.git", self.env,
            )

    def test_missing_commit_cannot_fall_back_to_the_current_branch(self):
        source, _ = self.source_history()
        with self.assertRaises(subprocess.CalledProcessError):
            prepare_mirror(
                source.as_uri(), "f" * 40, "nightly-2025-09-18",
                self.root / "missing.git", self.env,
            )

    def test_manifest_requires_an_immutable_official_source(self):
        (self.root / "rust-toolchain").write_text(
            '[toolchain]\nchannel = "nightly-2025-09-18"\n', encoding="utf-8"
        )
        for url, revision in ((CLIPPY_URL, "main"), ("https://example.invalid/repo", "a" * 40)):
            with self.subTest(url=url, revision=revision):
                (self.root / "Cargo.toml").write_text(
                    '[dependencies]\nclippy_utils = { git = "' + url
                    + '", rev = "' + revision + '" }\n', encoding="utf-8",
                )
                with self.assertRaisesRegex(ValueError, "official URL and an exact commit"):
                    pinned_inputs(self.root)

    def test_git_configuration_is_scoped_to_a_child_environment(self):
        original = {
            "PATH": os.environ["PATH"], "KEEP_ME": "unchanged",
            "GIT_CONFIG_COUNT": "1", "GIT_CONFIG_KEY_0": "credential.helper",
            "GIT_CONFIG_VALUE_0": "unexpected-helper",
        }
        saved = original.copy()
        child = git_environment(original, self.root / "mirror.git")
        self.assertEqual(original, saved)
        self.assertEqual(child["KEEP_ME"], "unchanged")
        values = [child[f"GIT_CONFIG_VALUE_{i}"] for i in range(int(child["GIT_CONFIG_COUNT"]))]
        self.assertNotIn("unexpected-helper", values)
        self.assertEqual(values[-1], CLIPPY_URL)
        self.assertEqual(child["GIT_CONFIG_GLOBAL"], os.devnull)

    def test_original_command_arguments_and_failure_exit_are_preserved(self):
        command = ["cargo", "test", "--", "unchanged fixture"]
        with (
            patch("with_pinned_clippy.pinned_inputs", return_value=("a" * 40, "nightly-2025-09-18")),
            patch("with_pinned_clippy.prepare_mirror"),
            patch("with_pinned_clippy.subprocess.run", return_value=subprocess.CompletedProcess(command, 37)) as run,
        ):
            self.assertEqual(main(["--", *command]), 37)
        self.assertEqual(run.call_args.args[0], command)


if __name__ == "__main__":
    unittest.main()
