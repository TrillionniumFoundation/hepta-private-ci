"""Behavioral and independent-reference tests for R15."""

import copy
import json
import unittest

import numpy as np

from .audit import behavior_audit, numerical_audit, world_event_audit
from .calibration import likelihood, make_training
from .law import Law, default_free_raw
from .planner import BeliefMemory


class IndependentAuditTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.law = Law()

    def test_generator_first_event_and_repeated_events(self):
        report = numerical_audit(self.law)
        self.assertTrue(report["passed"])
        self.assertGreater(report["repeated_events"]["expected_count"], 1.)

    def test_actual_addressed_memory_planning_and_replay(self):
        self.assertTrue(behavior_audit(self.law)["passed"])

    def test_exogenous_write_distractor_and_score_before_write(self):
        self.assertTrue(world_event_audit(self.law)["passed"])

    def test_free_family_contains_same_initial_operator(self):
        free = Law(mode="free", free_raw=default_free_raw(tuple(self.law.theta)))
        np.testing.assert_allclose(free.Q, self.law.Q, rtol=0, atol=2e-13)
        for duration in (.35, .95):
            np.testing.assert_allclose(free.transition(duration), self.law.transition(duration),
                                       rtol=0, atol=2e-13)

    def test_public_likelihood_and_frozen_model_replay(self):
        data = make_training(self.law, 150443, count=7, length=5)
        restored = Law.from_payload(json.loads(json.dumps(self.law.export(), allow_nan=False)))
        self.assertEqual(likelihood(data, self.law), likelihood(data, restored))
        # An injected private state cannot silently enter the public fit path.
        injected = copy.deepcopy(data["sequences"])
        injected[0]["observations"][0]["hidden_state"] = 11
        with self.assertRaises(ValueError):
            likelihood(injected, self.law)

    def test_checkpoint_rejects_corruption_and_different_model(self):
        memory = BeliefMemory(self.law, [3, 1, 0, 2])
        memory.advance(.65)
        memory.observe(0, 1, "refresh")
        checkpoint = memory.checkpoint()
        tampered = copy.deepcopy(checkpoint)
        tampered["beliefs"][0][0] += .1
        with self.assertRaises(ValueError):
            BeliefMemory.restore(self.law, tampered)
        other = Law(theta=(.29, .017))
        with self.assertRaises(ValueError):
            BeliefMemory.restore(other, checkpoint)

    def test_approximate_memory_restores_all_state_and_operation_counts(self):
        for projection in ("factorized", "mean"):
            original = BeliefMemory(self.law, [0, 1, 2, 3], projection=projection)
            original.advance(.45)
            original.observe(1, 0, "refresh")
            restored = BeliefMemory.restore(self.law, json.loads(json.dumps(original.checkpoint())))
            for memory in (original, restored):
                memory.advance(.95)
                memory.write(3, 1)
                memory.observe(2, 2, "read")
            self.assertEqual(original.checkpoint(), restored.checkpoint())


if __name__ == "__main__":
    unittest.main()
