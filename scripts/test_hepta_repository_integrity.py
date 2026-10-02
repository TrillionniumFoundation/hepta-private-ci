"""Hostile workflow substitutions use isolated candidate directories."""

import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
import sys
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from scripts import hepta_workflow_integrity as workflow

SPEC = importlib.util.spec_from_file_location(
    "scripts.hepta_repository_integrity_policy",
    Path(__file__).with_name("hepta-repository-integrity.py"),
)
POLICY = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = POLICY
SPEC.loader.exec_module(POLICY)

LEAF = """name: leaf
on:
  workflow_call:
permissions:
  contents: read
jobs:
  native:
    runs-on: ubuntu-24.04
    steps:
      - uses: actions/checkout@reviewed
        with:
          persist-credentials: false
      - run: |
          echo checked
"""
CALLER = """name: caller
on:
  workflow_dispatch:
permissions:
  contents: read
jobs:
  native:
    uses: ./.github/workflows/leaf.yml
"""


class WorkflowIntegrityTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.directory = self.root / ".github/workflows"
        self.directory.mkdir(parents=True)
        self.leaf = self.directory / "leaf.yml"
        self.leaf.write_text(LEAF)
        self.caller = self.directory / "caller.yml"

    def rules(self, text=CALLER):
        with patch.object(POLICY, "ROOT", self.root):
            return {
                item.rule
                for item in POLICY.scan_path(".github/workflows/caller.yml", text)
            }

    def candidate_change(self, target, before, after):
        environment = {
            **workflow.git_environment(),
            "GIT_AUTHOR_NAME": "Fixture",
            "GIT_AUTHOR_EMAIL": "fixture@example.test",
            "GIT_COMMITTER_NAME": "Fixture",
            "GIT_COMMITTER_EMAIL": "fixture@example.test",
        }

        def git(*arguments):
            return (
                subprocess.check_output(
                    ["git", "-C", str(self.root), *arguments],
                    env=environment,
                    stderr=subprocess.DEVNULL,
                )
                .decode()
                .strip()
            )

        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(before)
        git("init", "--quiet")
        git("add", ".")
        git("commit", "--quiet", "-m", "Base fixture")
        base = git("rev-parse", "HEAD")
        target.write_text(after)
        git("add", ".")
        git("commit", "--quiet", "-m", "Candidate fixture")
        return base, git("rev-parse", "HEAD")

    def verify(self, base, candidate):
        captured = io.StringIO()
        with (
            patch.object(POLICY, "ROOT", self.root),
            contextlib.redirect_stdout(captured),
        ):
            result = POLICY.verify(base, candidate, None)
        return result, json.loads(captured.getvalue())

    def test_nested_current_candidate_calls_pass_and_callee_edits_are_seen(self):
        self.leaf.write_text(CALLER.replace("leaf.yml", "grandchild.yml"))
        (self.directory / "grandchild.yml").write_text(LEAF)
        self.leaf.write_text(
            self.leaf.read_text().replace("workflow_dispatch:", "workflow_call:")
        )
        self.assertEqual(self.rules(), set())
        (self.directory / "grandchild.yml").write_text(LEAF.replace("false", "true"))
        self.assertIn("missing-safe-workflow-token", self.rules())

    def test_external_reference_never_uses_false_token_as_proof(self):
        text = CALLER.replace(
            "./.github/workflows/leaf.yml", "owner/repo/.github/workflows/leaf.yml@main"
        )
        text += "# persist-credentials: false\n"
        self.assertIn("external-reusable-workflow", self.rules(text))

    def test_every_real_checkout_requires_its_own_literal_false(self):
        for replacement in (
            "# persist-credentials: false",
            "unrelated: false",
            "persist-credentials: ${{ false }}",
        ):
            with self.subTest(replacement=replacement):
                self.leaf.write_text(
                    LEAF.replace("persist-credentials: false", replacement)
                )
                self.assertIn("missing-safe-workflow-token", self.rules())
        self.leaf.write_text(LEAF + "      - uses: actions/checkout@another\n")
        self.assertIn("missing-safe-workflow-token", self.rules())

    def test_run_scalar_and_unrelated_environment_do_not_supply_policy(self):
        bad = LEAF.replace("          persist-credentials: false\n", "")
        bad = bad.replace("echo checked", "persist-credentials: false")
        bad = bad.replace("jobs:\n", "env:\n  persist-credentials: false\njobs:\n")
        self.leaf.write_text(bad)
        self.assertIn("missing-safe-workflow-token", self.rules())

    def test_actual_permissions_and_reusable_trigger_are_required(self):
        cases = (
            ("contents: read", "# contents: read"),
            ("contents: read", "contents: write"),
            ("permissions:\n  contents: read", "permissions: {contents: read}"),
            ("    runs-on:", "    permissions:\n      contents: write\n    runs-on:"),
            ("workflow_call:", "workflow_dispatch:"),
        )
        for old, new in cases:
            with self.subTest(new=new):
                self.leaf.write_text(LEAF.replace(old, new))
                self.assertTrue(self.rules())

    def test_permissions_allow_only_reviewed_literal_read_or_none_values(self):
        cases = (
            "issues: ${{ 'write' }}",
            "issues: '${{ inputs.permission }}'",
            "issues: invalid",
            "issues:\n    nested: read",
            "issues: |\n    read",
            "unknown-permission: read",
            "id-token: read",
        )
        for permission in cases:
            with self.subTest(scope="workflow", permission=permission):
                text = CALLER.replace(
                    "  contents: read\n", "  contents: read\n  " + permission + "\n"
                )
                self.assertIn("workflow-write-permission", self.rules(text))
            with self.subTest(scope="job", permission=permission):
                nested = permission.replace("\n", "\n    ")
                text = CALLER.replace(
                    "  native:\n", "  native:\n    permissions:\n      " + nested + "\n"
                )
                self.assertIn("workflow-write-permission", self.rules(text))
        safe = CALLER.replace(
            "  contents: read\n",
            "  contents: read\n  actions: read\n  id-token: none\n",
        )
        safe = safe.replace(
            "  native:\n",
            "  native:\n    permissions:\n      contents: read\n      issues: none\n",
        )
        self.assertEqual(self.rules(safe), set())

    def test_privileged_trigger_cannot_hide_in_scalar_flow_or_sequence_shapes(self):
        for trigger in (
            "on: pull_request_target",
            "on: 'pull_request_target'",
            "on: [pull_request_target]",
            "on: [push, pull_request_target]",
            "on:\n  - push\n  - pull_request_target",
            "on:\n  pull_request_target:\n    types:\n      - opened",
            "on: ${{ inputs.trigger }}",
        ):
            with self.subTest(trigger=trigger):
                # Keep literal read permission and a genuine safe checkout, so
                # rejection proves event policy rather than missing tokens.
                text = LEAF.replace("on:\n  workflow_call:", trigger)
                self.assertTrue(self.rules(text))
        for trigger in ("on: push", "on:\n  - push\n  - pull_request"):
            with self.subTest(trigger=trigger):
                self.assertEqual(
                    self.rules(LEAF.replace("on:\n  workflow_call:", trigger)), set()
                )

    def test_unchanged_callee_executable_policy_is_not_skipped(self):
        self.leaf.write_text(LEAF.replace("echo checked", "git push origin HEAD:main"))
        self.assertIn("branch-push", self.rules())

    def test_duplicate_keys_aliases_and_mixed_jobs_fail_closed(self):
        for text in (
            CALLER.replace("permissions:\n", "permissions: {}\npermissions:\n"),
            CALLER.replace("jobs:\n", "jobs: &jobs\n"),
            CALLER + "    steps:\n      - run: echo ignored\n",
            CALLER.replace("    uses:", "    runs-on: ubuntu-24.04\n    uses:"),
        ):
            with self.subTest(text=text):
                self.assertTrue(self.rules(text))

    def test_missing_path_escape_and_non_regular_callees_reject(self):
        for target in (
            "./.github/workflows/missing.yml",
            "./.github/workflows/../leaf.yml",
            "./other/leaf.yml",
        ):
            with self.subTest(target=target):
                self.assertTrue(
                    self.rules(CALLER.replace("./.github/workflows/leaf.yml", target))
                )
        self.leaf.unlink()
        self.leaf.mkdir()
        self.assertIn("invalid-local-reusable-workflow", self.rules())

    def test_leaf_and_parent_symlinks_reject(self):
        self.leaf.unlink()
        target = self.root / "outside.yml"
        target.write_text(LEAF)
        self.leaf.symlink_to(target)
        self.assertIn("invalid-local-reusable-workflow", self.rules())
        self.leaf.unlink()
        self.directory.rmdir()
        self.directory.symlink_to(self.root, target_is_directory=True)
        (self.root / "leaf.yml").write_text(LEAF)
        self.assertIn("invalid-local-reusable-workflow", self.rules())

    def test_fifo_and_oversized_callee_reject_before_reading(self):
        self.leaf.unlink()
        os.mkfifo(self.leaf)
        self.assertIn("invalid-local-reusable-workflow", self.rules())
        self.leaf.unlink()
        self.leaf.write_text("x" * (workflow.MAX_BYTES + 1))
        self.assertIn("invalid-local-reusable-workflow", self.rules())

    def test_hardlinked_callee_rejects(self):
        os.link(self.leaf, self.root / "alias.yml")
        self.assertIn("invalid-local-reusable-workflow", self.rules())

    def test_callee_hardlink_appearing_before_open_is_rejected(self):
        real_open = os.open
        hook_fired = False

        def link_before_open(path, *arguments, **keywords):
            nonlocal hook_fired
            if Path(path) == self.leaf:
                self.assertFalse(hook_fired)
                hook_fired = True
                os.link(self.leaf, self.root / "racing-alias.yml")
            return real_open(path, *arguments, **keywords)

        with patch.object(workflow.os, "open", side_effect=link_before_open):
            self.assertIn("invalid-local-reusable-workflow", self.rules())
        self.assertTrue(hook_fired)

    def test_immutable_candidate_rejects_drift_untracked_and_non_regular_mode(self):
        def git(*arguments, input=None):
            return (
                subprocess.check_output(
                    ["git", "-C", str(self.root), *arguments],
                    input=input,
                    env={
                        **workflow.git_environment(),
                        "GIT_AUTHOR_NAME": "Fixture",
                        "GIT_AUTHOR_EMAIL": "fixture@example.test",
                        "GIT_COMMITTER_NAME": "Fixture",
                        "GIT_COMMITTER_EMAIL": "fixture@example.test",
                    },
                    stderr=subprocess.DEVNULL,
                )
                .decode()
                .strip()
            )

        git("init", "--quiet")
        self.caller.write_text(CALLER)
        git("add", ".")
        tree = git("write-tree")
        candidate = git("commit-tree", tree, "-m", "Candidate fixture")
        original_blob = git("hash-object", str(self.leaf))
        self.assertEqual(
            workflow.workflow_violations(
                ".github/workflows/caller.yml", CALLER, self.root, candidate=candidate
            ),
            [],
        )
        for noncommit in (tree, original_blob):
            with self.subTest(candidate=noncommit):
                self.assertTrue(
                    workflow.workflow_violations(
                        ".github/workflows/caller.yml",
                        CALLER,
                        self.root,
                        candidate=noncommit,
                    )
                )
        self.caller.write_text(CALLER + "# caller drift\n")
        self.assertTrue(
            workflow.workflow_violations(
                ".github/workflows/caller.yml",
                self.caller.read_text(),
                self.root,
                candidate=candidate,
            )
        )
        self.caller.unlink()
        self.caller.symlink_to(self.leaf)
        self.assertTrue(
            workflow.workflow_violations(
                ".github/workflows/caller.yml", CALLER, self.root, candidate=candidate
            )
        )
        self.caller.unlink()
        self.caller.write_text("x" * (workflow.MAX_BYTES + 1))
        self.assertTrue(
            workflow.workflow_violations(
                ".github/workflows/caller.yml",
                self.caller.read_text(),
                self.root,
                candidate=candidate,
            )
        )
        self.caller.write_text(CALLER)
        self.leaf.write_text(LEAF + "# changed\n")
        violations = workflow.workflow_violations(
            ".github/workflows/caller.yml", CALLER, self.root, candidate=candidate
        )
        self.assertIn(
            "invalid-local-reusable-workflow", {item[1] for item in violations}
        )
        (self.directory / "untracked.yml").write_text(LEAF)
        untracked = CALLER.replace("leaf.yml", "untracked.yml")
        self.caller.write_text(untracked)
        git("add", ".github/workflows/caller.yml")
        untracked_candidate = git(
            "commit-tree", git("write-tree"), "-m", "Untracked callee fixture"
        )
        self.assertTrue(
            workflow.workflow_violations(
                ".github/workflows/caller.yml",
                untracked,
                self.root,
                candidate=untracked_candidate,
            )
        )
        self.caller.write_text(CALLER)
        git("add", ".github/workflows/caller.yml")
        self.leaf.write_text(LEAF)
        git(
            "update-index",
            "--cacheinfo",
            "120000",
            original_blob,
            ".github/workflows/leaf.yml",
        )
        replacement = git("commit-tree", git("write-tree"), "-m", "Link fixture")
        self.assertTrue(
            workflow.workflow_violations(
                ".github/workflows/caller.yml", CALLER, self.root, candidate=replacement
            )
        )
        git("replace", candidate, replacement)
        with patch.dict(
            os.environ,
            {"GIT_DIR": "/nonexistent/ambient-git", "GIT_NO_REPLACE_OBJECTS": "0"},
        ):
            self.assertEqual(
                workflow.workflow_violations(
                    ".github/workflows/caller.yml",
                    CALLER,
                    self.root,
                    candidate=candidate,
                ),
                [],
            )

    def test_verify_rejects_safe_worktree_substituting_an_unsafe_candidate_caller(self):
        environment = {
            **workflow.git_environment(),
            "GIT_AUTHOR_NAME": "Fixture",
            "GIT_AUTHOR_EMAIL": "fixture@example.test",
            "GIT_COMMITTER_NAME": "Fixture",
            "GIT_COMMITTER_EMAIL": "fixture@example.test",
        }

        def git(*arguments):
            return (
                subprocess.check_output(
                    ["git", "-C", str(self.root), *arguments],
                    env=environment,
                    stderr=subprocess.DEVNULL,
                )
                .decode()
                .strip()
            )

        git("init", "--quiet")
        self.caller.write_text(CALLER)
        git("add", ".")
        git("commit", "--quiet", "-m", "Safe base")
        base = git("rev-parse", "HEAD")
        self.caller.write_text(CALLER.replace("contents: read", "contents: write"))
        git("add", ".")
        git("commit", "--quiet", "-m", "Unsafe candidate")
        candidate = git("rev-parse", "HEAD")
        self.caller.write_text(CALLER)
        captured = io.StringIO()
        with (
            patch.object(POLICY, "ROOT", self.root),
            contextlib.redirect_stdout(captured),
        ):
            result = POLICY.verify(base, candidate, None)
        receipt = json.loads(captured.getvalue())
        self.assertEqual(result, 1)
        self.assertEqual(receipt["head"], candidate)
        self.assertEqual(receipt["status"], "FAIL_HEPTA_REPOSITORY_INTEGRITY")
        self.assertIn(
            "invalid-candidate-file", {item["rule"] for item in receipt["violations"]}
        )

    def test_verify_rejects_changed_caller_missing_or_outside_regular_file_bounds(self):
        candidate_text = CALLER + "# candidate\n"
        base, candidate = self.candidate_change(self.caller, CALLER, candidate_text)
        for kind in (
            "missing",
            "directory",
            "symlink",
            "fifo",
            "oversized",
            "hardlink",
        ):
            with self.subTest(kind=kind):
                self.caller.unlink()
                if kind == "directory":
                    self.caller.mkdir()
                elif kind == "symlink":
                    self.caller.symlink_to(self.leaf)
                elif kind == "fifo":
                    os.mkfifo(self.caller)
                elif kind == "oversized":
                    self.caller.write_text("x" * (workflow.MAX_BYTES + 1))
                elif kind == "hardlink":
                    os.link(self.leaf, self.caller)
                result, receipt = self.verify(base, candidate)
                self.assertEqual(result, 1)
                self.assertEqual(receipt["status"], "FAIL_HEPTA_REPOSITORY_INTEGRITY")
                self.assertEqual(
                    receipt["scannedPaths"], [".github/workflows/caller.yml"]
                )
                self.assertEqual(
                    {item["rule"] for item in receipt["violations"]},
                    {"invalid-candidate-file"},
                )
                if kind == "directory":
                    self.caller.rmdir()
                else:
                    self.caller.unlink(missing_ok=True)
                self.caller.write_text(candidate_text)

    def test_verify_scans_unicode_tab_and_newline_workflow_names(self):
        for name in ("caller-界.yml", "caller-\t.yml", "caller-\n.yml"):
            with self.subTest(name=name):
                target = self.directory / name
                base, candidate = self.candidate_change(
                    target, CALLER, CALLER.replace("contents: read", "contents: write")
                )
                result, receipt = self.verify(base, candidate)
                self.assertEqual(result, 1)
                self.assertEqual(receipt["scannedPaths"], [".github/workflows/" + name])
                self.assertIn(
                    "contents-write", {item["rule"] for item in receipt["violations"]}
                )
        safe = self.directory / "checkout-安全.yml"
        base, candidate = self.candidate_change(safe, LEAF, LEAF + "# candidate\n")
        result, receipt = self.verify(base, candidate)
        self.assertEqual(result, 0)
        self.assertEqual(
            receipt["scannedPaths"], [".github/workflows/checkout-安全.yml"]
        )
        self.assertEqual(receipt["violations"], [])

    def test_verify_rejects_non_utf8_git_filenames_explicitly(self):
        target = Path(os.fsdecode(os.fsencode(self.directory) + b"/caller-\xff.yml"))
        base, candidate = self.candidate_change(
            target, CALLER, CALLER.replace("contents: read", "contents: write")
        )
        with self.assertRaisesRegex(SystemExit, "filename is not valid UTF-8"):
            self.verify(base, candidate)

    def test_verify_resolves_refs_and_reports_only_canonical_commits(self):
        base, candidate = self.candidate_change(
            self.caller, CALLER, CALLER + "# candidate\n"
        )
        for name, commit in (("fixture-base", base), ("fixture-head", candidate)):
            subprocess.check_call(
                ["git", "-C", str(self.root), "branch", name, commit],
                env=workflow.git_environment(),
            )
        result, receipt = self.verify("fixture-base", "fixture-head")
        self.assertEqual(result, 0)
        self.assertEqual((receipt["base"], receipt["head"]), (base, candidate))
        for arguments in (
            ("--not-a-reference", candidate),
            (base, "--not-a-reference"),
        ):
            with self.subTest(arguments=arguments), self.assertRaises(SystemExit):
                self.verify(*arguments)

    def test_verify_binds_changed_script_bytes_without_unbounded_text_read(self):
        script = self.root / "scripts/check.py"
        base, candidate = self.candidate_change(
            script, "print('base')\n", "print('candidate')\n"
        )
        with patch.object(
            Path, "read_text", side_effect=AssertionError("unbounded read")
        ):
            result, receipt = self.verify(base, candidate)
        self.assertEqual(result, 0)
        self.assertEqual(receipt["violations"], [])
        script.write_text("print('base')\n")
        result, receipt = self.verify(base, candidate)
        self.assertEqual(result, 1)
        self.assertEqual(
            {item["rule"] for item in receipt["violations"]}, {"invalid-candidate-file"}
        )

    def test_self_bypass_scan_reuses_its_single_bounded_candidate_capture(self):
        own = self.root / "scripts/hepta-repository-integrity.py"
        base, candidate = self.candidate_change(
            own, "pass\n", 'subprocess.run(["git", "push"])\n'
        )
        with (
            patch.object(
                Path, "read_text", side_effect=AssertionError("unbounded read")
            ),
            patch.object(
                POLICY, "_read_workflow", wraps=workflow._read_workflow
            ) as reader,
        ):
            result, receipt = self.verify(base, candidate)
        self.assertEqual(reader.call_count, 1)
        self.assertEqual(result, 1)
        self.assertEqual(
            {item["rule"] for item in receipt["violations"]}, {"self-bypass"}
        )

    def test_cycles_depth_and_fanout_have_hard_bounds(self):
        self.leaf.write_text(CALLER.replace("workflow_dispatch:", "workflow_call:"))
        self.assertIn("reusable-workflow-cycle-or-depth", self.rules())
        for number in range(workflow.MAX_DEPTH + 1):
            text = CALLER.replace("leaf.yml", f"depth{number + 1}.yml").replace(
                "workflow_dispatch:", "workflow_call:"
            )
            (self.directory / f"depth{number}.yml").write_text(text)
        self.assertIn(
            "reusable-workflow-cycle-or-depth",
            self.rules(CALLER.replace("leaf.yml", "depth0.yml")),
        )
        jobs = []
        for number in range(workflow.MAX_WORKFLOWS):
            (self.directory / f"wide{number}.yml").write_text(LEAF)
            jobs.append(
                f"  child{number}:\n    uses: ./.github/workflows/wide{number}.yml\n"
            )
        text = CALLER.split("jobs:\n", 1)[0] + "jobs:\n" + "".join(jobs)
        with patch.object(
            workflow, "_read_workflow", wraps=workflow._read_workflow
        ) as reader:
            self.assertIn("reusable-workflow-count-limit", self.rules(text))
            self.assertEqual(reader.call_count, workflow.MAX_WORKFLOWS - 1)

    def test_real_receipt_bound_recovery_workflow_passes(self):
        root = Path(__file__).resolve().parents[1]
        path = ".github/workflows/hepta-supervisor-recovery-check.yml"
        with patch.object(POLICY, "ROOT", root):
            self.assertEqual(POLICY.scan_path(path, (root / path).read_text()), [])


if __name__ == "__main__":
    unittest.main()
