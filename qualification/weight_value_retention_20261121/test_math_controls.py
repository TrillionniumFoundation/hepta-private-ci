"""Synthetic mathematical controls; no checkpoint or task-file access."""
import copy
import unittest
import numpy as np

from data_contract import exact_radius, model_with_head, head, choose
from head_candidates import exact_loss_gradient, conic_subproblem
from value_graph import evaluate, strict_scores


def branching_graph():
    masks = np.array([[1, 1, 0, 0, 1, 1],
                      [1, 0, 0, 0, 1, 1],
                      [1, 0, 0, 0, 1, 1]], dtype=bool)
    terminal = np.zeros((3, 6))
    terminal[1, 4:] = [-0.8, 0.8]
    terminal[2, 4:] = [0.8, -0.8]
    qstar = terminal.copy()
    qstar[0, 1] = 0.7
    return dict(masks=masks, terminal=terminal, qstar=qstar,
                posterior=np.array([0.5, 0.9, 0.1]),
                optimal_values=np.array([0.7, 0.8, 0.8]),
                edges=[[[(0.25, 1, 0.1), (0.75, 2, 0.1)], [], []],
                       [[], [], []], [[], [], []]], order=[0, 1, 2], initial=0)


class MathematicalControls(unittest.TestCase):
    def test_new_policy_occupancy_exposes_loss_hidden_by_old_occupancy(self):
        graph = branching_graph()
        original = np.zeros((3, 6))  # Lowest-index ties select STOP.
        base, original_arrays = evaluate(graph, original)
        scores = original.copy()
        scores[0, 1] = 2
        scores[1:, 4] = 0.8  # Wrong terminal sign in the newly reached first branch.
        scores[1:, 5] = -0.8
        record, arrays = evaluate(graph, scores, original_arrays['occupancy'])
        self.assertAlmostEqual(base['utility'], 0.0, places=14)
        self.assertAlmostEqual(record['utility'], 0.3, places=14)
        self.assertAlmostEqual(record['optimal_regret'], 0.4, places=14)
        self.assertAlmostEqual(record['expected_terminal_reward'], 0.4, places=14)
        self.assertAlmostEqual(record['expected_expense'], 0.1, places=14)
        np.testing.assert_array_equal(arrays['occupancy'], [1.0, 0.25, 0.75])
        self.assertAlmostEqual(record['terminal_gap_contribution'], 0.4, places=14)
        self.assertAlmostEqual(record['continuation_gap_contribution'], 0.0, places=14)
        old_proxy = float(np.sum(original_arrays['occupancy'] * arrays['raw_gap']))
        self.assertEqual(old_proxy, 0.0)
        self.assertLess(abs(record['PDI_residual']), 1e-14)
        self.assertAlmostEqual(record['belief_diagnostics']['own_posterior_MSE_original_occupancy'], 0.0)
        self.assertAlmostEqual(record['belief_diagnostics']['own_posterior_MSE_candidate_occupancy'], 0.08)

    def test_exact_optimal_actions_and_probability_corruption(self):
        graph = branching_graph()
        record, _ = evaluate(graph, graph['qstar'])
        self.assertAlmostEqual(record['utility'], 0.7, places=14)
        self.assertAlmostEqual(record['optimal_regret'], 0.0, places=14)
        corrupted = copy.deepcopy(graph)
        corrupted['edges'][0][0][1] = (0.8, 2, 0.1)
        with self.assertRaises(ArithmeticError):
            evaluate(corrupted, graph['qstar'])
        corrupted = copy.deepcopy(graph)
        corrupted['qstar'][0, 1] = 0.9
        with self.assertRaises(ArithmeticError):
            evaluate(corrupted, graph['qstar'])

    def test_196_gradient_matches_finite_differences_away_from_kinks(self):
        rng = np.random.default_rng(72121023)
        H = rng.normal(0, 0.2, (9, 49))
        H[:, -1] = 1
        anchor = rng.normal(0, 0.07, (4, 49))
        rows = anchor + rng.normal(0, 0.03, (4, 49))
        problem = dict(H=H, masks=np.ones((9, 6), dtype=bool),
                       targets=np.array([0, 1, 2, 3, 4, 5, 1, 4, 5]),
                       margins=rng.uniform(0.6, 1.4, (9, 6)))
        radius = exact_radius(anchor)['numeric_radius']
        objective, gradient = exact_loss_gradient(rows, anchor, problem, radius)
        self.assertTrue(np.isfinite(objective))
        eps = 1e-6
        errors = []
        for index in np.ndindex(rows.shape):
            plus, minus = rows.copy(), rows.copy()
            plus[index] += eps
            minus[index] -= eps
            upper = exact_loss_gradient(plus, anchor, problem, radius)[0]
            lower = exact_loss_gradient(minus, anchor, problem, radius)[0]
            errors.append(abs((upper - lower) / (2 * eps) - gradient[index]))
        self.assertLess(max(errors), 2e-7)

    def test_one_conic_solve_matches_a_known_active_radius_boundary(self):
        # Only the WAIT bias affects the selected state. Its ideal move is one;
        # the registered inner ball is slightly smaller than one.
        anchor = np.zeros((4, 49))
        anchor[0, 0] = 2.0
        H = np.zeros((1, 49))
        H[0, -1] = 1
        problem = dict(H=H, masks=np.array([[1, 1, 0, 0, 1, 1]], dtype=bool),
                       targets=np.array([1]), margins=np.ones((1, 6)))
        proposed, report, _ = conic_subproblem(anchor, anchor, problem, 'Q', 1.0,
                                               1.4, lambda: None)
        self.assertIsNotNone(proposed, report)
        self.assertTrue(report['accepted_numeric_proposal'])
        np.testing.assert_array_equal(proposed[3], anchor[3])
        self.assertTrue(exact_radius(anchor, proposed)['within_shared_ball'])
        self.assertAlmostEqual(proposed[0, -1], 1.0, delta=2e-6)
        scores, _, _ = strict_scores(proposed, H)
        self.assertEqual(int(np.argmax(scores[0])), 1)

    def test_shared_exact_ball_signed_zero_and_immutable_copy(self):
        rows = np.zeros((4, 49))
        rows[0, 0] = 1.0
        changed = rows.copy()
        changed[0, 0] = 1.5
        self.assertTrue(exact_radius(rows, changed)['within_shared_ball'])
        changed[0, 0] = np.nextafter(1.5, np.inf)
        self.assertFalse(exact_radius(rows, changed)['within_shared_ball'])
        changed = rows.copy()
        changed[0, 0] += 0.4
        changed[3, -1] = 0.4
        self.assertFalse(exact_radius(rows, changed)['within_shared_ball'])
        base = dict(network=dict(w2=rows[:, :48].tolist(), b2=rows[:, 48].tolist()),
                    semantic_marker=dict(target_tick=6, protected=[1, 2, 3]))
        frozen = copy.deepcopy(base)
        changed = rows.copy()
        changed[0, -1] = 0.25
        model, _ = model_with_head(base, changed, 'Q')
        self.assertEqual(base, frozen)
        np.testing.assert_array_equal(head(model), changed)
        changed[3, -1] = -0.0
        with self.assertRaises(ArithmeticError):
            model_with_head(base, changed, 'Q')

    def test_keep_first_selection_rejects_unknown_and_nonfinite(self):
        values = {'KEEP': 0.2, 'Q_1': 0.2, 'B_1': None, 'G_1': float('nan')}
        self.assertEqual(choose(values, ['Q_1', 'B_1', 'G_1']), 'KEEP')
        values['G_1'] = 0.25
        self.assertEqual(choose(values, ['Q_1', 'B_1', 'G_1']), 'G_1')
        with self.assertRaises(ValueError):
            choose({'KEEP': float('nan')}, [])


if __name__ == '__main__':
    unittest.main()
