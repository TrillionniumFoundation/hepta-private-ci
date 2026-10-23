import contextlib
import copy
import io
import json
import os
import shlex
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from source_guard import SourceGuardError, main, verify_worktrees


def git(root, *args):
    return (
        subprocess.check_output(
            ["git", "-C", str(root), *args], stderr=subprocess.STDOUT
        )
        .decode()
        .strip()
    )


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
            pins[name] = {
                "commit": git(root, "rev-parse", "HEAD"),
                "tree": git(root, "rev-parse", "HEAD^{tree}"),
            }
            self.paths[name] = str(root)

        def digest(n):
            return f"{n:064x}"

        self.base = {
            "schema": "hepta.native-abc.v1",
            "sources": pins,
            "modes": ["A", "B", "C"],
            "scales": [64, 256, 1024, 4096],
            "target_profile_digest": digest(2),
            "model_profile_digest": digest(3),
            "mode_build_digests": {
                m: digest(80 + i) for i, m in enumerate(("A", "B", "C"))
            },
            "resource_limits": {
                "max_input_tokens": 50,
                "max_output_tokens": 10,
                "timeout_ms": 1000,
                "max_cpu_ms": 1000,
                "max_rss_bytes": 10000,
                "max_gpu_memory_bytes": 10000,
                "max_active_concurrency": 4096,
                "max_tool_calls": 2,
            },
            "tasks": [
                {
                    "task_id": "case-1",
                    "seed": 0,
                    "fixture_digest": digest(4),
                    "answer_oracle_digest": digest(5),
                }
            ],
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

    def test_source_match_does_not_bypass_new_build_and_resource_pins(self):
        for field in ("mode_build_digests", "resource_limits"):
            with self.subTest(field=field):
                base = copy.deepcopy(self.base)
                del base[field]
                receipt = verify_worktrees(base, self.paths)
                self.assertFalse(receipt["experiment_pins_present"])
                self.assertFalse(receipt["independent_acceptance"])

    def test_clean_filter_is_rejected_without_executing_it(self):
        root = Path(self.paths["hepta"])
        (root / ".gitattributes").write_text("README.md filter=forge\n")
        git(root, "add", ".gitattributes")
        git(root, "commit", "-qm", "add attribute")
        self.base["sources"]["hepta"] = {
            "commit": git(root, "rev-parse", "HEAD"),
            "tree": git(root, "rev-parse", "HEAD^{tree}"),
        }
        marker = Path(self.temp.name) / "filter-was-executed"
        code = (
            "import pathlib,sys; pathlib.Path("
            + repr(str(marker))
            + ").write_text('executed'); sys.stdout.buffer.write(b'hepta-1\\n')"
        )
        git(
            root,
            "config",
            "filter.forge.clean",
            shlex.quote(sys.executable) + " -c " + shlex.quote(code),
        )
        (root / "README.md").write_text("hepta-2\n")
        with self.assertRaisesRegex(SourceGuardError, "configured Git filters"):
            verify_worktrees(self.base, self.paths)
        self.assertFalse(marker.exists())

    def test_partial_clone_is_rejected_before_transport_can_execute(self):
        root = Path(self.paths["hepta"])
        marker = Path(self.temp.name) / "transport-was-executed"
        code = (
            "import pathlib; pathlib.Path("
            + repr(str(marker))
            + ").write_text('executed')"
        )
        git(root, "config", "remote.lazy.url", "ssh://invalid.example/nonexistent")
        git(root, "config", "remote.lazy.promisor", "true")
        git(
            root,
            "config",
            "core.sshCommand",
            shlex.quote(sys.executable) + " -c " + shlex.quote(code),
        )
        tree = self.base["sources"]["hepta"]["tree"]
        (root / ".git" / "objects" / tree[:2] / tree[2:]).unlink()
        with self.assertRaisesRegex(SourceGuardError, "partial/promisor"):
            verify_worktrees(self.base, self.paths)
        self.assertFalse(marker.exists())

    def test_git_command_hooks_and_environment_overrides_never_execute(self):
        root = Path(self.paths["hepta"])
        (root / ".gitattributes").write_text("README.md diff=guard\n")
        git(root, "add", ".gitattributes")
        git(root, "commit", "-qm", "diff attribute")
        self.base["sources"]["hepta"] = {
            "commit": git(root, "rev-parse", "HEAD"),
            "tree": git(root, "rev-parse", "HEAD^{tree}"),
        }
        marker = Path(self.temp.name) / "git-command-was-executed"
        code = (
            "import pathlib; pathlib.Path("
            + repr(str(marker))
            + ").write_text('executed')"
        )
        command = shlex.quote(sys.executable) + " -c " + shlex.quote(code)
        for key in ("core.fsmonitor", "diff.external", "diff.guard.textconv"):
            git(root, "config", key, command)
        overrides = {
            "GIT_EXTERNAL_DIFF": command,
            "GIT_CONFIG_COUNT": "1",
            "GIT_CONFIG_KEY_0": "core.fsmonitor",
            "GIT_CONFIG_VALUE_0": command,
        }
        with patch.dict(os.environ, overrides):
            self.assertTrue(
                verify_worktrees(self.base, self.paths)["experiment_pins_present"]
            )
            (root / "README.md").write_text("changed\n")
            with self.assertRaises(SourceGuardError):
                verify_worktrees(self.base, self.paths)
        self.assertFalse(marker.exists())

    def test_replacement_refs_do_not_substitute_pinned_source(self):
        root = Path(self.paths["hepta"])
        original = self.base["sources"]["hepta"]["commit"]
        (root / "README.md").write_text("replacement content\n")
        git(root, "add", "README.md")
        git(root, "commit", "-qm", "replacement")
        replacement = git(root, "rev-parse", "HEAD")
        git(root, "switch", "--detach", original)
        git(root, "replace", original, replacement)
        self.assertTrue(
            verify_worktrees(self.base, self.paths)["experiment_pins_present"]
        )
        self.assertEqual((root / "README.md").read_text(), "hepta-1\n")

    def test_normalized_clean_status_is_not_exact_source_bytes(self):
        root = Path(self.paths["hepta"])
        (root / ".gitattributes").write_text("README.md text\n")
        git(root, "add", ".gitattributes")
        git(root, "commit", "-qm", "add text normalization")
        self.base["sources"]["hepta"] = {
            "commit": git(root, "rev-parse", "HEAD"),
            "tree": git(root, "rev-parse", "HEAD^{tree}"),
        }
        (root / "README.md").write_bytes(b"hepta-1\r\n")
        git(root, "add", "README.md")
        self.assertEqual(git(root, "diff", "--cached"), "")
        self.assertEqual(git(root, "status", "--porcelain=v1"), "")
        with self.assertRaisesRegex(SourceGuardError, "raw tracked source bytes"):
            verify_worktrees(self.base, self.paths)

    def test_submodule_is_rejected_before_its_filter_can_execute(self):
        root = Path(self.paths["hepta"])
        git(
            root,
            "-c",
            "protocol.file.allow=always",
            "submodule",
            "add",
            self.paths["runtime"],
            "module",
        )
        sub = root / "module"
        git(sub, "config", "user.name", "Source Guard")
        git(sub, "config", "user.email", "test@example.invalid")
        (sub / ".gitattributes").write_text("README.md filter=forge\n")
        git(sub, "add", ".gitattributes")
        git(sub, "commit", "-qm", "submodule attribute")
        git(root, "add", ".gitmodules", "module")
        git(root, "commit", "-qm", "pin submodule")
        self.base["sources"]["hepta"] = {
            "commit": git(root, "rev-parse", "HEAD"),
            "tree": git(root, "rev-parse", "HEAD^{tree}"),
        }
        marker = Path(self.temp.name) / "submodule-filter-was-executed"
        code = (
            "import pathlib,sys; pathlib.Path("
            + repr(str(marker))
            + ").write_text('executed'); sys.stdout.buffer.write(b'runtime-2\\n')"
        )
        git(
            sub,
            "config",
            "filter.forge.clean",
            shlex.quote(sys.executable) + " -c " + shlex.quote(code),
        )
        (sub / "README.md").write_text("runtime-x\n")
        with self.assertRaisesRegex(SourceGuardError, "submodule source"):
            verify_worktrees(self.base, self.paths)
        self.assertFalse(marker.exists())

    @unittest.skipIf(os.name == "nt", "requires POSIX executable permission bits")
    def test_filemode_config_cannot_hide_executable_bit_changes(self):
        root = Path(self.paths["hepta"])
        source = root / "README.md"
        git(root, "config", "core.filemode", "false")
        source.chmod(0o755)
        self.assertEqual(git(root, "status", "--porcelain=v1"), "")
        with self.assertRaisesRegex(SourceGuardError, "executable bit"):
            verify_worktrees(self.base, self.paths)
        git(root, "update-index", "--chmod=+x", "README.md")
        git(root, "commit", "-qm", "pin executable")
        self.base["sources"]["hepta"] = {
            "commit": git(root, "rev-parse", "HEAD"),
            "tree": git(root, "rev-parse", "HEAD^{tree}"),
        }
        self.assertTrue(
            verify_worktrees(self.base, self.paths)["experiment_pins_present"]
        )
        source.chmod(0o644)
        self.assertEqual(git(root, "status", "--porcelain=v1"), "")
        with self.assertRaisesRegex(SourceGuardError, "executable bit"):
            verify_worktrees(self.base, self.paths)

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
                with self.assertRaisesRegex(
                    SourceGuardError, "modified, staged or untracked"
                ):
                    verify_worktrees(self.base, self.paths)
                git(root, "reset", "--hard", "-q")
                (root / "extra.txt").unlink(missing_ok=True)

    def test_ignored_untracked_build_input_is_not_clean_source(self):
        root = Path(self.paths["hepta"])
        (root / ".git" / "info" / "exclude").write_text("ignored-build-input\n")
        (root / "ignored-build-input").write_text("tampered\n")
        self.assertEqual(git(root, "status", "--porcelain=v1"), "")
        with self.assertRaisesRegex(SourceGuardError, "ignored untracked"):
            verify_worktrees(self.base, self.paths)

    def test_concealed_index_flags_denied(self):
        root = Path(self.paths["hepta"])
        for flag, clear in (
            ("--assume-unchanged", "--no-assume-unchanged"),
            ("--skip-worktree", "--no-skip-worktree"),
        ):
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
        with patch.dict(
            os.environ, {"GIT_DIR": str(Path(self.paths["codex"]) / ".git")}
        ):
            self.assertTrue(
                verify_worktrees(self.base, self.paths)["experiment_pins_present"]
            )

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
