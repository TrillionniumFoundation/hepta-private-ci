"""Independent adjoint, optimizer reconstruction and final-score rejection tests."""

import json
from pathlib import Path
import tempfile
import unittest

import numpy as np

from cell_field_retention_audit import adam_transition, plan_value_gradient
from cell_field_retention_score_audit import audit_evaluation
from cell_field_state import CellTrainingState
from cell_learning_models import NumpyCellHead
from test_cell_field_retention_evaluate import Fixture, write


class IndependentRetentionAuditTests(unittest.TestCase):
    def test_adjoint_gradient_matches_finite_difference_for_hinge_and_symmetric(self):
        rng = np.random.default_rng(562)
        horizon, dim, actions = 4, 3, 2
        policy = {"F": np.tile(np.eye(dim), (horizon, 1, 1)) + rng.normal(0, 0.02, (horizon, dim, dim)),
                  "D": rng.normal(0, 0.05, (horizon, dim, actions)),
                  "charged": rng.normal(0, 0.5, (horizon + 1, 2, dim)),
                  "target": rng.normal(0, 0.2, (horizon + 1, 2))}
        observed, control = rng.normal(size=dim), rng.normal(0, 0.1, (horizon - 1, actions))
        for symmetric in (False, True):
            value, gradient, fields = plan_value_gradient(policy, 1, observed, control, 0.02, 0.1, symmetric=symmetric)
            numeric = np.zeros_like(control)
            for index in np.ndindex(control.shape):
                plus, minus = control.copy(), control.copy()
                plus[index] += 1e-6; minus[index] -= 1e-6
                numeric[index] = (plan_value_gradient(policy, 1, observed, plus, 0.02, 0.1, symmetric=symmetric)[0]
                                  - plan_value_gradient(policy, 1, observed, minus, 0.02, 0.1, symmetric=symmetric)[0]) / 2e-6
            np.testing.assert_allclose(gradient, numeric, atol=2e-10, rtol=2e-7)
            self.assertTrue(np.isfinite(value))
            self.assertEqual(fields.shape, (horizon, 2))

    def test_independent_adam_matches_existing_head_with_active_gradient_clipping(self):
        rng = np.random.default_rng(83)
        x, y = rng.normal(size=(16, 3)), np.tile(np.arange(4), 4)
        protocol = {"learning_rate": 0.02, "l2": 0.001, "beta1": 0.9, "beta2": 0.999,
                    "epsilon": 1e-8, "gradient_clip": 0.02, "sampler": "full_batch"}
        for mode in ("linear", "gated"):
            state = CellTrainingState(NumpyCellHead(3, 4, mode, seed=7), bindings={"test": "audit"}, protocol=protocol)
            for completed in range(5):
                independent = adam_transition(state.vector(), mode, x, y, completed, protocol)
                actual = state.transition_vector(state.vector(), completed, x, y)
                np.testing.assert_allclose(independent, actual, atol=2e-14, rtol=2e-14)
                state.set_vector(actual)

    def test_independent_final_scoring_reproduces_complete_family_and_rejects_tampering(self):
        with tempfile.TemporaryDirectory() as temporary:
            fixture = Fixture(temporary)
            result = fixture.run()
            path = fixture.output / "evaluation.json"
            audit = audit_evaluation(fixture.root, fixture.data, fixture.protocol, path)
            self.assertEqual(audit["secondary_intervals_recomputed"], 144)
            self.assertEqual(audit["primary_intervals_recomputed"], 8)
            self.assertLessEqual(audit["maximum_absolute_error"], 1e-14)
            for defect in ("interval", "decision", "missing-comparison"):
                bad = json.loads(json.dumps(result))
                if defect == "interval": bad["primary_contrasts"][0]["bonferroni_percentile_interval"][1] += 0.1
                elif defect == "decision": bad["decisions"][0]["all_primary_criteria_met"] = False
                else: bad["contrasts"].pop()
                write(path, bad)
                with self.assertRaises(ValueError):
                    audit_evaluation(fixture.root, fixture.data, fixture.protocol, path)


if __name__ == "__main__":
    unittest.main()
