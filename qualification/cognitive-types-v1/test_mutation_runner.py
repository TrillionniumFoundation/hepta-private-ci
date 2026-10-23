import unittest

from run_mutations import (
    RECIPES,
    TARGETED_MUTATION_SCOPE,
    mutate_once,
    observed_kill,
    observed_rust_test_kill,
    observed_rust_test_pass,
    rust_test_command,
)


class MutationRunnerTests(unittest.TestCase):
    def test_anchor_is_exact_and_unambiguous(self):
        recipe = {"name": "fixture", "old": "CHECK", "new": "MUTANT"}
        self.assertEqual(mutate_once("before CHECK after", recipe), "before MUTANT after")
        for source in ["missing", "CHECK CHECK"]:
            with self.assertRaises(ValueError):
                mutate_once(source, recipe)

    def test_recipe_inventory_covers_every_reviewed_identity_key(self):
        expected = {
            "provenance-logical-identity": "event:logical-provenance-conflict",
            "recall-selected-event-logical-identity": "recall:logical-event-conflict",
            "recall-active-node-logical-identity": "recall:logical-active-node-conflict",
            "recall-activation-path-logical-identity": "recall:logical-activation-path-conflict",
            "plasticity-weight-target-logical-identity": "plasticity:logical-target-conflict",
            "plasticity-threshold-target-logical-identity": "plasticity:logical-threshold-conflict",
            "topology-node-logical-identity": "topology:logical-node-conflict",
            "schema-bound-digest-domain": "ModalitySpanRefV1:golden",
            "recall-path-resource-accounting": "recall:underreported-synapses",
            "recall-node-resource-accounting": "recall:underreported-path-nodes",
            "actual-serialization-byte-budget": "wire_budget_tests::actual_serialization_is_bounded_when_preflight_observation_changes",

            "consumer-payload-family": "consumer_tests::payload_consumer_matrix_fails_closed",
        }
        self.assertEqual(len(RECIPES), 12)
        self.assertEqual(
            {
                row["name"]: row.get("case", row.get("test"))
                for row in RECIPES
            },
            expected,
        )
        self.assertEqual(len({row["file"] + row["old"] for row in RECIPES}), 12)
        self.assertEqual(
            TARGETED_MUTATION_SCOPE,
            "twelve-targeted-source-mutants-not-global-mutation-coverage",
        )

    def test_only_observed_wrong_semantics_count_as_killed(self):
        killed = {
            "exit_code": 0,
            "report": {"outcome": "accepted"},
            "passed": False,
            "status": "failed",
        }
        self.assertTrue(observed_kill(killed))
        for invalid in [
            {},
            dict(killed, exit_code=101),
            dict(killed, status="infrastructure_invalid"),
            dict(killed, report={"outcome": "rejected"}),
            dict(killed, passed=True),
        ]:
            self.assertFalse(observed_kill(invalid))

    def test_exact_rust_regression_failure_counts_after_a_successful_build(self):
        name = "consumer_tests::payload_consumer_matrix_fails_closed"
        failed = {"exit_code": 101, "status": "failed"}
        log = (
            "running 1 test\n"
            f"test {name} ... FAILED\n\n"
            "test result: FAILED. 0 passed; 1 failed\n"
        )
        self.assertTrue(observed_rust_test_kill(failed, log, name))
        for result, text in [
            ({"exit_code": 0, "status": "passed"}, log),
            (failed, "test result: FAILED"),
            (failed, f"test {name} ... FAILED"),
            ({"exit_code": None, "status": "infrastructure_invalid"}, log),
        ]:
            self.assertFalse(observed_rust_test_kill(result, text, name))

    def test_pass_requires_the_named_regression_to_execute(self):
        name = "consumer_tests::payload_consumer_matrix_fails_closed"
        passed = {"exit_code": 0, "status": "passed"}
        log = f"test {name} ... ok\ntest result: ok. 1 passed; 0 failed; 0 ignored"
        self.assertTrue(observed_rust_test_pass(passed, log, name))
        for result, text in [
            (passed, "running 0 tests\ntest result: ok. 0 passed; 0 failed"),
            (passed, log.replace(name, "other::test")),
            (dict(passed, exit_code=101), log),
            (dict(passed, status="infrastructure_invalid"), log),
        ]:
            self.assertFalse(observed_rust_test_pass(result, text, name))

    def test_rust_mutation_command_is_exact_and_compile_first(self):
        name = "consumer_tests::payload_consumer_matrix_fails_closed"
        self.assertEqual(
            rust_test_command(name, no_run=True),
            [
                "cargo",
                "test",
                "--locked",
                "-p",
                "codex-hepta-cognitive-types",
                "--lib",
                "--no-run",
                name,
            ],
        )
        self.assertEqual(
            rust_test_command(name)[-3:],
            ["--", "--exact", "--nocapture"],
        )


if __name__ == "__main__":
    unittest.main()
