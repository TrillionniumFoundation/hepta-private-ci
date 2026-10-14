"""Round-2 math/mechanism tests; real optimization tests do not establish efficacy."""
import unittest
from unittest.mock import patch

import numpy as np
import torch
from torch.func import jacfwd

from models import StateStem, assign, vector
from problem import decimal_oracle, make_world, terminals
from run import fit, predictions, residual
from structured import (StructuredStem, invariant_probe, new_terminals, panel_specs,
                        panel_world, priced_decisions)


class StructureTests(unittest.TestCase):
    def setUp(self):
        self.world = make_world()
        self.w = self.world.tensor()
        self.g = torch.tensor(terminals(self.world, 'train'), dtype=torch.float64)

    def test_01_same_family_initial_bytes_and_count(self):
        for seed in (11, 23, 47):
            b, c = StructuredStem(seed), StructuredStem(seed)
            np.testing.assert_array_equal(vector(b), vector(c))
            self.assertEqual(vector(b).size, vector(StateStem(seed)).size)

    def test_02_all_trainable_groups_have_nonzero_gradient(self):
        model = StructuredStem()
        residual(model, self.w, self.g, 3).square().sum().backward()
        for p in model.parameters():
            self.assertTrue(torch.isfinite(p.grad).all())
            self.assertGreater(float(p.grad.abs().sum()), 0)

    def test_03_full_jacobian_matches_finite_difference(self):
        model = StructuredStem()
        theta = torch.tensor(vector(model))
        j = jacfwd(lambda z: residual(model, self.w, self.g, 3, z))(theta).detach().numpy()
        for k in (0, 7, 33, 64):
            e = torch.zeros_like(theta)
            e[k] = 1e-5
            d = (residual(model, self.w, self.g, 3, theta + e) -
                 residual(model, self.w, self.g, 3, theta - e)).detach().numpy() / 2e-5
            np.testing.assert_allclose(j[:, k], d, rtol=2e-4, atol=2e-10)

    def test_04_chain_adjoint_equals_full_jacobian(self):
        model = StructuredStem()
        theta = torch.tensor(vector(model), requires_grad=True)
        r = residual(model, self.w, self.g, 3, theta)
        gradient = torch.autograd.grad(r.square().sum(), theta)[0]
        j = jacfwd(lambda z: residual(model, self.w, self.g, 3, z))(theta.detach())
        np.testing.assert_allclose(gradient.detach(), (2 * j.T @ r.detach()).detach(), atol=1e-12)

    def test_05_zero_risk_is_exact_before_training(self):
        world = panel_world(2, 'joint')
        g = new_terminals(world, 'indicator')
        for seed in (11, 23, 47):
            m = StructuredStem(seed)
            for scale in (1, 10, -10):
                assign(m, np.clip(vector(m) * scale, -12, 12))
                pred = predictions(m, 'B', world.tensor(), g, 8)[-1]
                exact = g @ np.linalg.matrix_power(world.kernel(), 8).T
                np.testing.assert_allclose(pred, exact, atol=2e-14, rtol=0)
                self.assertGreaterEqual(float(pred.min()), 0)
                self.assertLessEqual(float(pred.max()), 1)

    def test_06_real_arbitrary_weight_structure_probes(self):
        rng = np.random.default_rng(39)
        m = StructuredStem()
        for _ in range(4):
            assign(m, rng.uniform(-12, 12, 65))
            report = invariant_probe(m, self.world)
            for key, value in report.items():
                if key != 'numerical_probes_only':
                    self.assertLess(value, 2e-13, key)

    def test_07_translation_for_several_shifts(self):
        m = StructuredStem()
        with torch.no_grad():
            for shift in (-2.0, -0.2, 3.0):
                np.testing.assert_allclose(m(self.g + shift, self.w),
                                          m(self.g, self.w) + self.world.discount * shift, atol=2e-14)

    def test_08_certainty_outcome_exchange_symmetry(self):
        a, b, p = self.g[:, self.w['left']], self.g[:, self.w['right']], self.w['p']
        np.testing.assert_allclose(StructuredStem.certainty(a, b, p, self.w['risk']),
                                  StructuredStem.certainty(b, a, 1 - p, self.w['risk']), atol=1e-14)

    def test_09_small_risk_stability(self):
        a, b, p = self.g[:, self.w['left']], self.g[:, self.w['right']], self.w['p']
        tiny = torch.full_like(p, 1e-12)
        np.testing.assert_allclose(StructuredStem.certainty(a, b, p, tiny), p * a + (1 - p) * b,
                                  atol=1e-12, rtol=0)

    def test_10_basis_is_not_the_exact_target(self):
        m = StructuredStem()
        with torch.no_grad():
            m.net[2].weight.zero_()
            m.net[2].bias.zero_()
        pred = predictions(m, 'B', self.w, self.g.numpy(), 3)
        exact = decimal_oracle(self.world, self.g.numpy(), 3)
        self.assertGreater(float(np.max(np.abs(pred - exact))), 1e-5)

    def test_11_new_terminal_laws_are_disjoint(self):
        def identities(a):
            return {row.tobytes() for row in a}
        train = identities(terminals(self.world, 'train'))
        old_test = identities(terminals(self.world, 'transfer'))
        for family in ('uniform', 'composed', 'indicator'):
            fresh = identities(new_terminals(self.world, family))
            self.assertFalse(train & fresh)
            self.assertFalse(old_test & fresh)
            self.assertGreaterEqual(len(fresh), 30)  # Bernoulli terminal collisions are possible.

    def test_12_composed_family_is_bounded_and_nondegenerate(self):
        g = new_terminals(self.world, 'composed')
        self.assertLessEqual(float(np.abs(g).max()), 0.8 + 1e-15)
        self.assertGreater(float(np.std(g)), 0.1)

    def test_13_only_named_coefficient_changes(self):
        names = ('left', 'right', 'probability', 'risk', 'cost', 'discount')
        for intervention, changed in [('risk', 'risk'), ('cost', 'cost'), ('discount', 'discount')]:
            world = panel_world(2, intervention)
            for name in names:
                a, b = getattr(self.world, name), getattr(world, name)
                self.assertEqual(np.array_equal(a, b), name != changed, (intervention, name))
            np.testing.assert_array_equal(new_terminals(world), new_terminals(self.world))

    def test_14_indicator_changes_no_world_coefficients(self):
        world = panel_world(2, 'base')
        np.testing.assert_array_equal(world.kernel(), self.world.kernel())
        self.assertEqual(set(np.unique(new_terminals(world, 'indicator'))), {0.0, 1.0})

    def test_15_changed_kernel_is_known_not_hidden(self):
        world = panel_world(2, 'kernel')
        self.assertFalse(np.array_equal(world.left, self.world.left))
        np.testing.assert_array_equal(world.probability, self.world.probability)
        np.testing.assert_array_equal(world.risk, self.world.risk)

    def test_16_higher_dimension_no_weight_change(self):
        model = StructuredStem()
        before = vector(model)
        world = make_world(6)
        result = predictions(model, 'B', world.tensor(), new_terminals(world), 3)
        self.assertEqual(result.shape, (4, 32, 192))
        np.testing.assert_array_equal(before, vector(model))

    def test_17_initial_choice_regret_is_actual_cost_difference(self):
        truth = np.array([[[0.0], [0.0]], [[0.0], [0.2]]])
        pred = truth.copy()
        pred[-1, 0, 0] = 0.3
        bad = priced_decisions(pred, truth)
        good = priced_decisions(truth, truth)
        self.assertEqual(good['priced_decision_regret'], 0)
        self.assertGreater(bad['priced_decision_regret'], 0)
        self.assertLess(bad['priced_decision_accuracy'], 1)

    def test_18_new_panel_order_and_original_law_unchanged(self):
        self.assertEqual(len(set(p[0] for p in panel_specs())), len(panel_specs()))
        np.testing.assert_array_equal(terminals(self.world, 'train'), self.g.numpy())

    def test_19_invalid_intervention_refused(self):
        with self.assertRaises(ValueError):
            panel_world(2, 'hidden_drift')
        with self.assertRaises(ValueError):
            new_terminals(self.world, 'oracle_selected')

    def test_20_actual_solve_no_oracle_calls(self):
        model = StructuredStem()
        before = float(residual(model, self.w, self.g, 2).square().sum().detach())
        with patch('run.decimal_oracle', side_effect=AssertionError('oracle in optimizer')):
            report = fit(model, 'C', self.w, self.g, 2, 1.5)
        after = float(residual(model, self.w, self.g, 2).square().sum().detach())
        self.assertLess(after, before)
        self.assertGreater(report['counts']['jacobian_evaluations'], 0)
        self.assertNotEqual(report['initial_weights_sha256'], report['final_weights_sha256'])


if __name__ == '__main__':
    unittest.main(verbosity=2)
