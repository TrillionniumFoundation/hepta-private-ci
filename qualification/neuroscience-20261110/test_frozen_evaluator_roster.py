"""Frozen evaluator and matched resource opportunity, synthetic contract only."""
import unittest
from dataclasses import replace
from study import ContractError, paired_evidence
from test_study import digest
from test_cohort_retention import panel


class FrozenEvaluatorRosterTests(unittest.TestCase):
    def test_cross_seed_evaluator_drift_is_rejected(self):
        rows = panel(11, "ACT", "a11") + panel(17, "ACT", "a17")
        rows = [replace(r, evaluator_digest=digest("future-evaluator"))
                if r.seed == 17 else r for r in rows]
        with self.assertRaisesRegex(ContractError, "frozen evaluator"):
            paired_evidence(rows)

    def test_within_seed_evaluator_drift_is_rejected(self):
        rows = (panel(11, "ACT", "a11") +
                panel(11, "ACT", "b11"))
        rows = [replace(r, evaluator_digest=digest("unfrozen-evaluator"))
                if r.episode_id == "b11" else r for r in rows]
        with self.assertRaisesRegex(ContractError, "frozen evaluator"):
            paired_evidence(rows)

    def test_cross_seed_budget_opportunity_drift_is_rejected(self):
        rows = panel(11, "ACT", "a11") + panel(17, "ACT", "a17")
        rows = [replace(r, compute_budget_us=1000000)
                if r.seed == 17 else r for r in rows]
        with self.assertRaisesRegex(ContractError, "frozen resource opportunity"):
            paired_evidence(rows)

    def test_distinct_task_families_can_have_distinct_prelocked_evaluators(self):
        rows = []
        for seed in (11, 17):
            rows += panel(seed, "ACT", f"a{seed}")
            rows += [replace(r, evaluator_digest=digest("CTRL-evaluator"),
                             query_budget=10)
                     for r in panel(seed, "CTRL", f"c{seed}")]
        self.assertEqual(paired_evidence(rows)["seed_clusters"], 2)

    def test_independent_training_seed_ability_digests_may_differ(self):
        rows = panel(11, "ACT", "a11") + panel(17, "ACT", "a17")
        rows = [replace(r, ability_digest=digest("trained-model-17"))
                if r.seed == 17 else r for r in rows]
        self.assertEqual(paired_evidence(rows)["blocks"], 2)


if __name__ == "__main__":
    unittest.main()
