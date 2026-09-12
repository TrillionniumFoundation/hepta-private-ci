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


    def test_documentation_blocks_cannot_supply_commands_or_actions(self):
        for marker in ("|", "|-", ">-", "|2", "| # example"):
            with self.subTest(marker=marker):
                text = (
                    f"description: {marker}\n"
                    "  run: git merge-tree --write-tree base source\n"
                    "  uses: ./missing\n"
                    "  run: git commit-tree tree\n"
                )
                self.assertEqual(workflow_commands(text), [])
                self.assertEqual(declared_commands(text, ROOT), [])
                with self.assertRaises(ValueError):
                    verify_synthetic_merge(text, ROOT)

    def test_run_block_does_not_consume_sibling_metadata(self):
        text = (
            "steps:\n  - run: |\n      echo executed\n"
            "    name: metadata is not a command\n"
            "    env:\n      EXAMPLE: value\n"
            "  - run: echo next\n"
        )
        self.assertEqual(
            workflow_commands(text), [["echo", "executed"], ["echo", "next"]]
        )

    def test_commented_block_header_is_not_a_shell_command(self):
        self.assertEqual(
            workflow_commands("run: | # actual script\n  echo executed\n"),
            [["echo", "executed"]],
        )

    def test_quoted_local_actions_resolve_and_still_reject_escapes(self):
        for quote in ("'", '\"'):
            with self.subTest(quote=quote):
                verify_synthetic_merge(
                    f"steps:\n  - uses: {quote}./.github/actions/hepta-synthetic-merge{quote} # shared\n",
                    ROOT,
                )
                with self.assertRaises(ValueError):
                    declared_commands(f"uses: {quote}./../outside{quote}\n", ROOT)

    def test_local_action_symlinks_cannot_escape_root(self):
        with tempfile.TemporaryDirectory() as directory:
            parent = Path(directory)
            root = parent / "root"
            root.mkdir()
            outside = parent / "outside"
            outside.mkdir()
            (outside / "action.yml").write_text(
                "runs:\n  using: composite\n  steps:\n    - run: echo outside\n"
            )
            (root / "linked").symlink_to(outside, target_is_directory=True)
            with self.assertRaises(ValueError):
                declared_commands("uses: ./linked\n", root)
            inside = root / "inside"
            inside.mkdir()
            (inside / "action.yml").symlink_to(outside / "action.yml")
            with self.assertRaises(ValueError):
                declared_commands("uses: ./inside\n", root)

    def test_action_metadata_cannot_claim_composite_execution(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "action.yml").write_text(
                "description: |\n  using: composite\n"
                "runs:\n  using: node20\n  main: index.js\n"
            )
            with self.assertRaisesRegex(ValueError, "execution profile"):
                declared_commands("uses: ./\n", root)

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
