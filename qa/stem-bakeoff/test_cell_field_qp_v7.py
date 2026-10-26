"""Independent primal optima, risk derivatives and valid dual certificates."""

from types import SimpleNamespace
import unittest
from unittest.mock import patch

import numpy as np
from scipy.optimize import minimize

from cell_field_qp_v7 import objective_weights, solve_terminal


class PanelQuadraticTests(unittest.TestCase):
    def test_robust_risk_weights_are_its_actual_loss_derivatives(self):
        losses = np.array([1.1, 1.4, .7, 1.2, 1.5, .8, 1.3, 1.])
        for dispersion in (0., .5):
            value, weights = objective_weights(losses, .25, dispersion)
            def independent(x):
                spread = np.sqrt(np.mean((x[:4]-x[:4].mean())**2)+1e-12)
                return x[:4].mean()+dispersion*spread+.25*x[4:].mean()
            self.assertAlmostEqual(value, independent(losses), places=14)
            derivative = [(independent(losses+1e-6*d)-independent(losses-1e-6*d))/2e-6
                for d in np.eye(8)]
            np.testing.assert_allclose(weights, derivative, rtol=1e-8, atol=1e-10)

    def test_dual_matches_independent_primal_with_box_and_two_active_panels(self):
        rng = np.random.default_rng(442)
        for h, p in ((1, 6), (3, 4), (8, 3)):
            r, bound, weight = .2, .4, .25
            normal = rng.normal(0., .05, (4, h*p))
            optimum = rng.uniform(-.2, .2, h*p)
            optimum[0] = bound
            multipliers = np.array([.4, .6, 0., 0.])
            c = -r*optimum-normal.T@multipliers
            c[0] -= .2
            q = normal@optimum+np.array([0., 0., .1, .2])
            maps = np.empty((h, 8, p))
            maps[:, :4] = (c-weight*normal.mean(axis=0)).reshape(h, 1, p)
            maps[:, 4:] = normal.reshape(4, h, p).transpose(1, 0, 2)
            nominal = rng.uniform(-.1, .1, (h, p))
            baseline = np.array([1.1, 1.4, .7, 1.2, 1., 1.1, 1.2, 1.3])
            anchors = baseline[4:]+q-normal@nominal.ravel()
            result = solve_terminal(maps, baseline, anchors, nominal, dt=.5,
                effort_price=.4, action_bound=bound*np.sqrt(p), old_weight=weight,
                current_dispersion=.5)
            self.assertEqual(result["record"]["status"], "qualified", result["record"])
            objective = lambda u: float(c@u+.5*r*(u@u))
            primal = minimize(objective, np.zeros(h*p), jac=lambda u: c+r*u,
                constraints=[{"type": "ineq", "fun": lambda u: q-normal@u,
                    "jac": lambda u: -normal}], bounds=[(-bound, bound)]*(h*p),
                method="SLSQP", options={"ftol": 1e-13, "maxiter": 1000})
            self.assertTrue(primal.success, primal.message)
            actions = result["actions"].ravel()
            np.testing.assert_allclose(actions, primal.x, rtol=2e-6, atol=2e-7)
            np.testing.assert_allclose(actions, optimum, rtol=2e-7, atol=2e-8)
            self.assertAlmostEqual(objective(actions), objective(primal.x), places=11)
            self.assertTrue(np.all(np.asarray(result["record"]["dual_multipliers"]) >= 0))
            predicted = baseline+np.einsum("kqp,kp->q", maps, result["actions"]-nominal)
            np.testing.assert_array_equal(predicted, result["record"]["predicted_terminal_losses"])
            self.assertLessEqual(float(np.max(predicted[4:]-anchors)), 1e-10)

    def test_joint_infeasibility_requires_a_verified_box_separating_mixture(self):
        maps = np.zeros((1, 8, 1))
        maps[0, 4:, 0] = [1., -1., 0., 0.]
        q = np.array([-.5, -.5, 1., 1.])
        result = solve_terminal(maps, np.zeros(8), q, np.zeros((1, 1)), action_bound=1.)
        self.assertEqual(result["record"]["status"], "tangent_infeasible")
        self.assertIsNone(result["actions"])
        mixture = np.asarray(result["record"]["separating_mixture"])
        self.assertTrue(np.all(mixture >= 0))
        self.assertAlmostEqual(float(mixture.sum()), 1., places=12)
        lower = -abs(float(mixture@maps[0, 4:, 0]))-float(mixture@q)
        self.assertGreater(lower, 1e-10)
        self.assertEqual(lower, result["record"]["verified_box_infeasibility_lower_bound"])
        q[:2] = 0.
        boundary = solve_terminal(maps, np.zeros(8), q, np.zeros((1, 1)), action_bound=1.)
        self.assertEqual(boundary["record"]["status"], "qualified")
        np.testing.assert_array_equal(boundary["actions"], [[0.]])

    def test_negative_dual_cannot_pass_even_when_other_kkt_residuals_vanish(self):
        maps = np.zeros((1, 8, 2))
        maps[0, :4] = [-1., -.1]
        maps[0, 4:] = [[1., 0.], [0., 1.], [1., 1.], [-1., 0.]]
        anchors = 1.+np.array([.5, .5, .5, 1.])
        invalid = SimpleNamespace(x=np.array([0., -1.4, np.sqrt(2.), 0.]),
            success=True, nit=1, nfev=1)
        with patch("cell_field_qp_v7.minimize", return_value=invalid):
            result = solve_terminal(maps, np.ones(8), anchors, np.zeros((1, 2)),
                dt=1., effort_price=1., action_bound=np.sqrt(2.))
        self.assertEqual(result["record"]["status"], "unresolved")
        self.assertIsNone(result["actions"])
        self.assertTrue(all(not row["dual_candidate_feasible"] for row in result["record"]["attempts"]))

    def test_underflowed_regularization_fails_before_any_certificate(self):
        with self.assertRaisesRegex(ValueError, "finite and positive"):
            solve_terminal(np.zeros((1, 8, 1)), np.zeros(8), np.zeros(4),
                np.zeros((1, 1)), dt=1e-308, effort_price=1e-308)


if __name__ == "__main__":
    unittest.main()
