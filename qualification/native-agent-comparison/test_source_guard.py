import contextlib
import copy
import io
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from source_guard import SourceGuardError, main, verify_worktrees


def git(root, *args):
    return subprocess.check_output(["git", "-C", str(root), *args], stderr=subprocess.STDOUT).decode().strip()


class SourceGuardTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        parent = Path(self.temp.name)
        self.paths = {}
        pins = {}
        for index, name in enumerate(("hepta", "runtime", "codex"), 1):
            root = parent / name
            root.mkdir()
            git(root, "init", "-q")
            git(root, "config", "user.name", "Source Guard")
            git(root, "config", "user.email", "test@example.invalid")
            (root / "README.md").write_text(f"{name}-{index}\n")
            git(root, "add", "README.md")
            git(root, "commit", "-qm", "initial")
            pins[name] = {"commit": git(root, "rev-parse", "HEAD"),
                          "tree": git(root, "rev-parse", "HEAD^{tree}")}
            self.paths[name] = str(root)
        digest = lambda n: f"{n:064x}"
        self.base = {
            "schema": "hepta.native-abc.v1", "sources": pins,
            "modes": ["A", "B", "C"], "scales": [64, 256, 1024, 4096],
            "target_profile_digest": digest(2), "model_profile_digest": digest(3),
            "resource_limits": {"max_input_tokens": 50, "max_output_tokens": 10,
                                "timeout_ms": 1000, "max_rss_bytes": 10000, "max_tool_calls": 2},
            "tasks": [{"task_id": "case-1", "seed": 0, "fixture_digest": digest(4),
                       "answer_oracle_digest": digest(5)}],
        }

    def test_clean_pinned_worktrees_are_local_only(self):
        receipt = verify_worktrees(self.base, self.paths)
        self.assertTrue(receipt["experiment_pins_present"])
        self.assertFalse(receipt["actual_built_source_attested"])
        self.assertFalse(receipt["independent_acceptance"])
        self.assertEqual(set(receipt["verified_worktrees"]), set(self.paths))

    def test_placeholder_model_and_missing_tasks_fail_experiment_gate(self):
        base = copy.deepcopy(self.base)
        base["tasks"] = []
        receipt = verify_worktrees(base, self.paths)
        self.assertFalse(receipt["experiment_pins_present"])
        self.assertIn("HOLD_NO_GO", receipt["experiment_pin_blocker"])

    def test_commit_and_tree_drift_denied(self):
        for field in ("commit", "tree"):
            base = copy.deepcopy(self.base)
            base["sources"]["runtime"][field] = "f" * 40
            with self.assertRaisesRegex(SourceGuardError, "commit/tree drift"):
                verify_worktrees(base, self.paths)

    def test_staged_unstaged_untracked_denied(self):
        root = Path(self.paths["codex"])
        for mode in ("tracked", "staged", "untracked"):
            with self.subTest(mode=mode):
                if mode == "untracked":
                    (root / "extra.txt").write_text("extra\n")
                else:
                    (root / "README.md").write_text("tampered\n")
                    if mode == "staged":
                        git(root, "add", "README.md")
                with self.assertRaisesRegex(SourceGuardError, "modified, staged or untracked"):
                    verify_worktrees(self.base, self.paths)
                git(root, "reset", "--hard", "-q")
                (root / "extra.txt").unlink(missing_ok=True)

    def test_concealed_index_flags_denied(self):
        root = Path(self.paths["hepta"])
        for flag, clear in (("--assume-unchanged", "--no-assume-unchanged"),
                            ("--skip-worktree", "--no-skip-worktree")):
            with self.subTest(flag=flag):
                git(root, "update-index", flag, "README.md")
                with self.assertRaisesRegex(SourceGuardError, "index entry"):
                    verify_worktrees(self.base, self.paths)
                git(root, "update-index", clear, "README.md")

    def test_missing_or_nested_path_denied(self):
        paths = dict(self.paths)
        paths["runtime"] = paths["runtime"] + "/not-found"
        with self.assertRaisesRegex(SourceGuardError, "path unavailable"):
            verify_worktrees(self.base, paths)
        child = Path(self.paths["runtime"]) / "child"
        child.mkdir()
        paths["runtime"] = str(child)
        with self.assertRaisesRegex(SourceGuardError, "not the repository root"):
            verify_worktrees(self.base, paths)

    def test_git_environment_override_cannot_change_observed_repo(self):
        # A caller-supplied GIT_DIR must not silently redirect all three reads.
        with patch.dict(os.environ, {"GIT_DIR": str(Path(self.paths["codex"]) / ".git")}):
            self.assertTrue(verify_worktrees(self.base, self.paths)["experiment_pins_present"])

    def test_cli_exit_is_closed_for_incomplete_plan(self):
        base = copy.deepcopy(self.base)
        base["target_profile_digest"] = None
        f = Path(self.temp.name) / "BASELINE.json"
        f.write_text(json.dumps(base))
        args = ["--baseline", str(f)]
        for name, path in self.paths.items():
            args += ["--" + name, path]
        with contextlib.redirect_stdout(io.StringIO()) as output:
            self.assertEqual(main(args), 1)
        self.assertFalse(json.loads(output.getvalue())["experiment_pins_present"])


if __name__ == "__main__":
    unittest.main()
