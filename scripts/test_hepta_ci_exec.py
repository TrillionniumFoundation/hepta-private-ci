"""Exercise the actual command runner in disposable Git repositories."""

import json
import os
from pathlib import Path
import signal
import shutil
import subprocess
import sys
import tempfile
import unittest

RUNNER = Path(__file__).with_name("hepta_ci_exec.py").resolve()


class GitExecutionFixture(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory(prefix="hepta-exec-")
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.repo = self.root / "repo"
        self.repo.mkdir()
        self.git("init", "-q")
        self.git("config", "user.name", "execution-test")
        self.git("config", "user.email", "execution-test@example.invalid")
        (self.repo / "input").write_text("base\n")
        self.git("add", ".")
        self.git("commit", "-qm", "base")
        self.source = self.git("rev-parse", "HEAD")
        self.result = self.root / "result.json"
        self.marker = self.root / "effect"

    def git(self, *args):
        return subprocess.check_output(
            ["git", "-C", str(self.repo), *args], text=True, stderr=subprocess.PIPE
        ).strip()

    def execute(self, code=None, **identity):
        if code is None:
            code = f"from pathlib import Path; Path({str(self.marker)!r}).write_text('executed')"
        return subprocess.run(
            [sys.executable, str(RUNNER), "--output", str(self.result), "--", sys.executable, "-c", code],
            cwd=self.repo,
            env={
                **os.environ, "PYTHONDONTWRITEBYTECODE": "1",
                "SOURCE_SHA": self.source, "TESTED_SHA": self.source,
                "BASE_SHA": "0" * 40, "HEPTA_CI_LANE": "source-head", **identity,
            },
            text=True, capture_output=True, timeout=10,
        )

    def receipt(self):
        return json.loads(self.result.read_text())


class ExecutionRecordTests(GitExecutionFixture):
    def test_actual_command_success_binds_source_tree_parents_and_argv(self):
        result = self.execute()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.marker.read_text(), "executed")
        receipt = self.receipt()
        self.assertEqual(receipt["status"], "passed")
        self.assertEqual(receipt["command_exit_code"], 0)
        self.assertEqual(receipt["before"], receipt["after"])
        self.assertEqual(receipt["before"], {
            "commit": self.source, "tree": self.git("rev-parse", "HEAD^{tree}"),
            "parents": [], "dirty": False,
        })
        self.assertEqual(receipt["command"][:2], [sys.executable, "-c"])

    def test_nonzero_command_is_retained_and_not_converted_to_pass(self):
        result = self.execute("raise SystemExit(23)")
        self.assertEqual(result.returncode, 23)
        self.assertEqual(self.receipt()["command_exit_code"], 23)
        self.assertEqual(self.receipt()["status"], "failed")

    def test_wrong_checkout_and_dirty_inputs_never_dispatch(self):
        variants = ["wrong-sha", "unstaged", "staged", "untracked"]
        for variant in variants:
            with self.subTest(variant=variant):
                self.result.unlink(missing_ok=True)
                if variant == "wrong-sha":
                    result = self.execute(TESTED_SHA="f" * 40)
                else:
                    path = self.repo / ("extra" if variant == "untracked" else "input")
                    path.write_text("unreviewed\n")
                    if variant == "staged":
                        self.git("add", "input")
                    result = self.execute()
                    if variant == "untracked":
                        path.unlink()
                    else:
                        self.git("restore", "--staged", "--worktree", "input")
                self.assertEqual(result.returncode, 2)
                self.assertEqual(self.receipt()["status"], "rejected")
                self.assertFalse(self.marker.exists())

    def test_successful_command_mutating_source_still_fails(self):
        result = self.execute("from pathlib import Path; Path('input').write_text('changed')")
        self.assertEqual(result.returncode, 1)
        receipt = self.receipt()
        self.assertEqual(receipt["command_exit_code"], 0)
        self.assertEqual(receipt["status"], "failed")
        self.assertTrue(receipt["after"]["dirty"])

    def test_source_lane_cannot_relabel_another_commit(self):
        result = self.execute(SOURCE_SHA="f" * 40)
        self.assertEqual(result.returncode, 2)
        self.assertFalse(self.marker.exists())

    def test_synthetic_merge_accepts_only_exact_ordered_parents(self):
        base = self.source
        (self.repo / "input").write_text("source\n")
        self.git("commit", "-qam", "source")
        source = self.git("rev-parse", "HEAD")
        tree = self.git("rev-parse", "HEAD^{tree}")
        merge = self.git("commit-tree", tree, "-p", base, "-p", source, "-m", "synthetic")
        self.git("checkout", "-q", "--detach", merge)
        env = {"SOURCE_SHA": source, "BASE_SHA": base, "TESTED_SHA": merge, "HEPTA_CI_LANE": "base-merge"}
        result = self.execute(**env)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.receipt()["before"]["parents"], [base, source])
        self.result.unlink()
        self.marker.unlink()
        result = self.execute(**{**env, "SOURCE_SHA": base, "BASE_SHA": source})
        self.assertEqual(result.returncode, 2)
        self.assertFalse(self.marker.exists())

    def test_matching_parents_with_wrong_tree_reject_before_command(self):
        base = self.source
        wrong_tree = self.git("rev-parse", "HEAD^{tree}")
        (self.repo / "input").write_text("source change\n")
        self.git("commit", "-qam", "source change")
        source = self.git("rev-parse", "HEAD")
        merge = self.git("commit-tree", wrong_tree, "-p", base, "-p", source, "-m", "wrong tree")
        self.git("checkout", "-q", "--detach", merge)
        result = self.execute(SOURCE_SHA=source, BASE_SHA=base, TESTED_SHA=merge,
                              HEPTA_CI_LANE="base-merge")
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertEqual(self.receipt()["status"], "rejected")
        self.assertIsNone(self.receipt()["command_exit_code"])
        self.assertIn("recomputed", self.receipt()["error"])
        self.assertFalse(self.marker.exists())

    def test_divergent_clean_merge_records_recomputed_tree(self):
        ancestor = self.source
        (self.repo / "source-only").write_text("source\n")
        self.git("add", ".")
        self.git("commit", "-qm", "source change")
        source = self.git("rev-parse", "HEAD")
        self.git("checkout", "-q", "--detach", ancestor)
        (self.repo / "target-only").write_text("target\n")
        self.git("add", ".")
        self.git("commit", "-qm", "target change")
        base = self.git("rev-parse", "HEAD")
        tree = self.git("merge-tree", "--write-tree", base, source)
        merge = self.git("commit-tree", tree, "-p", base, "-p", source, "-m", "merge")
        self.git("checkout", "-q", "--detach", merge)
        result = self.execute(SOURCE_SHA=source, BASE_SHA=base, TESTED_SHA=merge,
                              HEPTA_CI_LANE="base-merge")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.receipt()["recomputed_merge_tree"], tree)
        self.assertEqual(self.receipt()["before"]["tree"], tree)
        self.assertTrue(self.marker.exists())

    def test_conflicting_merge_never_dispatches_an_arbitrary_resolution(self):
        ancestor = self.source
        (self.repo / "input").write_text("source\n")
        self.git("commit", "-qam", "source change")
        source = self.git("rev-parse", "HEAD")
        self.git("checkout", "-q", "--detach", ancestor)
        (self.repo / "input").write_text("target\n")
        self.git("commit", "-qam", "target change")
        base = self.git("rev-parse", "HEAD")
        tree = self.git("rev-parse", "HEAD^{tree}")
        merge = self.git("commit-tree", tree, "-p", base, "-p", source, "-m", "arbitrary resolution")
        self.git("checkout", "-q", "--detach", merge)
        result = self.execute(SOURCE_SHA=source, BASE_SHA=base, TESTED_SHA=merge,
                              HEPTA_CI_LANE="base-merge")
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertEqual(self.receipt()["status"], "rejected")
        self.assertIsNone(self.receipt()["command_exit_code"])
        self.assertFalse(self.marker.exists())

    def test_merge_lane_rejects_symbolic_base_identity(self):
        result = self.execute(BASE_SHA="HEAD", HEPTA_CI_LANE="base-merge")
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertEqual(self.receipt()["error"], "invalid base_sha")
        self.assertFalse(self.marker.exists())

    def test_existing_receipt_cannot_be_overwritten_or_reused(self):
        self.result.write_text("prior result\n")
        result = self.execute()
        self.assertEqual(result.returncode, 2)
        self.assertEqual(self.result.read_text(), "prior result\n")
        self.assertFalse(self.marker.exists())

    @unittest.skipUnless(os.name == "posix", "POSIX signal return codes")
    def test_killed_command_is_failed_not_passed(self):
        result = self.execute("import os, signal; os.kill(os.getpid(), signal.SIGTERM)")
        self.assertEqual(result.returncode, 128 + signal.SIGTERM)
        self.assertEqual(self.receipt()["command_exit_code"], -signal.SIGTERM)
        self.assertEqual(self.receipt()["status"], "failed")

    def test_shallow_checkout_records_real_commit_parents_not_traversal_grafts(self):
        base = self.source
        (self.repo / "input").write_text("next\n")
        self.git("commit", "-qam", "next")
        self.source = self.git("rev-parse", "HEAD")
        shallow = self.root / "shallow"
        subprocess.run(["git", "clone", "-q", "--depth=1", self.repo.as_uri(), str(shallow)], check=True)
        self.repo = shallow
        self.assertEqual(self.git("rev-parse", "--is-shallow-repository"), "true")
        result = self.execute()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.receipt()["before"]["parents"], [base])


class WorkflowCommandBindingTests(GitExecutionFixture):
    """Run the real YAML shell with stand-in executables, not Cargo itself."""

    def setUp(self):
        super().setUp()
        (self.repo / "scripts").mkdir()
        (self.repo / "codex-rs").mkdir()
        shutil.copyfile(RUNNER, self.repo / "scripts" / RUNNER.name)
        self.git("add", ".")
        self.git("commit", "-qm", "runner")
        self.source = self.git("rev-parse", "HEAD")
        binaries = self.root / "bin"
        binaries.mkdir()
        for name in ("just", "cargo"):
            command = binaries / name
            command.write_text(
                f"#!{sys.executable}\n"
                "import json, os, pathlib, sys\n"
                "with open(os.environ['CALLS'], 'a') as stream:\n"
                "    stream.write(json.dumps(sys.argv) + '\\n')\n"
                "raise SystemExit(17 if os.environ.get('FAIL_TOOL') == pathlib.Path(sys.argv[0]).name else 0)\n"
            )
            command.chmod(0o755)
        self.env = {
            **os.environ, "PYTHONDONTWRITEBYTECODE": "1", "PATH": str(binaries) + os.pathsep + os.environ["PATH"],
            "SOURCE_SHA": self.source, "TESTED_SHA": self.source, "BASE_SHA": "0" * 40,
            "HEPTA_CI_LANE": "source-head", "RUNNER_TEMP": str(self.root),
            "SELECTED_PACKAGES": "codex-one codex-two", "CALLS": str(self.root / "calls"),
        }
        workflow = (RUNNER.parents[1] / ".github/workflows/hepta-consolidated-source.yml").read_text()
        block = workflow.split("        id: native-owner-checks\n", 1)[1].split("        run: |\n", 1)[1]
        lines = []
        for line in block.splitlines():
            if line and not line.startswith("          "):
                break
            lines.append(line[10:])
        self.script = "\n".join(lines)

    def test_shell_preserves_test_targets_and_strict_lint_arguments(self):
        result = subprocess.run(["bash", "-c", self.script], cwd=self.repo / "codex-rs",
                                env=self.env, capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        folder = self.root / "hepta-command-records"
        test = json.loads((folder / "owner-test.json").read_text())
        lint = json.loads((folder / "clippy.json").read_text())
        self.assertEqual(test["command"], ["just", "test", "--locked", "-p", "codex-one", "-p", "codex-two"])
        self.assertEqual(lint["command"], ["cargo", "clippy", "--locked", "-p", "codex-one", "-p", "codex-two", "--all-targets", "--", "-D", "warnings"])
        self.assertEqual(test["before"], lint["before"])
        self.assertEqual(test["before"]["commit"], self.source)
        self.assertEqual(test["working_directory"], str(self.repo / "codex-rs"))

    def test_shell_test_failure_has_no_lint_pass_receipt(self):
        result = subprocess.run(["bash", "-c", self.script], cwd=self.repo / "codex-rs",
                                env={**self.env, "FAIL_TOOL": "just"}, capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 17, result.stderr)
        folder = self.root / "hepta-command-records"
        test = json.loads((folder / "owner-test.json").read_text())
        self.assertEqual(test["status"], "failed")
        self.assertFalse((folder / "clippy.json").exists())


if __name__ == "__main__":
    unittest.main()
