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
    def command_map(self):
        with tempfile.TemporaryDirectory() as directory:
            return {name: (argv, cwd) for name, argv, cwd in MODULE.commands(Path(directory))}

    def test_every_filtered_qualification_command_is_discovery_guarded(self):
        commands = self.command_map()
        self.assertEqual(set(MODULE.REQUIRED_FILTERS), {
            "signed-e2e",
            "shadow-consumer",
            "plasticity-consumer",
            "agentd-consumer",
            "agentd-outcome-consumer",
            "cold-recovery-e2e",
        })
        for name, spec in MODULE.REQUIRED_FILTERS.items():
            argv, cwd = commands[name]
            self.assertEqual(cwd, ".")
            self.assertEqual(argv[1], "scripts/hepta-nextest-require.py")
            self.assertIn(spec["filter"], argv)
            self.assertIn("--evidence", argv)
            for target in spec.get("tests", []):
                self.assertIn("--test", argv)
                self.assertIn(target, argv)

    def test_stale_agentd_filter_is_absent(self):
        commands = self.command_map()
        argv, _ = commands["agentd-consumer"]
        self.assertIn(
            "signed_candidate_passes_only_with_bound_owner_run_context_and_root_trust",
            argv,
        )
        self.assertNotIn(
            "signed_candidate_passes_only_on_bound_current_owner_and_context",
            " ".join(argv),
        )

    def test_compatibility_fixture_follows_api_surface(self):
        with tempfile.TemporaryDirectory() as directory:
            names = [name for name, _, _ in MODULE.commands(Path(directory))]
        self.assertEqual(
            names.index("trusted-compatibility-fixture"), names.index("api-surface") + 1
        )

    def test_original_command_order_is_preserved(self):
        with tempfile.TemporaryDirectory() as directory:
            original = [name for name, _, _ in MODULE.ORIGINAL_COMMANDS(Path(directory))]
            guarded = [name for name, _, _ in MODULE.commands(Path(directory))]
        without_fixture = [name for name in guarded if name != "trusted-compatibility-fixture"]
        self.assertEqual(without_fixture, original)


if __name__ == "__main__":
    unittest.main()
