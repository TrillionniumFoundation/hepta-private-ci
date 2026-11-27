"""Real local Git remotes exercise backup, ancestry, races and atomic deletion."""

from pathlib import Path
import json
import subprocess
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
        self.protection = {
            "schema": tool.PROTECTION_SCHEMA,
            "repository": tool.REPOSITORY,
            "hiaRootCommits": [],
            "historicalProtectedCommits": [],
            "protectedHeads": {},
            "protectedBaseHeads": {},
        }

    def prepare(self):
        plan = tool.plan_retirement(self.root, self.out, self.protection)
        return plan, tool.sha256(self.out / "plan.json")

    def test_only_merged_ref_is_deleted_and_source_is_unchanged(self):
        before = tool.remote_heads(self.root)
        plan, digest = self.prepare()
        self.assertFalse(plan["allHeadsRetainedByMain"])
        receipt = tool.apply_retirement(self.root, self.out, digest)
        self.assertEqual(receipt["branchesDeleted"], ["merged"])
        self.assertEqual(
            tool.remote_heads(self.root),
            {k: v for k, v in before.items() if k != "merged"},
        )
        self.assertFalse(receipt["singleMainRefVerified"])
        self.assertEqual((self.root / "source.txt").read_text(), "base\n")

    def test_backup_restores_exact_merged_head(self):
        plan, digest = self.prepare()
        expected = next(
            row["sha"] for row in plan["branches"] if row["branch"] == "merged"
        )
        tool.apply_retirement(self.root, self.out, digest)
        restored = self.home / "restored"
        restored.mkdir()
        tool.git(restored, "init")
        tool.git(
            restored,
            "fetch",
            str(self.out / "all-branches.bundle"),
            "refs/remotes/origin/merged:refs/heads/recovered",
        )
        self.assertEqual(
            tool.git(restored, "rev-parse", "recovered").stdout.strip(), expected
        )

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
        hook.write_text(
            "#!/bin/sh\nwhile read old new ref; do\n"
            '  if [ "$ref" = refs/heads/protected ]; then exit 1; fi\n'
            "done\n"
        )
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
                original_git(
                    self.remote,
                    "update-ref",
                    "refs/heads/merged",
                    original_git(
                        self.remote, "rev-parse", "refs/heads/unmerged"
                    ).stdout.strip(),
                )
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

    def test_inventory_enumerates_more_than_one_thousand_branches(self):
        heads = tool.remote_heads(self.root)
        added = {f"reviewed/{number:04d}": heads["main"] for number in range(1001)}
        subprocess.run(
            ["git", "-C", str(self.remote), "update-ref", "--stdin"],
            input="".join(
                f"create refs/heads/{name} {sha}\n" for name, sha in added.items()
            ),
            text=True,
            capture_output=True,
            check=True,
            timeout=30,
        )
        self.assertEqual(tool.remote_heads(self.root), heads | added)

    def test_protected_name_survives_even_when_manifest_observation_is_old(self):
        name = "codex/hia-native-fixture"
        heads = tool.remote_heads(self.root)
        self.protection["protectedHeads"][name] = heads["main"]
        tool.git(self.root, "merge", "--ff-only", "unmerged")
        tool.git(self.root, "branch", name)
        tool.git(self.root, "push", "origin", "main", name)
        plan, digest = self.prepare()
        row = next(row for row in plan["branches"] if row["branch"] == name)
        self.assertTrue(row["ancestorOfMain"])
        self.assertEqual(row["disposition"], "keep_protected")
        receipt = tool.apply_retirement(self.root, self.out, digest)
        self.assertEqual(receipt["branchesDeleted"], [])
        self.assertEqual(
            tool.remote_heads(self.root),
            {
                "main": heads["unmerged"],
                "merged": heads["merged"],
                "unmerged": heads["unmerged"],
                name: heads["unmerged"],
            },
        )
        self.assertTrue(receipt["singleRustMainRefVerified"])
        self.assertFalse(receipt["singleMainRefVerified"])

    def test_new_hia_name_is_retained_without_a_manifest_entry(self):
        name = "feature/New_HIA-rewrite"
        tool.git(self.root, "branch", name)
        tool.git(self.root, "push", "origin", name)
        before = tool.remote_heads(self.root)
        plan, _ = self.prepare()
        row = next(row for row in plan["branches"] if row["branch"] == name)
        self.assertTrue(row["ancestorOfMain"])
        self.assertEqual(row["disposition"], "keep_protected")
        self.assertEqual(row["protectionReasons"], ["hia_branch_name"])

        # A stale disposition cannot override the live name protection at apply.
        row["disposition"] = "eligible_merged"
        (self.out / "plan.json").write_text(json.dumps(plan))
        receipt = tool.apply_retirement(
            self.root, self.out, tool.sha256(self.out / "plan.json")
        )
        self.assertEqual(receipt["branchesDeleted"], [])
        self.assertEqual(tool.remote_heads(self.root), before)

    def test_hidden_hia_descendant_is_retained_even_after_merge_to_main(self):
        self.protection["hiaRootCommits"] = [tool.remote_heads(self.root)["unmerged"]]
        name = "codex/sdk-resolver-fixture"
        tool.git(self.root, "switch", "-c", name, "unmerged")
        (self.root / "sdk.txt").write_text("HIA-derived integration\n")
        tool.git(self.root, "add", ".")
        tool.git(self.root, "commit", "-m", "sdk descendant")
        tool.git(self.root, "switch", "main")
        tool.git(self.root, "merge", "--ff-only", name)
        tool.git(self.root, "push", "origin", "main", name)
        before = tool.remote_heads(self.root)
        plan, digest = self.prepare()
        row = next(row for row in plan["branches"] if row["branch"] == name)
        self.assertEqual(row["disposition"], "keep_protected")
        self.assertEqual(
            row["protectionReasons"], [f"hia_ancestor:{before['unmerged']}"]
        )
        receipt = tool.apply_retirement(self.root, self.out, digest)
        self.assertEqual(receipt["branchesDeleted"], ["merged"])
        self.assertEqual(
            tool.remote_heads(self.root),
            {key: sha for key, sha in before.items() if key != "merged"},
        )

    def test_protected_pr_base_is_retained_despite_eligible_row(self):
        self.protection["protectedBaseHeads"]["merged"] = tool.remote_heads(self.root)[
            "merged"
        ]
        plan, _ = self.prepare()
        row = next(row for row in plan["branches"] if row["branch"] == "merged")
        self.assertEqual(row["protectionReasons"], ["protected_pr_base"])
        # Even an approved plan with a mistaken disposition cannot override the frozen protection.
        row["disposition"] = "eligible_merged"
        (self.out / "plan.json").write_text(json.dumps(plan))
        before = tool.remote_heads(self.root)
        receipt = tool.apply_retirement(
            self.root, self.out, tool.sha256(self.out / "plan.json")
        )
        self.assertEqual(receipt["branchesDeleted"], [])
        self.assertEqual(tool.remote_heads(self.root), before)

    def test_missing_hia_ancestry_object_refuses_inventory(self):
        self.protection["hiaRootCommits"] = ["1" * 40]
        before = tool.remote_heads(self.root)
        with self.assertRaises(tool.RefSafetyError):
            self.prepare()
        self.assertEqual(tool.remote_heads(self.root), before)


    def test_new_hia_tip_protects_unnamed_aliases_and_descendants(self):
        hia_name = "feature/hia-independent"
        hidden_name = "ordinary/hidden-descendant"
        tool.git(self.root, "branch", hia_name, "unmerged")
        tool.git(self.root, "switch", "-c", hidden_name, "unmerged")
        (self.root / "later.txt").write_text("protected descendant\n")
        tool.git(self.root, "add", ".")
        tool.git(self.root, "commit", "-m", "descendant")
        tool.git(self.root, "switch", "main")
        tool.git(self.root, "merge", "--ff-only", hidden_name)
        tool.git(self.root, "push", "origin", "main", hia_name, hidden_name)
        before = tool.remote_heads(self.root)
        plan, digest = self.prepare()
        rows = {row["branch"]: row for row in plan["branches"]}
        for name in (hia_name, "unmerged", hidden_name):
            self.assertEqual(rows[name]["disposition"], "keep_protected")
        receipt = tool.apply_retirement(self.root, self.out, digest)
        self.assertEqual(receipt["branchesDeleted"], ["merged"])
        self.assertEqual(
            tool.remote_heads(self.root),
            {name: sha for name, sha in before.items() if name != "merged"},
        )

    def test_new_hia_name_at_apply_protects_existing_merged_alias(self):
        _, digest = self.prepare()
        name = "feature/hia-created-after-plan"
        tool.git(self.root, "branch", name, "merged")
        tool.git(self.root, "push", "origin", name)
        before = tool.remote_heads(self.root)
        receipt = tool.apply_retirement(self.root, self.out, digest)
        self.assertEqual(receipt["branchesDeleted"], [])
        self.assertEqual(tool.remote_heads(self.root), before)

    def test_recorded_named_pin_survives_unrelated_name_replacement(self):
        name = "feature/hia-replaced"
        historical = tool.remote_heads(self.root)["unmerged"]
        self.protection["protectedHeads"][name] = historical
        tool.git(self.root, "switch", "--orphan", "replacement-local")
        (self.root / "replacement.txt").write_text("independent replacement\n")
        tool.git(self.root, "add", ".")
        tool.git(self.root, "commit", "-m", "independent replacement")
        tool.git(self.root, "push", "origin", f"HEAD:refs/heads/{name}")
        tool.git(self.root, "switch", "main")
        tool.git(self.root, "merge", "--ff-only", "unmerged")
        tool.git(self.root, "push", "origin", "main")
        before = tool.remote_heads(self.root)
        plan, digest = self.prepare()
        row = next(row for row in plan["branches"] if row["branch"] == "unmerged")
        self.assertEqual(row["disposition"], "keep_protected")
        self.assertIn(historical, plan["protectionManifest"]["historicalProtectedCommits"])
        receipt = tool.apply_retirement(self.root, self.out, digest)
        self.assertEqual(receipt["branchesDeleted"], ["merged"])
        self.assertEqual(
            tool.remote_heads(self.root),
            {branch: sha for branch, sha in before.items() if branch != "merged"},
        )

    def test_historical_pin_list_protects_unnamed_alias(self):
        self.protection["historicalProtectedCommits"] = [
            tool.remote_heads(self.root)["unmerged"]
        ]
        tool.git(self.root, "merge", "--ff-only", "unmerged")
        tool.git(self.root, "push", "origin", "main")
        before = tool.remote_heads(self.root)
        plan, digest = self.prepare()
        row = next(row for row in plan["branches"] if row["branch"] == "unmerged")
        self.assertEqual(row["disposition"], "keep_protected")
        receipt = tool.apply_retirement(self.root, self.out, digest)
        self.assertEqual(receipt["branchesDeleted"], ["merged"])
        self.assertEqual(
            tool.remote_heads(self.root),
            {name: sha for name, sha in before.items() if name != "merged"},
        )

    def test_plan_retains_live_pin_after_protected_name_is_deleted(self):
        name = "feature/hia-temporary-name"
        historical = tool.remote_heads(self.root)["unmerged"]
        tool.git(self.root, "merge", "--ff-only", "unmerged")
        tool.git(self.root, "branch", name)
        tool.git(self.root, "push", "origin", "main", name)
        plan, _ = self.prepare()
        frozen = plan["protectionManifest"]
        self.assertIn(historical, frozen["historicalProtectedCommits"])
        self.assertEqual(frozen["protectedHeads"][name], historical)
        tool.git(self.root, "push", "origin", f":refs/heads/{name}")
        before = tool.remote_heads(self.root)
        self.assertIn("unmerged", tool.protected_branches(self.root, before, frozen))
        # Even a stale disposition cannot erase the retained historical pin.
        row = next(row for row in plan["branches"] if row["branch"] == "unmerged")
        row["disposition"] = "eligible_merged"
        (self.out / "plan.json").write_text(json.dumps(plan))
        receipt = tool.apply_retirement(
            self.root, self.out, tool.sha256(self.out / "plan.json")
        )
        self.assertEqual(receipt["branchesDeleted"], ["merged"])
        self.assertEqual(
            tool.remote_heads(self.root),
            {branch: sha for branch, sha in before.items() if branch != "merged"},
        )

    def test_missing_historical_pin_refuses_inventory(self):
        self.protection["historicalProtectedCommits"] = ["1" * 40]
        before = tool.remote_heads(self.root)
        with self.assertRaises(tool.RefSafetyError):
            self.prepare()
        self.assertEqual(tool.remote_heads(self.root), before)

    def test_missing_named_historical_pin_refuses_inventory(self):
        self.protection["protectedHeads"]["old/hia-name"] = "1" * 40
        before = tool.remote_heads(self.root)
        with self.assertRaises(tool.RefSafetyError):
            self.prepare()
        self.assertEqual(tool.remote_heads(self.root), before)

    def test_shallow_history_refuses_inventory(self):
        shallow = self.home / "shallow"
        tool.git(
            self.home,
            "clone",
            "--depth",
            "1",
            "--no-single-branch",
            self.remote.as_uri(),
            str(shallow),
        )
        before = tool.remote_heads(shallow)
        with self.assertRaises(tool.RefSafetyError):
            tool.plan_retirement(shallow, self.out, self.protection)
        self.assertEqual(tool.remote_heads(shallow), before)

    def test_grafted_history_refuses_inventory(self):
        before = tool.remote_heads(self.root)
        grafts = self.root / ".git" / "info" / "grafts"
        grafts.parent.mkdir(exist_ok=True)
        grafts.write_text(before["unmerged"] + "\n")
        with self.assertRaises(tool.RefSafetyError):
            self.prepare()
        self.assertEqual(tool.remote_heads(self.root), before)

    def test_replacement_objects_do_not_hide_descendant(self):
        historical = tool.remote_heads(self.root)["unmerged"]
        self.protection["historicalProtectedCommits"] = [historical]
        name = "ordinary/replaced-descendant"
        tool.git(self.root, "switch", "-c", name, "unmerged")
        (self.root / "later.txt").write_text("retained source\n")
        tool.git(self.root, "add", ".")
        tool.git(self.root, "commit", "-m", "descendant")
        descendant = tool.git(self.root, "rev-parse", "HEAD").stdout.strip()
        tool.git(self.root, "switch", "main")
        tool.git(self.root, "merge", "--ff-only", name)
        tool.git(self.root, "push", "origin", "main", name)
        tool.git(self.root, "replace", descendant, "merged")
        before = tool.remote_heads(self.root)
        plan, digest = self.prepare()
        row = next(row for row in plan["branches"] if row["branch"] == name)
        self.assertEqual(row["disposition"], "keep_protected")
        receipt = tool.apply_retirement(self.root, self.out, digest)
        self.assertEqual(receipt["branchesDeleted"], ["merged"])
        self.assertEqual(
            tool.remote_heads(self.root),
            {branch: sha for branch, sha in before.items() if branch != "merged"},
        )

    def test_legacy_plan_is_refused_before_any_deletion(self):
        plan, _ = self.prepare()
        plan["schema"] = "hepta.branch-retirement.v2"
        (self.out / "plan.json").write_text(json.dumps(plan))
        before = tool.remote_heads(self.root)
        with self.assertRaises(tool.RefSafetyError):
            tool.apply_retirement(
                self.root, self.out, tool.sha256(self.out / "plan.json")
            )
        self.assertEqual(tool.remote_heads(self.root), before)


    def test_reapplying_plan_cannot_forget_hia_seen_only_during_apply(self):
        _, digest = self.prepare()
        name = "feature/hia-observed-at-apply"
        historical = tool.remote_heads(self.root)["merged"]
        tool.git(self.root, "branch", name, "merged")
        tool.git(self.root, "push", "origin", name)
        receipt = tool.apply_retirement(self.root, self.out, digest)
        self.assertEqual(receipt["branchesDeleted"], [])
        journal = json.loads((self.out / "attempt.json").read_text())
        self.assertEqual(journal["planSha256"], digest)
        self.assertEqual(receipt["protectionManifest"], journal["protectionManifest"])
        self.assertIn(
            historical, journal["protectionManifest"]["historicalProtectedCommits"]
        )
        tool.git(self.root, "push", "origin", f":refs/heads/{name}")
        before = tool.remote_heads(self.root)
        with self.assertRaises(tool.RefSafetyError):
            tool.apply_retirement(self.root, self.out, digest)
        self.assertEqual(tool.remote_heads(self.root), before)


    def test_partial_attempt_record_refuses_mutation_without_final_receipt(self):
        _, digest = self.prepare()
        (self.out / "attempt.json").write_text("{")
        before = tool.remote_heads(self.root)
        with self.assertRaises(tool.RefSafetyError):
            tool.apply_retirement(self.root, self.out, digest)
        self.assertEqual(tool.remote_heads(self.root), before)
        self.assertFalse((self.out / "receipt.json").exists())


if __name__ == "__main__":
    unittest.main()
