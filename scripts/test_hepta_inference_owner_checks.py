import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts import hepta_inference_owner_checks as checks
from scripts.hepta_ci_scope import select


class InferenceOwnerCheckTests(unittest.TestCase):
    def test_every_command_requires_observed_execution_through_repository_test_entry(self):
        plans = checks.commands(Path("/tmp/records"))
        self.assertEqual(len(plans), 3)
        for command in plans:
            self.assertEqual(command[command.index("--minimum-tests") + 1], "1")
            start = command.index("--") + 1
            self.assertEqual(command[start:start + 2], ["just", "test"])
            self.assertIn("--locked", command)
            self.assertEqual(command[command.index("--retries") + 1], "0")
            self.assertIn("--no-capture", command)
        self.assertIn("--run-ignored", plans[0])
        self.assertTrue(all("--run-ignored" not in command for command in plans[1:]))

    def test_failure_retains_independent_remaining_diagnostics_and_fails_aggregate(self):
        with tempfile.TemporaryDirectory() as directory:
            results = [subprocess.CompletedProcess([], code) for code in [1, 0, 0]]
            with patch.object(checks.subprocess, "run", side_effect=results) as run:
                self.assertEqual(checks.run_suite(Path(directory)), 1)
                self.assertEqual(run.call_count, 3)
                self.assertTrue(all(call.kwargs["check"] is False for call in run.call_args_list))

    def test_all_commands_must_succeed(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(checks.subprocess, "run", return_value=subprocess.CompletedProcess([], 0)):
                self.assertEqual(checks.run_suite(Path(directory)), 0)

    def test_test_filters_name_existing_source_tests_not_speculative_capabilities(self):
        source = (checks.ROOT / "codex-rs/hepta-infer-core/src/native_growth_tests.rs").read_text()
        for _, name, _ in checks.TESTS:
            self.assertIn(f"fn {name}()", source)
        names = " ".join(name for _, name, _ in checks.TESTS)
        self.assertNotIn("post_compaction", names)
        self.assertNotIn("only_peer_deltas", names)

    def test_both_workflows_consume_the_one_plan(self):
        for name in ["hepta-architecture-convergence.yml", "hepta-inference-maintenance.yml"]:
            source = (checks.ROOT / ".github/workflows" / name).read_text()
            self.assertIn("python3 scripts/hepta_inference_owner_checks.py --output-dir", source)
            for _, test, _ in checks.TESTS:
                self.assertNotIn(test, source)
            self.assertNotIn("post_compaction_multi_generation_curve", source)
            self.assertNotIn("alternating_writers_replay_only_peer_deltas", source)

    def test_shared_recipe_changes_select_real_inference_execution(self):
        scope = select(["scripts/hepta_inference_owner_checks.py"])
        self.assertTrue(scope["native"])
        self.assertTrue(scope["inference"])
        self.assertFalse(scope["effects"])


if __name__ == "__main__":
    unittest.main()
