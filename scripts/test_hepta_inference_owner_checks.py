import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts import hepta_inference_owner_checks as checks
from scripts.hepta_ci_scope import select


class InferenceOwnerCheckTests(unittest.TestCase):
    def test_every_command_requires_observed_execution_through_repository_test_entry(
        self,
    ):
        plans = checks.commands(Path("/tmp/records"))
        self.assertEqual(len(plans), len(checks.TESTS))
        for command in plans:
            self.assertEqual(command[command.index("--minimum-tests") + 1], "1")
            start = command.index("--") + 1
            self.assertEqual(command[start : start + 2], ["just", "test"])
            self.assertIn("--locked", command)
            self.assertEqual(command[command.index("--retries") + 1], "0")
            self.assertIn("--no-capture", command)
        self.assertIn("--run-ignored", plans[0])
        self.assertTrue(all("--run-ignored" not in command for command in plans[1:]))

    def test_failure_retains_independent_remaining_diagnostics_and_fails_aggregate(
        self,
    ):
        with tempfile.TemporaryDirectory() as directory:
            results = [
                subprocess.CompletedProcess([], code)
                for code in [1] + [0] * (len(checks.TESTS) - 1)
            ]
            with patch.object(checks.subprocess, "run", side_effect=results) as run:
                self.assertEqual(checks.run_suite(Path(directory)), 1)
                self.assertEqual(run.call_count, len(checks.TESTS))
                self.assertTrue(
                    all(call.kwargs["check"] is False for call in run.call_args_list)
                )

    def test_all_commands_must_succeed(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(
                checks.subprocess,
                "run",
                return_value=subprocess.CompletedProcess([], 0),
            ):
                self.assertEqual(checks.run_suite(Path(directory)), 0)

    def test_test_filters_name_existing_source_tests_not_speculative_capabilities(self):
        source = "\n".join(
            path.read_text()
            for path in (checks.ROOT / "codex-rs/hepta-infer-core/src").glob(
                "*_tests.rs"
            )
        )
        for _, name, _ in checks.TESTS:
            self.assertIn(f"fn {name}()", source)
        names = " ".join(name for _, name, _ in checks.TESTS)
        self.assertNotIn("post_compaction", names)
        self.assertNotIn("only_peer_deltas", names)

    def test_both_workflows_consume_the_one_plan(self):
        for name in [
            "hepta-architecture-convergence.yml",
            "hepta-inference-maintenance.yml",
        ]:
            source = (checks.ROOT / ".github/workflows" / name).read_text()
            self.assertIn(
                "python3 scripts/hepta_inference_owner_checks.py --output-dir", source
            )
            for _, test, _ in checks.TESTS:
                self.assertNotIn(test, source)
            self.assertNotIn("post_compaction_multi_generation_curve", source)
            self.assertNotIn("alternating_writers_replay_only_peer_deltas", source)

    def test_shared_recipe_changes_select_real_inference_execution(self):
        scope = select(["scripts/hepta_inference_owner_checks.py"])
        self.assertTrue(scope["native"])
        self.assertTrue(scope["inference"])
        self.assertFalse(scope["effects"])

    def test_native_product_job_does_not_depend_on_registry_or_owner_success(self):
        workflow = (
            checks.ROOT / ".github/workflows/hepta-inference-maintenance.yml"
        ).read_text()
        product = workflow.split("  native-product-regression:", 1)[1]
        self.assertNotIn("needs:", product)
        self.assertIn("--retries 0 -p codex-hepta-infer-worker-host --lib", product)
        self.assertIn("--minimum-tests 1", product)
        self.assertLess(
            product.index("Execute native authorization"),
            product.index("Verify exact source navigation"),
        )
        self.assertIn("always() && steps.identity.outcome == 'success'", product)
        self.assertIn('["source-head","base-merge"]', product)

    def test_real_agentd_witness_and_authorizer_cannot_be_hidden_by_other_tests(self):
        workflow = (
            checks.ROOT / ".github/workflows/hepta-inference-maintenance.yml"
        ).read_text()
        product = workflow.split("  native-product-regression:", 1)[1]
        self.assertIn("test(native_) | test(final_use_authorizer::)", product)
        self.assertIn("native-agentd-witness.json", product)
        self.assertIn("--minimum-tests 1 -- just test", product)
        self.assertIn(
            "test(real_agentd_worker_accepts_fresh_context_and_rejects_final_use_tombstone)",
            product,
        )
        self.assertIn("steps.runtime_binary.outcome == 'success'", product)

    def test_each_lane_pins_root_cargo_to_the_repository_toolchain(self):
        workflow = (
            checks.ROOT / ".github/workflows/hepta-inference-maintenance.yml"
        ).read_text()
        self.assertEqual(workflow.count("printf 'RUSTUP_TOOLCHAIN=%s"), 2)
        self.assertEqual(workflow.count("cd codex-rs && rustc --version --verbose"), 2)
        self.assertEqual(
            workflow.count('tomllib.load(open("codex-rs/rust-toolchain.toml", "rb"))'),
            2,
        )
        self.assertIn("--all-targets -- -D warnings", workflow)
        self.assertEqual(workflow.count('export RUSTUP_TOOLCHAIN="$toolchain"'), 2)
        self.assertEqual(
            workflow.count('rustup toolchain install "$toolchain" --profile minimal'), 2
        )

    def test_native_runtime_is_built_and_bound_before_product_execution(self):
        workflow = (
            checks.ROOT / ".github/workflows/hepta-inference-maintenance.yml"
        ).read_text()
        product = workflow.split("  native-product-regression:", 1)[1]
        self.assertLess(
            product.index("Build exact-source native runtime executable"),
            product.index("Execute native authorization"),
        )
        self.assertIn("-p codex-app-server --bin codex-app-server", product)
        self.assertIn("native-runtime-build.json", product)
        self.assertIn("native-runtime-binary.sha256", product)
        self.assertIn("HEPTA_TEST_CODEX_EXE", product)


if __name__ == "__main__":
    unittest.main()
