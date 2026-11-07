"""Real original-TRAIN semantic checks, before any new candidate or holdout."""
import copy
from pathlib import Path
import sys
import unittest

import numpy as np

UPSTREAM = Path(__file__).resolve().parent.parent / "wsp_native_value_20261105/value_edit"
sys.path.insert(0, str(UPSTREAM))
from artifact_io import read
from vendor import planning as p
from evaluate import ControlPolicy, history
from guard import model_identity, protected_identity


class FrozenExecutionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ctx = p.load_context(UPSTREAM / "vendor/frozen_joint")
        cls.model = read(UPSTREAM / "inputs/fit_11_C.json.gz")
        cls.policy = cls.ctx.NumpyPolicy(cls.model)
        cls.theta = cls.ctx.head(cls.model)
        cls.public = read(UPSTREAM / "inputs/fit_11_TRAIN_PUBLICS.json.gz")[0]

    def test_literal_stored_head_matches_checked_execution(self):
        state = self.ctx.initial(self.public)
        checked = ControlPolicy(self.ctx, self.public, self.policy, None, "C")
        literal = ControlPolicy(self.ctx, self.public, self.policy, None, "L")
        first, first_belief = checked.scores(state, self.theta, "head")
        second, second_belief = literal.scores(state, self.theta, "head")
        np.testing.assert_array_equal(first, second)
        self.assertEqual(first_belief, second_belief)

    def test_myopic_never_calls_recursive_bellman(self):
        policy = ControlPolicy(self.ctx, self.public, self.policy, None, "MYOPIC")
        def forbidden(*_args):
            raise AssertionError("recursive Bellman was invoked by cheap control")
        policy.own.q = forbidden
        scores, probability = policy.scores(self.ctx.initial(self.public), self.theta, "head")
        self.assertTrue(np.isfinite(scores).all())
        self.assertTrue(0 <= probability <= 1)

    def test_tensor_shape_and_protected_identity_reject_mutation(self):
        changed = copy.deepcopy(self.model)
        changed["network"]["w1"][0][0] += .01
        self.assertNotEqual(protected_identity(changed), protected_identity(self.model))
        changed["network"]["w2"][0].pop()
        with self.assertRaises(ValueError):
            model_identity(changed)

    def test_exposed_previous_confirmation_is_in_history(self):
        known, _, report = history(UPSTREAM)
        self.assertEqual(len(known), 2896)
        self.assertEqual(report["known_unique_schedules"], len(known))


if __name__ == "__main__":
    unittest.main()
