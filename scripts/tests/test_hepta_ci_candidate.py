import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts.hepta_ci_candidate import candidate_plan

CANDIDATE_SCRIPT = Path(__file__).resolve().parents[1] / "hepta_ci_candidate.py"


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

    def merge(self, *, changed=False, reverse_parents=False, forged_tree=False):
        if changed:
            self.git("checkout", "-q", "--detach", self.base)
            (self.root / "base-only").write_text("combined tree")
            self.git("add", ".")
            self.git("commit", "-qm", "base advanced independently")
            self.base = self.git("rev-parse", "HEAD")
        tree = self.git("merge-tree", "--write-tree", self.base, self.source)
        if forged_tree:
            tree = self.git("rev-parse", f"{self.base}^{{tree}}")
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

    def test_source_only_dispatch_allows_absent_base_without_claiming_merge(self):
        plan = candidate_plan(
            source=self.source, tested=self.source, lane="source-head", base=""
        )
        self.assertIsNone(plan["base_sha"])
        self.assertTrue(plan["native_execution_required"])

    def test_source_lane_cannot_bind_a_tree_object_as_its_base(self):
        with self.assertRaisesRegex(ValueError, "not a commit object"):
            candidate_plan(
                source=self.source,
                tested=self.source,
                lane="source-head",
                base=self.git("rev-parse", "HEAD^{tree}"),
            )

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

    def test_matching_parents_cannot_certify_a_different_merge_tree(self):
        merge = self.merge(forged_tree=True)
        with self.assertRaisesRegex(ValueError, "canonical merge"):
            candidate_plan(
                source=self.source, tested=merge, base=self.base, lane="base-merge"
            )

    def test_local_graft_cannot_replace_the_canonical_merge_ancestry(self):
        self.merge(changed=True)
        source_tree = self.git("rev-parse", f"{self.source}^{{tree}}")
        merge = self.git(
            "commit-tree",
            source_tree,
            "-p",
            self.base,
            "-p",
            self.source,
            "-m",
            "forged source-only merge",
        )
        self.git("reset", "--hard", merge)
        graft = self.root / ".git/info/grafts"
        graft.write_text(f"{self.source} {self.base}\n")
        # Legacy grafts still affect merge-tree with replacement refs disabled.
        # The existing metadata reader must suppress both graph overrides.
        with self.assertRaisesRegex(ValueError, "canonical merge"):
            candidate_plan(
                source=self.source, tested=merge, base=self.base, lane="base-merge"
            )

    def test_unresolved_canonical_merge_cannot_certify_a_manual_tree(self):
        self.git("checkout", "-q", "--detach", self.base)
        (self.root / "source").write_text("conflicting base edit")
        self.git("commit", "-qam", "conflicting base")
        self.base = self.git("rev-parse", "HEAD")
        merge = self.git(
            "commit-tree",
            self.git("rev-parse", f"{self.source}^{{tree}}"),
            "-p",
            self.base,
            "-p",
            self.source,
            "-m",
            "unverified resolution",
        )
        self.git("reset", "--hard", merge)
        with self.assertRaises(subprocess.CalledProcessError):
            candidate_plan(
                source=self.source, tested=merge, base=self.base, lane="base-merge"
            )

    def test_dirty_hidden_and_untracked_sources_fail_without_modifying_index(self):
        for flag, undo in (
            ("--assume-unchanged", "--no-assume-unchanged"),
            ("--skip-worktree", "--no-skip-worktree"),
        ):
            with self.subTest(flag=flag):
                self.git("update-index", flag, "source")
                (self.root / "source").write_text("hidden change")
                index = (self.root / ".git/index").read_bytes()
                with self.assertRaisesRegex(ValueError, "dirty"):
                    candidate_plan(
                        source=self.source, tested=self.source, lane="source-head"
                    )
                self.assertEqual((self.root / ".git/index").read_bytes(), index)
                self.git("update-index", undo, "source")
                self.git("checkout", "--", "source")
        (self.root / "untracked").write_text("unreviewed input")
        with self.assertRaisesRegex(ValueError, "dirty"):
            candidate_plan(source=self.source, tested=self.source, lane="source-head")

    def pair_clone(self):
        # A sibling checkout keeps the primary source clean.
        pair = self.root.parent / (self.root.name + "-pair")
        self.git("clone", "-q", "--no-local", str(self.root), str(pair))
        self.addCleanup(shutil.rmtree, pair)
        return pair

    def test_explicit_repository_ignores_ambient_git_selectors(self):
        pair = self.pair_clone()
        (self.root / "source").write_text("dirty primary")
        with patch.dict(
            os.environ,
            {"GIT_DIR": str(self.root / ".git"), "GIT_WORK_TREE": str(self.root)},
        ):
            plan = candidate_plan(
                source=self.source,
                tested=self.source,
                lane="source-head",
                repository=pair,
            )
        self.assertEqual(plan["tested_sha"], self.source)

    def test_pair_cli_binds_both_actual_checkouts_and_rejects_stale_pair(self):
        pair = self.pair_clone()
        command = [
            sys.executable,
            str(CANDIDATE_SCRIPT),
            "--source",
            self.source,
            "--tested",
            self.source,
            "--base",
            self.base,
            "--lane",
            "source-head",
            "--pair-repository",
            str(pair),
            "--pair-source",
            self.source,
            "--pair-tested",
            self.source,
            "--pair-base",
            self.base,
        ]
        result = subprocess.run(command, text=True, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        plan = json.loads(result.stdout)
        self.assertEqual(plan.pop("paired_candidate"), plan)
        self.git("-C", str(pair), "reset", "--hard", self.base)
        result = subprocess.run(command, text=True, capture_output=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("checked-out commit differs", result.stderr)
        self.assertEqual(result.stdout, "")

    def test_pair_cli_rejects_partial_tuple_without_emitting_plan(self):
        result = subprocess.run(
            [
                sys.executable,
                str(CANDIDATE_SCRIPT),
                "--source",
                self.source,
                "--tested",
                self.source,
                "--lane",
                "source-head",
                "--pair-source",
                self.source,
            ],
            text=True,
            capture_output=True,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("paired checkout requires", result.stderr)
        self.assertEqual(result.stdout, "")

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
