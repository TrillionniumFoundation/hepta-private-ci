import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import capture_module_lock_evidence as capture


class CaptureTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.base = Path(self.temporary.name)
        self.root = self.base / "checkout"
        self.root.mkdir()
        self.runner_temp = self.base / "runner-temp"
        self.runner_temp.mkdir()
        self.output = self.runner_temp / "bazel-execution-logs/module-lock-evidence"
        self.git("init", "--quiet")
        self.git("config", "user.name", "Fixture")
        self.git("config", "user.email", "fixture@example.invalid")
        self.git("config", "core.autocrlf", "false")
        for name in (
            "MODULE.bazel",
            "MODULE.bazel.lock",
            ".bazelrc",
            ".bazelversion",
            "codex-rs/Cargo.toml",
            "codex-rs/Cargo.lock",
            "lib/Cargo.toml",
            "a.bzl",
        ):
            destination = self.root / name
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes((name + "\n").encode())
        self.git("add", ".")
        self.git("commit", "--quiet", "-m", "Fixture")
        self.baseline = (self.root / capture.LOCK).read_bytes()
        self.current = b'{"generated_fixture": true}\n'
        (self.root / capture.LOCK).write_bytes(self.current)

    def git(self, *args):
        return subprocess.check_output(
            ["git", "-C", str(self.root), *args], stderr=subprocess.PIPE
        )

    def run_capture(self, outcome="success", status="success"):
        return capture.capture(self.root, self.runner_temp, outcome, status)

    def manifest(self):
        return json.loads((self.output / "manifest.json").read_bytes())

    def test_complete_capture_preserves_lock_head_raw_git_and_inputs(self):
        before = self.git("status", "--porcelain=v1", "-z")
        self.assertEqual(self.run_capture(), 0)
        result = self.manifest()
        self.assertEqual(result["classification"], "UNVERIFIED")
        self.assertEqual(result["candidate_kind"], "successful_build_candidate")
        self.assertEqual(result["lock_validation"], "NOT_PERFORMED")
        self.assertEqual(result["head"], self.git("rev-parse", "HEAD").decode().strip())
        self.assertEqual(
            result["tree"], self.git("rev-parse", "HEAD^{tree}").decode().strip()
        )
        self.assertEqual(
            (self.output / "MODULE.bazel.lock.HEAD").read_bytes(), self.baseline
        )
        self.assertEqual(
            (self.output / "MODULE.bazel.lock.current").read_bytes(), self.current
        )
        self.assertEqual(before, self.git("status", "--porcelain=v1", "-z"))
        self.assertEqual(
            result["inputs"]["lib/Cargo.toml"],
            {
                "head_blob": self.git("rev-parse", "HEAD:lib/Cargo.toml")
                .decode()
                .strip(),
                **capture.digest((self.root / "lib/Cargo.toml").read_bytes()),
            },
        )
        for name, info in result["files"].items():
            self.assertEqual(info, capture.digest((self.output / name).read_bytes()))
        self.assertEqual(
            (self.output / "git-diff-HEAD.patch").read_bytes(),
            self.git(*capture.DIFF, result["head"], "--", capture.LOCK),
        )

    def test_failed_or_skipped_build_is_never_a_validated_lock(self):
        for outcome, status in (
            ("failure", "failure"),
            ("skipped", "failure"),
            ("success", "failure"),
        ):
            with self.subTest(outcome=outcome, status=status):
                self.assertEqual(self.run_capture(outcome, status), 0)
                result = self.manifest()
                self.assertEqual(
                    result["candidate_kind"],
                    "partial_failed_or_skipped_build_candidate",
                )
                self.assertEqual(result["classification"], "UNVERIFIED")
                shutil.rmtree(self.output)

    def test_unchanged_lock_is_retained_not_claimed_regenerated(self):
        (self.root / capture.LOCK).write_bytes(self.baseline)
        self.assertEqual(self.run_capture("skipped", "failure"), 0)
        self.assertFalse(self.manifest()["lock_bytes_differ_from_HEAD_blob"])

    def test_staged_and_unstaged_lock_diffs_are_both_retained(self):
        self.git("add", capture.LOCK)
        (self.root / capture.LOCK).write_bytes(b"another current state\n")
        self.assertEqual(self.run_capture(), 0)
        for name, args in (
            ("index", ["--cached", "HEAD", "--", capture.LOCK]),
            ("worktree", ["--"]),
        ):
            self.assertEqual(
                (self.output / f"git-diff-{name}.patch").read_bytes(),
                self.git(*capture.DIFF, *args),
            )

    def test_source_drift_retains_evidence_and_fails_capture(self):
        source = self.root / "MODULE.bazel"
        baseline = source.read_bytes()
        # Binary unrelated bytes must not be materialized in retained patches.
        unrelated = b"DO_NOT_RETAIN_NONLOCK_CONTENT\0binary\n"
        for staged_then_restored in (False, True):
            with self.subTest(staged_then_restored=staged_then_restored):
                try:
                    source.write_bytes(unrelated)
                    if staged_then_restored:
                        self.git("add", "MODULE.bazel")
                        source.write_bytes(baseline)
                        self.assertEqual(
                            self.git("diff", "HEAD", "--", "MODULE.bazel"), b""
                        )
                        self.assertIn(
                            b"MM MODULE.bazel", self.git("status", "--porcelain=v1")
                        )
                    self.assertEqual(self.run_capture(), 1)
                    result = self.manifest()
                    self.assertEqual(result["error"], "source_drift")
                    self.assertTrue(
                        (self.output / "MODULE.bazel.lock.current").is_file()
                    )
                    self.assertTrue(result["tracked_source_drift"])
                    for scope, args in (
                        ("HEAD", ["HEAD"]),
                        ("index", ["--cached", "HEAD"]),
                        ("worktree", []),
                    ):
                        self.assertEqual(
                            (self.output / f"git-diff-{scope}.patch").read_bytes(),
                            self.git(*capture.DIFF, *args, "--", capture.LOCK),
                        )
                    self.assertIn(
                        b"MODULE.bazel\0",
                        (self.output / "git-drift-worktree-names.z").read_bytes(),
                    )
                    if staged_then_restored:
                        self.assertIn(
                            b"MODULE.bazel\0",
                            (self.output / "git-drift-index-names.z").read_bytes(),
                        )
                finally:
                    if self.output.exists():
                        shutil.rmtree(self.output)
                    source.write_bytes(baseline)
                    self.git("add", "MODULE.bazel")

    def test_untracked_input_fails_without_copying_its_contents(self):
        (self.root / "untracked.txt").write_bytes(b"DO_NOT_COPY_UNTRACKED_CONTENT")
        self.assertEqual(self.run_capture(), 1)
        self.assertTrue(self.manifest()["untracked_paths_present"])
        for output in self.output.iterdir():
            self.assertNotIn(b"DO_NOT_COPY_UNTRACKED_CONTENT", output.read_bytes())

    def test_non_regular_current_lock_is_rejected(self):
        lock = self.root / capture.LOCK
        lock.unlink()
        lock.mkdir()
        self.assertEqual(self.run_capture(), 1)
        self.assertEqual(self.manifest()["error"], "not_a_regular_file_or_directory")

    def test_symlink_current_lock_is_rejected(self):
        lock = self.root / capture.LOCK
        lock.unlink()
        try:
            lock.symlink_to(self.root / "MODULE.bazel")
        except OSError:
            self.skipTest("symlink creation is unavailable")
        self.assertEqual(self.run_capture(), 1)
        self.assertEqual(self.manifest()["error"], "symlink_or_reparse_point")

    def test_byte_limit_is_failure_not_truncated_success(self):
        with patch.object(capture, "MAX_FILE", len(self.current) - 1):
            self.assertEqual(self.run_capture(), 1)
        self.assertEqual(self.manifest()["error"], "source_file_byte_limit")

    def test_git_output_limit_is_failure(self):
        with patch.object(capture, "MAX_GIT", 1):
            self.assertEqual(self.run_capture(), 1)
        self.assertEqual(self.manifest()["error"], "git_output_byte_limit")

    def test_lock_change_during_capture_is_detected(self):
        original = capture.source_bytes
        reads = 0

        def mutate(root, name):
            nonlocal reads
            if name == capture.LOCK:
                reads += 1
                if reads == 2:
                    (root / name).write_bytes(b"concurrent change\n")
            return original(root, name)

        with patch.object(capture, "source_bytes", side_effect=mutate):
            self.assertEqual(self.run_capture(), 1)
        self.assertEqual(self.manifest()["error"], "inputs_changed_during_capture")

    def test_input_change_during_capture_is_detected(self):
        original = capture.input_hashes
        reads = 0

        def mutate(root, inventory):
            nonlocal reads
            reads += 1
            if reads == 2:
                (root / "lib/Cargo.toml").write_bytes(b"concurrent input\n")
            return original(root, inventory)

        with patch.object(capture, "input_hashes", side_effect=mutate):
            self.assertEqual(self.run_capture(), 1)
        self.assertEqual(self.manifest()["error"], "inputs_changed_during_capture")

    def test_missing_lock_and_git_failure_fail_closed(self):
        (self.root / capture.LOCK).unlink()
        self.assertEqual(self.run_capture(), 1)
        self.assertEqual(self.manifest()["error"], "FileNotFoundError")
        shutil.rmtree(self.output)
        with patch.object(
            capture, "git", side_effect=capture.CaptureError("git_read_failed")
        ):
            self.assertEqual(self.run_capture(), 1)
        self.assertEqual(self.manifest()["error"], "git_read_failed")

    def test_artifact_symlink_is_not_followed(self):
        other = self.base / "other"
        other.mkdir()
        try:
            (self.runner_temp / "bazel-execution-logs").symlink_to(
                other, target_is_directory=True
            )
        except OSError:
            self.skipTest("symlink creation is unavailable")
        with self.assertRaisesRegex(capture.CaptureError, "symlink_or_reparse_point"):
            self.run_capture()
        self.assertEqual(list(other.iterdir()), [])

    def test_binary_diff_and_crlf_input_bytes_are_preserved(self):
        (self.root / capture.LOCK).write_bytes(b"binary\0lock\r\n")
        self.git("config", "core.autocrlf", "true")
        (self.root / "lib/Cargo.toml").write_bytes(b"lib/Cargo.toml\r\n")
        self.assertEqual(self.run_capture(), 0)
        self.assertIn(
            b"GIT binary patch", (self.output / "git-diff-HEAD.patch").read_bytes()
        )
        self.assertFalse(self.manifest()["tracked_source_drift"])
        self.assertEqual(
            self.manifest()["inputs"]["lib/Cargo.toml"]["sha256"],
            capture.digest(b"lib/Cargo.toml\r\n")["sha256"],
        )

    def test_existing_capture_and_output_inside_checkout_are_rejected(self):
        self.assertEqual(self.run_capture(), 0)
        with self.assertRaises(FileExistsError):
            self.run_capture()
        with self.assertRaisesRegex(
            capture.CaptureError, "artifact_directory_inside_checkout"
        ):
            capture.capture(self.root, self.root, "success", "success")


if __name__ == "__main__":
    unittest.main()
