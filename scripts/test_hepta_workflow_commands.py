"""Execution-path checks for local actions, and real Git merge behavior."""

import os
from pathlib import Path
import subprocess
import tempfile
import unittest

from hepta_workflow_commands import (
    declared_commands,
    verify_synthetic_merge,
    workflow_commands,
)

ROOT = Path(__file__).resolve().parents[1]


class WorkflowCommandTests(unittest.TestCase):
    def test_only_run_scalars_are_commands(self):
        self.assertEqual(
            workflow_commands("""name: cargo test
steps:
  - run: >-
      just test --locked
      -p example
  - run: |
      # cargo test --locked -p misleading
      echo cargo test
      python3 scripts/check.py verify
"""),
            [
                ["just", "test", "--locked", "-p", "example"],
                ["echo", "cargo", "test"],
                ["python3", "scripts/check.py", "verify"],
            ],
        )

    def test_real_workflow_resolves_composite_action(self):
        text = (ROOT / ".github/workflows/hepta-development-docs.yml").read_text()
        verify_synthetic_merge(text, ROOT)
        with self.assertRaisesRegex(ValueError, "missing executable"):
            verify_synthetic_merge(
                text.replace(
                    "uses: ./.github/actions/hepta-synthetic-merge",
                    "name: unused action",
                ),
                ROOT,
            )

    def test_comment_or_echo_cannot_stand_in_for_merge(self):
        for line in (
            "# git merge-tree --write-tree base source",
            "echo git merge-tree --write-tree base source",
        ):
            with self.subTest(line=line), self.assertRaises(ValueError):
                verify_synthetic_merge(
                    f"run: |\n  {line}\n  echo git commit-tree tree\n", ROOT
                )

    def test_shell_payload_does_not_register_a_local_action(self):
        text = "run: |\n  cat <<END\n  uses: ./missing\n  END\n"
        declared_commands(text, ROOT)

    def test_local_action_path_and_cycle_reject(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            action = root / "a"
            action.mkdir()
            (action / "action.yml").write_text(
                "runs:\n  using: composite\n  steps:\n    - uses: ./a\n"
            )
            for target in ("./a", "./../outside", "./missing"):
                with self.subTest(target=target), self.assertRaises(ValueError):
                    declared_commands(f"steps:\n  - uses: {target}\n", root)


class SyntheticMergeExecutionTests(unittest.TestCase):
    def test_shared_action_builds_ordered_repeatable_candidate(self):
        action = (ROOT / ".github/actions/hepta-synthetic-merge/action.yml").read_text()
        script = action.split("      run: |\n", 1)[1]
        script = "\n".join(line[8:] for line in script.splitlines())
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)

            def git(*args):
                return subprocess.check_output(
                    ["git", "-C", str(root), *args], text=True, stderr=subprocess.PIPE
                ).strip()

            git("init", "-q")
            git("config", "user.name", "test")
            git("config", "user.email", "test@example.invalid")
            (root / "base").write_text("base\n")
            git("add", ".")
            git("commit", "-qm", "initial")
            initial = git("rev-parse", "HEAD")
            (root / "source").write_text("source\n")
            git("add", ".")
            git("commit", "-qm", "source")
            source = git("rev-parse", "HEAD")
            git("checkout", "--detach", initial)
            (root / "target").write_text("target\n")
            git("add", ".")
            git("commit", "-qm", "target")
            base = git("rev-parse", "HEAD")
            outputs = []
            for number in range(2):
                git("checkout", "--detach", source)
                output = root / f"output-{number}"
                environment = {
                    **os.environ,
                    "BASE_SHA": base,
                    "SOURCE_SHA": source,
                    "PR_NUMBER": "1",
                    "AUTHOR_NAME": "test",
                    "AUTHOR_EMAIL": "test@example.invalid",
                    "MESSAGE": "test merge",
                    "GITHUB_OUTPUT": str(output),
                }
                result = subprocess.run(
                    ["bash", "-c", script],
                    cwd=root,
                    env=environment,
                    capture_output=True,
                    text=True,
                )
                self.assertEqual(result.returncode, 0, result.stderr)
                outputs.append(
                    dict(line.split("=", 1) for line in output.read_text().splitlines())
                )
                self.assertEqual(
                    git("rev-list", "--parents", "-n", "1", "HEAD"),
                    f"{outputs[-1]['sha']} {base} {source}",
                )
                self.assertEqual((root / "source").read_text(), "source\n")
                self.assertEqual((root / "target").read_text(), "target\n")
            self.assertEqual(outputs[0], outputs[1])
            git("checkout", "--detach", base)
            result = subprocess.run(
                ["bash", "-c", script],
                cwd=root,
                env=environment,
                capture_output=True,
                text=True,
            )
            self.assertNotEqual(
                result.returncode, 0, "incorrect checked-out source must fail"
            )


if __name__ == "__main__":
    unittest.main()
