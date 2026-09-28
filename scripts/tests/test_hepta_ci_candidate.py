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
        return subprocess.check_output(
            ["git", *args], stderr=subprocess.PIPE, text=True
        ).strip()

    def merge(self, *, changed=False, reverse_parents=False):
        if changed:
            self.git("checkout", "--detach", self.base)
            (self.root / "base-only").write_text("combined tree")
            self.git("add", ".")
            self.git("commit", "-qm", "new base")
            self.base = self.git("rev-parse", "HEAD")
            self.git("checkout", "--detach", self.source)
        tree = self.git("merge-tree", "--write-tree", self.base, self.source)
        parents = [self.base, self.source]
        if reverse_parents:
            parents.reverse()
        merge = self.git(
            "commit-tree", tree, "-p", parents[0], "-p", parents[1], "-m", "merge"
        )
        self.git("reset", "--hard", merge)
        return merge

    def test_source_always_executes_native_checks(self):
        plan = candidate_plan(
            source=self.source, tested=self.source, lane="source-head"
        )
        self.assertTrue(plan["native_execution_required"])
        self.assertFalse(plan["requires_source_head_success"])

    def test_identical_merge_reuses_tree_only_with_required_source_success(self):
        merge = self.merge()
        plan = candidate_plan(
            source=self.source, tested=merge, base=self.base, lane="base-merge"
        )
        self.assertFalse(plan["native_execution_required"])
        self.assertTrue(plan["requires_source_head_success"])
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
        self.assertFalse(plan["native_execution_required"])
        self.assertTrue(plan["requires_source_head_success"])
        self.assertEqual(plan["source_tree"], plan["tested_tree"])

    def test_different_merge_tree_requires_real_tests_not_only_compile(self):
        merge = self.merge(changed=True)
        plan = candidate_plan(
            source=self.source, tested=merge, base=self.base, lane="base-merge"
        )
        self.assertTrue(plan["native_execution_required"])
        self.assertFalse(plan["requires_source_head_success"])

    def test_source_tree_with_correct_parents_cannot_hide_base_changes(self):
        self.merge(changed=True)
        source_tree = self.git("rev-parse", f"{self.source}^{{tree}}")
        forged = self.git(
            "commit-tree",
            source_tree,
            "-p",
            self.base,
            "-p",
            self.source,
            "-m",
            "incorrect source-only merge",
        )
        self.git("reset", "--hard", forged)
        with self.assertRaisesRegex(ValueError, "merge tree"):
            candidate_plan(
                source=self.source, tested=forged, base=self.base, lane="base-merge"
            )

    def test_dirty_inputs_never_authorize_tree_reuse(self):
        merge = self.merge()
        for change in ("modified", "staged", "untracked"):
            with self.subTest(change=change):
                path = self.root / (
                    "extra-input" if change == "untracked" else "source"
                )
                path.write_text("not the tested tree")
                if change == "staged":
                    self.git("add", "source")
                with self.assertRaisesRegex(ValueError, "clean"):
                    candidate_plan(
                        source=self.source,
                        tested=merge,
                        base=self.base,
                        lane="base-merge",
                    )
                self.git("reset", "--hard", merge)
                if change == "untracked":
                    path.unlink()

    def test_conflicting_base_cannot_reuse_fabricated_merge(self):
        self.git("checkout", "--detach", self.base)
        (self.root / "source").write_text("conflicting base change")
        self.git("commit", "-qam", "conflict")
        self.base = self.git("rev-parse", "HEAD")
        source_tree = self.git("rev-parse", f"{self.source}^{{tree}}")
        forged = self.git(
            "commit-tree",
            source_tree,
            "-p",
            self.base,
            "-p",
            self.source,
            "-m",
            "unresolved merge",
        )
        self.git("reset", "--hard", forged)
        with self.assertRaisesRegex(ValueError, "merge"):
            candidate_plan(
                source=self.source, tested=forged, base=self.base, lane="base-merge"
            )

    def test_wrong_checkout_cannot_reuse_a_receipt(self):
        self.merge()
        with self.assertRaisesRegex(ValueError, "checked-out"):
            candidate_plan(source=self.source, tested=self.source, lane="source-head")

    def test_parent_order_is_part_of_exact_merge_identity(self):
        merge = self.merge(reverse_parents=True)
        with self.assertRaisesRegex(ValueError, "parents"):
            candidate_plan(
                source=self.source, tested=merge, base=self.base, lane="base-merge"
            )

    def test_source_lane_cannot_test_a_different_commit(self):
        merge = self.merge()
        with self.assertRaisesRegex(ValueError, "exact source"):
            candidate_plan(source=self.source, tested=merge, lane="source-head")

    def test_invalid_identity_and_unknown_lane_fail_before_git(self):
        for overrides in [
            {"source": "HEAD"},
            {"lane": "unknown"},
            {"lane": "base-merge"},
        ]:
            args = {
                "source": self.source,
                "tested": self.source,
                "lane": "source-head",
                **overrides,
            }
            with (
                self.subTest(overrides=overrides),
                patch("scripts.hepta_ci_candidate.git") as git,
            ):
                with self.assertRaises(ValueError):
                    candidate_plan(**args)
                git.assert_not_called()


if __name__ == "__main__":
    unittest.main()
