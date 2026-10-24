"""Command admission never substitutes a gold action or relaxes the task gate."""

from pathlib import Path
import unittest

from baseline_study import input_only
from task_execution import action_argv


class TaskExecutionTests(unittest.TestCase):
    def test_original_input_hint_is_preserved(self):
        self.assertEqual(
            input_only(
                dict(text="help: run 'rustup component add clippy' to install it")
            ),
            "rustup component add clippy",
        )
        self.assertIsNone(input_only(dict(text="help: Remove unused import")))

    def test_actions_are_constrained_without_changing_frozen_check(self):
        root = Path("/tmp/registered-task")
        executable = Path("/tmp/registered-ruff")
        argv, error = action_argv("ruff check --fix file.py", executable, root)
        self.assertIsNone(error)
        self.assertEqual(
            argv, [str(executable), "check", "--no-cache", "--fix", "file.py"]
        )
        for text in (
            "ruff check --ignore E731 file.py",
            "ruff check --fix ../outside.py",
            "ruff check --fix /tmp/outside.py",
            "python -c 'print(1)'",
            "ruff check; rm file.py",
        ):
            self.assertIsNone(action_argv(text, executable, root)[0], text)


if __name__ == "__main__":
    unittest.main()
