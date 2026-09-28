import unittest

from run_mutations import RECIPES, TARGETED_MUTATION_SCOPE, mutate_once, observed_kill


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
        }
        self.assertEqual(len(RECIPES), 8)
        self.assertEqual({row["name"]: row["case"] for row in RECIPES}, expected)
        self.assertEqual(len({row["file"] + row["old"] for row in RECIPES}), 8)
        self.assertEqual(
            TARGETED_MUTATION_SCOPE,
            "eight-targeted-source-mutants-not-global-mutation-coverage",
        )

    def test_only_observed_wrong_semantics_count_as_killed(self):
        killed = {"exit_code": 0, "report": {"outcome": "accepted"}, "passed": False, "status": "failed"}
        self.assertTrue(observed_kill(killed))
        for invalid in [{}, dict(killed, exit_code=101), dict(killed, status="infrastructure_invalid"),
                        dict(killed, report={"outcome": "rejected"}), dict(killed, passed=True)]:
            self.assertFalse(observed_kill(invalid))


if __name__ == "__main__":
    unittest.main()
