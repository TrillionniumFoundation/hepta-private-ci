"""Adversarial small-field learning vs exact E12 contraction and frozen baselines."""

from dataclasses import replace
from fractions import Fraction as Q
from math import nan
from unittest import TestCase
from unittest.mock import patch

from e12_nonlinear_cert import Law, solve
from e12_independent_audit import reference
from e12_local_cell_solver import _paths
from e12_continuation_field import (
    TrainingRow, FrozenHead, features, fit_head, initial_y, predict,
    solve_warm, training_rows, DIM, WIDTH, EPOCHS,
)


def toy_rows():
    rows = []
    for k in (-3, -1, 1, 3):
        law = Law(depth=3, x0=str(Q(k, 4)))
        result = solve(law)
        y = tuple(Q(node.y) for node in result.trace.states[:7])
        rows.extend(training_rows(law, y))
    return tuple(rows)


class ContinuationFieldTests(TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rows = toy_rows()
        cls.head = fit_head(cls.rows, 'neural')

    def test_neural_weights_physically_updated_and_shape(self):
        model = self.head
        self.assertEqual(len(model.hidden), WIDTH)
        self.assertEqual(len(model.hidden[0]), DIM)
        self.assertEqual(model.updates, EPOCHS * len(self.rows))
        self.assertGreater(model.fit_cpu_ns, 0)
        self.assertTrue(any(abs(v) > .02 for v in model.readout))
        model.validate()
        self.assertEqual(model.authority, 'DENY_ALL')

    def test_constant_and_linear_do_not_forge_neural_capacity(self):
        for kind in ('constant', 'linear'):
            m = fit_head(self.rows, kind)
            self.assertEqual(m.kind, kind)
            self.assertEqual(m.train_rows, len(self.rows))
            m.validate()
            self.assertGreater(m.fit_cpu_ns, 0)
        self.assertEqual(len(fit_head(self.rows, 'constant').hidden), 0)

    def test_fields_observe_only_past_public_prefix(self):
        law = Law(depth=3, x0='1/2')
        self.assertNotEqual(features(law, 'L'), features(law, 'R'))
        self.assertNotEqual(features(law, 'LL'), features(law, 'LR'))
        self.assertEqual(features(law, 'LR'), features(law, 'RL'))
        for bad in ('LLL', 'X', 'll', 'RLRR'):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                features(law, bad)

    def test_neural_heads_produce_bounded_q16_initialization(self):
        for a in ('0', '1/3'):
            law = Law(depth=3, a=a)
            guess = initial_y(law, self.head)
            self.assertEqual(len(guess), 7)
            self.assertTrue(all(abs(v) <= law.values()['M'] and
                                (v * (1 << 16)).denominator == 1 for v in guess))
            self.assertTrue(all(abs(predict(self.head, features(law, path))) <= 1
                                for path in _paths(law.depth)[0]))

    def test_warm_local_iteration_globally_certified_on_six_laws(self):
        for depth in (1, 2, 3):
            for a in ('0', '1/3'):
                with self.subTest(depth=depth, a=a):
                    law = Law(depth=depth, a=a, x0='7/10')
                    attempt = solve_warm(law, initial_y(law, self.head))
                    p = law.values()
                    y = tuple(Q(s.y) for s in attempt.trace.states[:(1 << depth) - 1])
                    reference_x, reference_u, mapped = reference(law, y)
                    residual = max(abs(a - b) for a, b in zip(y, mapped))
                    self.assertEqual(str(residual), attempt.residual)
                    self.assertEqual(str(residual / (1 - p['q'])),
                                     attempt.rigorous_error_bound)
                    self.assertLessEqual(Q(attempt.rigorous_error_bound), Q(1, 10000))
                    self.assertEqual(attempt.policy, 'DENY_ALL')
                    self.assertEqual(attempt.node_updates, attempt.iterations * ((1 << depth) - 1) * 2)
                    original = solve(law)
                    self.assertLessEqual(abs(y[0] - Q(original.trace.states[0].y)), Q(1, 5000))

    def test_exact_zero_initializer_matches_existing_oracle_free_solver(self):
        from e12_local_cell_solver import solve_local_cells
        law = Law(depth=3, a='1/3')
        r = solve_warm(law, initial_y(law, None))
        cold = solve_local_cells(law)
        self.assertEqual(r.trace, cold.result.trace)
        self.assertEqual(r.iterations, cold.result.evaluations)

    def test_inference_does_not_call_teacher_or_global_operator(self):
        law = Law(depth=3, x0='7/10')
        with patch('e12_nonlinear_cert.solve', side_effect=RuntimeError('leak')), \
             patch('e12_nonlinear_cert.operator', side_effect=RuntimeError('leak')):
            ans = solve_warm(law, initial_y(law, self.head))
        self.assertLessEqual(Q(ans.rigorous_error_bound), Q(1, 10000))

    def test_invalid_features_weights_and_training_rows_rejected(self):
        with self.assertRaises(ValueError):
            fit_head((), 'neural')
        with self.assertRaises(ValueError):
            fit_head(self.rows, 'invalid')
        with self.assertRaises(ValueError):
            fit_head((TrainingRow((nan,) * DIM, 0.0),), 'neural')
        with self.assertRaises(ValueError):
            predict(self.head, (0.0,))
        with self.assertRaises(ValueError):
            predict(replace(self.head, readout=(nan,) + self.head.readout[1:]),
                    self.rows[0].features)
        with self.assertRaises(ValueError):
            self.head.validate() if self.head.authority != 'DENY_ALL' else replace(
                self.head, authority='ALLOW').validate()

    def test_reject_unphysical_start_and_global_noncontraction(self):
        law = Law()
        for guess in ((Q(2),) * 7, (Q(0),) * 6, (0,) * 7):
            with self.subTest(guess=guess), self.assertRaises(ValueError):
                solve_warm(law, guess)
        with self.assertRaises(ValueError):
            solve_warm(Law(a='1', g='1', beta='1', horizon='2'), (Q(0),) * 7)

    def test_exhaustion_and_no_uncertified_completion(self):
        law = Law(depth=3, a='1/3')
        with self.assertRaises(ValueError):
            solve_warm(law, (Q(0),) * 7, max_calls=1)
        with self.assertRaises(ValueError):
            solve_warm(law, (Q(0),) * 7, max_calls=True)


if __name__ == '__main__':
    import unittest
    unittest.main()
