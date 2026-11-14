"""Exercise the actual Git blob policy, including pinned historical assets."""

import hashlib
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

CHECKER = Path(__file__).resolve().parents[1] / "check_blob_size.py"
LIMIT = 512000


class BlobSizePolicyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.repo = self.root / "repo"
        self.repo.mkdir()
        self.git("init", "-q")
        self.git("config", "user.name", "Blob policy fixture")
        self.git("config", "user.email", "blob-policy@example.invalid")
        (self.repo / "baseline.txt").write_text("fixture\n")
        self.git("add", ".")
        self.git("commit", "-qm", "baseline")
        self.base = self.git("rev-parse", "HEAD").strip()
        self.allowlist = self.root / "allowlist.txt"
        self.allowlist.write_text("")

    def git(self, *args):
        return subprocess.check_output(
            ["git", *args], cwd=self.repo, text=True, stderr=subprocess.PIPE
        )

    def commit_asset(self, content, path="evidence.gz"):
        (self.repo / path).write_bytes(content)
        self.git("add", "--", path)
        self.git("commit", "-qm", "asset")
        return self.git("rev-parse", "HEAD").strip()

    def check(self, head):
        return subprocess.run(
            [
                sys.executable,
                "-B",
                str(CHECKER),
                "--base",
                self.base,
                "--head",
                head,
                "--max-bytes",
                str(LIMIT),
                "--allowlist",
                str(self.allowlist),
            ],
            cwd=self.repo,
            text=True,
            capture_output=True,
            check=False,
        )

    def pin(self, content, path="evidence.gz"):
        digest = hashlib.sha256(content).hexdigest()
        return f"sha256:{digest} {path}\n"

    def test_original_limit_accepts_boundary_and_refuses_one_extra_byte(self):
        head = self.commit_asset(b"x" * LIMIT)
        self.assertEqual(self.check(head).returncode, 0)
        head = self.commit_asset(b"x" * (LIMIT + 1))
        self.assertEqual(self.check(head).returncode, 1)

    def test_exact_binary_pin_preserves_asset_without_allowing_changed_bytes(self):
        original = b"\0" + b"a" * LIMIT
        head = self.commit_asset(original)
        self.allowlist.write_text(self.pin(original))
        self.assertEqual(self.check(head).returncode, 0)
        changed = b"\0" + b"b" + b"a" * (LIMIT - 1)
        head = self.commit_asset(changed)
        self.assertEqual(self.check(head).returncode, 1)
        # Hashing the current worktree instead of the requested revision would
        # incorrectly allow this changed commit after the original is restored.
        (self.repo / "evidence.gz").write_bytes(original)
        self.assertEqual(self.check(head).returncode, 1)

    def test_same_bytes_at_an_unlisted_path_are_refused(self):
        original = b"\0" + b"x" * LIMIT
        head = self.commit_asset(original, "other.gz")
        self.allowlist.write_text(self.pin(original))
        self.assertEqual(self.check(head).returncode, 1)

    def test_pin_uses_requested_head_even_if_worktree_has_different_bytes(self):
        original = b"\0" + b"x" * LIMIT
        head = self.commit_asset(original)
        self.allowlist.write_text(self.pin(original))
        (self.repo / "evidence.gz").write_bytes(b"changed worktree")
        self.assertEqual(self.check(head).returncode, 0)

    def test_legacy_exact_asset_entry_remains_supported_without_a_prefix_match(self):
        original = b"\0" + b"x" * LIMIT
        head = self.commit_asset(original)
        self.allowlist.write_text("# existing asset\nevidence.gz\n")
        self.assertEqual(self.check(head).returncode, 0)
        head = self.commit_asset(original, "evidence.gz.copy")
        self.assertEqual(self.check(head).returncode, 1)

    def test_malformed_or_conflicting_pins_fail_closed(self):
        original = b"\0" + b"x" * LIMIT
        head = self.commit_asset(original)
        for policy in (
            "sha256:short evidence.gz\n",
            "sha256:" + "f" * 64 + "\n",
            self.pin(original) + "evidence.gz\n",
            "evidence.gz\n" + self.pin(original),
        ):
            with self.subTest(policy=policy):
                self.allowlist.write_text(policy)
                self.assertNotEqual(self.check(head).returncode, 0)

    def test_pin_preserves_exact_paths_with_spaces(self):
        original = b"\0" + b"x" * LIMIT
        head = self.commit_asset(original, "historical evidence.gz")
        self.allowlist.write_text(self.pin(original, "historical evidence.gz"))
        self.assertEqual(self.check(head).returncode, 0)


if __name__ == "__main__":
    unittest.main()
