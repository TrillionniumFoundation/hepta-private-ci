import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts.hepta_ci_candidate import candidate_plan


class CandidatePlanTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.cwd = Path.cwd()
        os.chdir(self.root)
        self.addCleanup(os.chdir, self.cwd)
        self.git("init", "-q")
        self.git("config", "user.name", "Candidate Test")
        self.git("config", "user.email", "candidate@localhost")
        (self.root / "source").write_text("base")
        self.git("add", ".")
        self.git("commit", "-qm", "base")
        self.base = self.git("rev-parse", "HEAD")
        (self.root / "source").write_text("candidate")
        self.git("commit", "-qam", "candidate")
        self.source = self.git("rev-parse", "HEAD")

    def git(self, *args):
        return subprocess.check_output(["git", *args], stderr=subprocess.PIPE, text=True).strip()

    def merge(self, *, changed=False, reverse_parents=False):
        if changed:
            self.git("checkout", "--detach", self.base)
            (self.root / "base-only").write_text("combined tree")
            self.git("add", ".")
            self.git("commit", "-qm", "independent main change")
            self.base = self.git("rev-parse", "HEAD")
            self.git("checkout", "--detach", self.source)
        tree = self.git("merge-tree", "--write-tree", self.base, self.source)
        parents = [self.base, self.source]
        if reverse_parents:
            parents.reverse()
        merge = self.git("commit-tree", tree, "-p", parents[0], "-p", parents[1], "-m", "merge")
        self.git("reset", "--hard", merge)
        return merge

    def test_source_always_executes_native_checks(self):
        plan = candidate_plan(source=self.source, tested=self.source, lane="source-head")
        self.assertTrue(plan["native_execution_required"])
        self.assertFalse(plan["requires_source_head_success"])

    def test_identical_merge_requires_its_own_real_native_execution(self):
        merge = self.merge()
        plan = candidate_plan(source=self.source, tested=merge, base=self.base, lane="base-merge")
        self.assertTrue(plan["native_execution_required"])
        self.assertFalse(plan["requires_source_head_success"])
        self.assertTrue(plan["source_tree_identical"])
        self.assertEqual(plan["source_tree"], plan["tested_tree"])
        self.assertNotEqual(plan["source_sha"], plan["tested_sha"])

    def test_synthetic_merge_alias_has_same_exact_tree_semantics(self):
        merge = self.merge()
        plan = candidate_plan(
            source=self.source,
            tested=merge,
            base=self.base,
            lane="synthetic-merge",
        )
        self.assertTrue(plan["native_execution_required"])
        self.assertFalse(plan["requires_source_head_success"])
        self.assertTrue(plan["source_tree_identical"])
        self.assertEqual(plan["source_tree"], plan["tested_tree"])

    def test_different_merge_tree_requires_real_tests_not_only_compile(self):
        merge = self.merge(changed=True)
        plan = candidate_plan(source=self.source, tested=merge, base=self.base, lane="base-merge")
        self.assertTrue(plan["native_execution_required"])
        self.assertFalse(plan["requires_source_head_success"])

    def test_wrong_checkout_cannot_reuse_a_receipt(self):
        self.merge()
        with self.assertRaisesRegex(ValueError, "checked-out"):
            candidate_plan(source=self.source, tested=self.source, lane="source-head")

    def test_parent_order_is_part_of_exact_merge_identity(self):
        merge = self.merge(reverse_parents=True)
        with self.assertRaisesRegex(ValueError, "parents"):
            candidate_plan(source=self.source, tested=merge, base=self.base, lane="base-merge")

    def test_source_lane_cannot_test_a_different_commit(self):
        merge = self.merge()
        with self.assertRaisesRegex(ValueError, "exact source"):
            candidate_plan(source=self.source, tested=merge, lane="source-head")

    def test_forged_source_tree_cannot_hide_base_changes(self):
        self.merge(changed=True)
        source_tree = self.git("rev-parse", f"{self.source}^{{tree}}")
        forged = self.git(
            "commit-tree", source_tree, "-p", self.base, "-p", self.source, "-m", "forged merge"
        )
        self.git("reset", "--hard", forged)
        with self.assertRaisesRegex(ValueError, "recomputed"):
            candidate_plan(source=self.source, tested=forged, base=self.base, lane="base-merge")

    def test_injected_merge_content_is_not_a_prospective_merge(self):
        (self.root / "extra-source.py").write_text("print('not from either parent')")
        self.git("add", ".")
        tree = self.git("write-tree")
        forged = self.git("commit-tree", tree, "-p", self.base, "-p", self.source, "-m", "extra")
        self.git("reset", "--hard", forged)
        with self.assertRaisesRegex(ValueError, "recomputed"):
            candidate_plan(source=self.source, tested=forged, base=self.base, lane="synthetic-merge")

    def test_manually_resolved_conflicting_merge_is_not_automatic_qualification(self):
        self.git("checkout", "--detach", self.base)
        (self.root / "source").write_text("conflicting main change")
        self.git("commit", "-qam", "conflict on main")
        self.base = self.git("rev-parse", "HEAD")
        tree = self.git("rev-parse", f"{self.source}^{{tree}}")
        forged = self.git("commit-tree", tree, "-p", self.base, "-p", self.source, "-m", "resolved")
        self.git("reset", "--hard", forged)
        with self.assertRaisesRegex(ValueError, "clean prospective merge"):
            candidate_plan(source=self.source, tested=forged, base=self.base, lane="base-merge")

    def test_unstaged_source_changes_are_rejected(self):
        (self.root / "source").write_text("changed after checkout")
        with self.assertRaisesRegex(ValueError, "clean"):
            candidate_plan(source=self.source, tested=self.source, lane="source-head")

    def test_staged_source_changes_are_rejected(self):
        (self.root / "source").write_text("staged after checkout")
        self.git("add", ".")
        with self.assertRaisesRegex(ValueError, "clean"):
            candidate_plan(source=self.source, tested=self.source, lane="source-head")

    def test_untracked_source_changes_are_rejected(self):
        (self.root / "injected.py").write_text("print('outside source tree')")
        with self.assertRaisesRegex(ValueError, "clean"):
            candidate_plan(source=self.source, tested=self.source, lane="source-head")

    def test_ignored_build_outputs_do_not_make_the_plan_a_hermetic_receipt(self):
        (self.root / ".gitignore").write_text("build-output/\n")
        self.git("add", ".")
        self.git("commit", "-qm", "declare output directory")
        self.source = self.git("rev-parse", "HEAD")
        (self.root / "build-output").mkdir()
        (self.root / "build-output/log.txt").write_text("not a source file")
        plan = candidate_plan(source=self.source, tested=self.source, lane="source-head")
        self.assertTrue(plan["native_execution_required"])
        self.assertNotIn("qualified", plan)

    def test_same_tree_merge_also_requires_a_clean_worktree(self):
        merge = self.merge()
        (self.root / "source").write_text("mutation before execution")
        with self.assertRaisesRegex(ValueError, "clean"):
            candidate_plan(source=self.source, tested=merge, base=self.base, lane="base-merge")

    def test_optional_source_base_must_be_exact_when_supplied(self):
        with patch("scripts.hepta_ci_candidate.git") as git:
            with self.assertRaises(ValueError):
                candidate_plan(source=self.source, tested=self.source, base="main", lane="source-head")
            git.assert_not_called()

    def test_optional_source_base_cannot_be_a_tree_object(self):
        tree = self.git("rev-parse", f"{self.base}^{{tree}}")
        with self.assertRaisesRegex(ValueError, "commit object"):
            candidate_plan(source=self.source, tested=self.source, base=tree, lane="source-head")

    def test_invalid_identity_and_unknown_lane_fail_before_git(self):
        for overrides in [{"source": "HEAD"}, {"lane": "unknown"}, {"lane": "base-merge"}]:
            args = {"source": self.source, "tested": self.source, "lane": "source-head", **overrides}
            with self.subTest(overrides=overrides), patch("scripts.hepta_ci_candidate.git") as git:
                with self.assertRaises(ValueError):
                    candidate_plan(**args)
                git.assert_not_called()


if __name__ == "__main__":
    unittest.main()
