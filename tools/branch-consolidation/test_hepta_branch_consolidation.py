"""Real local Git remotes exercise backup, ancestry, races and atomic deletion."""
from pathlib import Path
import json
import tempfile
import unittest

import hepta_branch_consolidation as tool


class RetirementTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name)
        self.remote = self.home / "remote.git"
        self.root = self.home / "work"
        self.remote.mkdir()
        self.root.mkdir()
        tool.git(self.remote, "init", "--bare")
        tool.git(self.root, "init", "--initial-branch=main")
        tool.git(self.root, "config", "user.name", "Fixture")
        tool.git(self.root, "config", "user.email", "fixture@example.invalid")
        (self.root / "source.txt").write_text("base\n")
        tool.git(self.root, "add", ".")
        tool.git(self.root, "commit", "-m", "base")
        tool.git(self.root, "remote", "add", "origin", str(self.remote))
        tool.git(self.root, "branch", "merged")
        tool.git(self.root, "push", "origin", "main", "merged")
        tool.git(self.remote, "symbolic-ref", "HEAD", "refs/heads/main")
        tool.git(self.root, "switch", "-c", "unmerged")
        (self.root / "unique.txt").write_text("must survive\n")
        tool.git(self.root, "add", ".")
        tool.git(self.root, "commit", "-m", "unique source")
        tool.git(self.root, "push", "origin", "unmerged")
        tool.git(self.root, "switch", "main")
        self.out = self.home / "backup"

    def prepare(self):
        plan = tool.plan_retirement(self.root, self.out)
        return plan, tool.sha256(self.out / "plan.json")

    def test_only_merged_ref_is_deleted_and_source_is_unchanged(self):
        before = tool.remote_heads(self.root)
        plan, digest = self.prepare()
        self.assertFalse(plan["allHeadsRetainedByMain"])
        receipt = tool.apply_retirement(self.root, self.out, digest)
        self.assertEqual(receipt["branchesDeleted"], ["merged"])
        self.assertEqual(tool.remote_heads(self.root), {k: v for k, v in before.items() if k != "merged"})
        self.assertFalse(receipt["singleMainRefVerified"])
        self.assertEqual((self.root / "source.txt").read_text(), "base\n")

    def test_backup_restores_exact_merged_head(self):
        plan, digest = self.prepare()
        expected = next(row["sha"] for row in plan["branches"] if row["branch"] == "merged")
        tool.apply_retirement(self.root, self.out, digest)
        restored = self.home / "restored"
        restored.mkdir()
        tool.git(restored, "init")
        tool.git(restored, "fetch", str(self.out / "all-branches.bundle"),
                 "refs/remotes/origin/merged:refs/heads/recovered")
        self.assertEqual(tool.git(restored, "rev-parse", "recovered").stdout.strip(), expected)

    def test_tampered_plan_rejects_without_deletion(self):
        _, digest = self.prepare()
        before = tool.remote_heads(self.root)
        with (self.out / "plan.json").open("a") as stream:
            stream.write(" ")
        with self.assertRaises(tool.RefSafetyError):
            tool.apply_retirement(self.root, self.out, digest)
        self.assertEqual(tool.remote_heads(self.root), before)

    def test_tampered_backup_rejects_without_deletion(self):
        _, digest = self.prepare()
        before = tool.remote_heads(self.root)
        with (self.out / "all-branches.bundle").open("ab") as stream:
            stream.write(b"tamper")
        with self.assertRaises(tool.RefSafetyError):
            tool.apply_retirement(self.root, self.out, digest)
        self.assertEqual(tool.remote_heads(self.root), before)

    def test_new_branch_commit_is_not_deleted(self):
        _, digest = self.prepare()
        tool.git(self.root, "switch", "merged")
        (self.root / "new.txt").write_text("concurrent change\n")
        tool.git(self.root, "add", ".")
        tool.git(self.root, "commit", "-m", "concurrent change")
        tool.git(self.root, "push", "origin", "merged")
        before = tool.remote_heads(self.root)
        receipt = tool.apply_retirement(self.root, self.out, digest)
        self.assertEqual(receipt["branchesDeleted"], [])
        self.assertEqual(tool.remote_heads(self.root), before)

    def test_advanced_main_preserves_ancestry_and_all_new_content(self):
        _, digest = self.prepare()
        (self.root / "later.txt").write_text("later main\n")
        tool.git(self.root, "add", ".")
        tool.git(self.root, "commit", "-m", "advance main")
        tool.git(self.root, "push", "origin", "main")
        current_main = tool.remote_heads(self.root)["main"]
        receipt = tool.apply_retirement(self.root, self.out, digest)
        self.assertEqual(receipt["branchesDeleted"], ["merged"])
        self.assertEqual(tool.remote_heads(self.root)["main"], current_main)

    def test_replaced_main_aborts(self):
        _, digest = self.prepare()
        tool.git(self.root, "switch", "--orphan", "replacement")
        (self.root / "replacement.txt").write_text("unrelated\n")
        tool.git(self.root, "add", ".")
        tool.git(self.root, "commit", "-m", "replacement")
        tool.git(self.root, "push", "origin", "+HEAD:refs/heads/main")
        before = tool.remote_heads(self.root)
        with self.assertRaises(tool.RefSafetyError):
            tool.apply_retirement(self.root, self.out, digest)
        self.assertEqual(tool.remote_heads(self.root), before)

    def test_live_default_is_never_deleted(self):
        _, digest = self.prepare()
        tool.git(self.remote, "symbolic-ref", "HEAD", "refs/heads/merged")
        before = tool.remote_heads(self.root)
        receipt = tool.apply_retirement(self.root, self.out, digest)
        self.assertEqual(receipt["branchesDeleted"], [])
        self.assertEqual(tool.remote_heads(self.root), before)

    def test_changed_remote_url_aborts(self):
        _, digest = self.prepare()
        tool.git(self.root, "remote", "set-url", "origin", str(self.home / "other.git"))
        with self.assertRaises(tool.RefSafetyError):
            tool.apply_retirement(self.root, self.out, digest)

    def test_server_rejection_preserves_entire_atomic_batch(self):
        tool.git(self.root, "branch", "protected")
        tool.git(self.root, "push", "origin", "protected")
        _, digest = self.prepare()
        before = tool.remote_heads(self.root)
        hook = self.remote / "hooks" / "pre-receive"
        hook.write_text("#!/bin/sh\nwhile read old new ref; do\n"
                        "  if [ \"$ref\" = refs/heads/protected ]; then exit 1; fi\n"
                        "done\n")
        hook.chmod(0o755)
        with self.assertRaises(tool.RefSafetyError):
            tool.apply_retirement(self.root, self.out, digest)
        self.assertEqual(tool.remote_heads(self.root), before)
        receipt = json.loads((self.out / "receipt.json").read_text())
        self.assertEqual(receipt["branchesDeleted"], [])

    def test_late_race_is_rejected_by_explicit_lease(self):
        _, digest = self.prepare()
        original_git = tool.git
        raced = False

        def racing_git(root, *args, **kwargs):
            nonlocal raced
            if args and args[0] == "push" and "--atomic" in args and not raced:
                raced = True
                original_git(self.remote, "update-ref", "refs/heads/merged",
                             original_git(self.remote, "rev-parse", "refs/heads/unmerged").stdout.strip())
            return original_git(root, *args, **kwargs)

        from unittest.mock import patch
        with patch.object(tool, "git", racing_git):
            with self.assertRaises(tool.RefSafetyError):
                tool.apply_retirement(self.root, self.out, digest)
        self.assertIn("merged", tool.remote_heads(self.root))
        receipt = json.loads((self.out / "receipt.json").read_text())
        self.assertEqual(receipt["branchesDeleted"], [])

    def test_branch_created_after_plan_is_not_touched(self):
        _, digest = self.prepare()
        tool.git(self.root, "branch", "brand-new")
        tool.git(self.root, "push", "origin", "brand-new")
        tool.apply_retirement(self.root, self.out, digest)
        self.assertIn("brand-new", tool.remote_heads(self.root))


if __name__ == "__main__":
    unittest.main()
