#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
from pathlib import Path
import tempfile
import unittest

SPEC = importlib.util.spec_from_file_location(
    "hepta_learning_eval_exact_entry",
    Path(__file__).with_name("hepta-learning-eval-exact-entry.py"),
)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


class ExactEntrypointTests(unittest.TestCase):
    def test_agentd_filter_is_current_and_guarded(self):
        with tempfile.TemporaryDirectory() as directory:
            commands = {name: (argv, cwd) for name, argv, cwd in MODULE.commands(Path(directory))}
        argv, cwd = commands["agentd-consumer"]
        self.assertEqual(cwd, ".")
        self.assertIn("hepta-nextest-require.py", argv[1])
        self.assertIn(MODULE.AGENTD_REQUIRED_TEST, argv)
        self.assertNotIn("intelligence_evaluation_tests", argv)

    def test_all_original_command_names_are_preserved(self):
        with tempfile.TemporaryDirectory() as directory:
            original = [name for name, _, _ in MODULE.ORIGINAL_COMMANDS(Path(directory))]
            guarded = [name for name, _, _ in MODULE.commands(Path(directory))]
        self.assertEqual(guarded, original)


if __name__ == "__main__":
    unittest.main()
