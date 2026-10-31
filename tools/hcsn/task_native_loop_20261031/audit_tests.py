"""Independent audit checks, including a dishonest latent-only gain claim."""
import copy
import unittest

import numpy as np

from .audit import expected_transition, independent_features, intervention_gate, public_features


def fixture():
    meta = dict(deadline=6, budget=3, reliability=[[.8]*6, [.8]*6],
                price=[[.1]*6, [.1]*6], duration=[.2, .5, .7, .4, .3, .6])
    state = dict(job=0, tick=0, budget=3, posterior=.5, terminal=False, reads_in_job=0,
                 charged_cost=0., query_cost=0., latency_cost=0., task_elapsed=0., answers=[])
    policy = dict(confusion=[[.9, .1], [.1, .9]], multiplier=1., latency_price=.1,
                  parameters=[0.]*11, family="distribution")
    return meta, state, policy


class AuditTests(unittest.TestCase):
    def test_independent_paid_evidence_and_recovery_clock(self):
        meta, state, policy = fixture()
        for action, observation in (("READ", 1), ("FIRE", None), ("READ", 0), ("FIRE", None)):
            state, _ = expected_transition(meta, state, policy, action, observation)
        self.assertEqual((state["job"], state["tick"], state["budget"], state["terminal"]), (2, 6, 1, True))
        self.assertAlmostEqual(state["task_elapsed"], 2.7)
        self.assertAlmostEqual(state["charged_cost"], .47)
        self.assertEqual([a["prediction"] for a in state["answers"]], [1, 0])
        self.assertAlmostEqual(state["answers"][0]["posterior"], .74)

    def test_failure_cost_and_deadline_cannot_be_erased(self):
        meta, initial, policy = fixture()
        failed, _ = expected_transition(meta, initial, policy, "READ", failed=True)
        self.assertAlmostEqual(failed["charged_cost"], .12)
        self.assertEqual((failed["budget"], failed["tick"], failed["terminal"]), (3, 0, True))
        last = dict(initial, tick=5)
        final, duration = expected_transition(meta, last, policy, "FIRE")
        self.assertAlmostEqual(duration, .6)
        self.assertEqual((final["tick"], final["terminal"]), (7, True))
        with self.assertRaises(AssertionError):
            expected_transition(meta, last, policy, "READ", 1)

    def test_latent_only_change_fails_content_gate(self):
        left = dict(cell_features=[.2, .1, .3, .4, .5], read_trace=["job0_tick0"], task_trace=["READ", "FIRE"])
        right = copy.deepcopy(left)
        right["cell_features"][3] = .9
        result = intervention_gate(left, right)
        self.assertTrue(result["latent_changed"])
        self.assertFalse(result["causal_content_gate"])
        right.update(read_trace=[], task_trace=["SKIP", "STOP"])
        self.assertTrue(intervention_gate(left, right)["causal_content_gate"])
        self.assertFalse(intervention_gate(left, right)["utility_gain_proved"])

    def test_query_and_reset_are_causal_and_side_effect_free(self):
        meta, state, policy = fixture()
        history = [dict(driver=.6, duration=.7, reset=False),
                   dict(driver=-.4, duration=.2, reset=True),
                   dict(driver=.2, duration=.1, reset=False)]
        original = copy.deepcopy(history)
        for family in ("ordinary", "distribution"):
            policy["family"] = family
            full = independent_features(policy, history, .3, .4)
            short = independent_features(policy, history[-1:], .3, .4)
            np.testing.assert_allclose(full, short, atol=1e-13)
        self.assertEqual(history, original)
        first = public_features(meta, state, policy)
        state["answers"] = [{"private_label_should_not_be_input": 999}]
        np.testing.assert_array_equal(first, public_features(meta, state, policy))


if __name__ == "__main__":
    unittest.main()
