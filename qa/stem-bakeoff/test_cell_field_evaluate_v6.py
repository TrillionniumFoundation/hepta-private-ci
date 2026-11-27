"""V6 renamed matched baselines preserve the full closed-family inference."""

import unittest

from cell_field_evaluate_v5 import evaluate_probabilities as previous_evaluate, evaluation_protocol as previous_protocol
from cell_field_evaluate_v6 import (CANDIDATE, POLICIES, FROM_PREVIOUS, TO_PREVIOUS, evaluate_probabilities,
                                    evaluation_protocol, translate)
import test_cell_field_evaluate_v5


class EvaluationV6Tests(unittest.TestCase):
    def test_bijective_mapping_preserves_every_gate_and_exact_bootstrap_number(self):
        p, y, c, costs = test_cell_field_evaluate_v5.EvaluationV5Tests().fixture()
        baseline = previous_evaluate(p, y, c, previous_protocol(), costs)
        new_p, new_costs = translate(p, FROM_PREVIOUS), translate(costs, FROM_PREVIOUS)
        actual = evaluate_probabilities(new_p, y, c, evaluation_protocol(), new_costs)
        self.assertEqual(set(new_costs["agnews"]["linear"][7])-{"warmup_old"}, set(POLICIES))
        self.assertEqual(translate(actual["primary_contrasts"], TO_PREVIOUS), baseline["primary_contrasts"])
        self.assertEqual(translate(actual["cost_contrasts"], TO_PREVIOUS), baseline["cost_contrasts"])
        self.assertEqual((actual["census_complete"], actual["all_registered_gates_met"]), (True, True))

    def test_repaired_candidate_or_baseline_stop_blocks_all_primary_eligibility(self):
        p, y, c, costs = test_cell_field_evaluate_v5.EvaluationV5Tests().fixture()
        p, costs = translate(p, FROM_PREVIOUS), translate(costs, FROM_PREVIOUS)
        costs["agnews"]["linear"][7][CANDIDATE].update(status="not_executed_unsafe", completed_steps=24)
        result = evaluate_probabilities(p, y, c, evaluation_protocol(), costs)
        self.assertTrue(result["census_complete"])
        self.assertFalse(result["all_registered_gates_met"])
        self.assertEqual(result["candidate_completed_fits"], 11)
        plan = evaluation_protocol()
        plan["max_cpu_ratio"] = 4.
        with self.assertRaises(ValueError):
            evaluate_probabilities(p, y, c, plan, costs)


if __name__ == "__main__":
    unittest.main()
