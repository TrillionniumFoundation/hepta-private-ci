"""Unit, independent-oracle, adversarial and resource tests for bounded v4 slice."""
import itertools
import math
import unittest

from finite_portfolio import (
    EMIT_COST, NAMES, InvalidModel, Model, Portfolio, State,
    certainty_equivalent, evaluate_exact, external_loss, fractional_cvar,
    verify_external_loss,
)


class FinitePortfolioTests(unittest.TestCase):
    def test_invalid_parameter_and_evidence_fail_closed(self):
        for kwargs in ({"common_flip": 0}, {"witness_accuracy": 1}, {"gamma": -1},
                       {"report_error": (.1,)}, {"witness_cost": 0},
                       {"probe_accuracy": (.1, .2, float('nan'), .3)}):
            with self.subTest(kwargs=kwargs), self.assertRaises(InvalidModel):
                Model(**kwargs)
        with self.assertRaises(InvalidModel):
            State((0, 1, 1, 0), budget=3)
        with self.assertRaises(InvalidModel):
            Portfolio(Model(), max_states=0)
        with self.assertRaises(InvalidModel):
            certainty_equivalent((1.0, 2.0), (.2, .2), 2)

    def test_immutable_external_utility_and_forgery(self):
        truth = 0b0110
        good = (0, 1, 1, 0)
        bad = (1, 0, 0, 1)
        self.assertEqual(external_loss(good, truth), 0.0)
        self.assertEqual(external_loss(bad, truth), 1.0)
        self.assertTrue(verify_external_loss(good, truth, 0.0))
        with self.assertRaises(InvalidModel):
            verify_external_loss(bad, truth, 0.0)  # Inflated internal NDU score.
        with self.assertRaises(InvalidModel):
            verify_external_loss(good, 16, 0.0)

    def test_ce_translation_invariance_and_risk(self):
        c = certainty_equivalent((-1.0, 1.0), (.5, .5), 2)
        self.assertLess(c, 0)
        self.assertAlmostEqual(certainty_equivalent((1, 3), (.5, .5), 2), c + 2)
        self.assertAlmostEqual(certainty_equivalent((-1, 1), (.5, .5), 0), 0)

    def test_fractional_cvar_not_ceil_tail(self):
        losses = [(0.0, 1/11)] * 10 + [(10.0, 1/11)]
        self.assertAlmostEqual(fractional_cvar(losses), 100 / 11, places=10)

    def test_joint_dependence_is_not_product_marginals(self):
        law = Model(common_flip=.35)
        p = Portfolio(law)
        state = State((0, 0, 0, 0), budget=6)
        joint = p.posterior(state)
        self.assertAlmostEqual(sum(joint), 1.0)
        # Posterior truth coordinates are dependent through the common cause.
        def mean(fn):
            return sum(prob * fn(truth, common) for truth in range(16)
                       for common, prob in enumerate(joint[truth*2:truth*2+2]))
        e1, e2 = mean(lambda t,c: bool(t & 1)), mean(lambda t,c: bool(t & 2))
        e12 = mean(lambda t,c: bool(t & 1) and bool(t & 2))
        self.assertGreater(abs(e12 - e1*e2), 0.01)
        # Equal single-channel marginal corruption can mask a changed common cause.
        e = tuple(law.common_flip * (1-x) + (1-law.common_flip)*x
                  for x in law.report_error)
        naive = Model(common_flip=1e-9, report_error=e)
        p_naive = Portfolio(naive).posterior(state)
        self.assertGreater(max(abs(a-b) for a,b in zip(joint,p_naive)), .02)

    def test_real_feedback_changes_next_modality(self):
        p = Portfolio(Model(common_flip=.18))
        s = State((0,0,0,0), budget=6)
        self.assertEqual(p.solve(s).action, 'video')
        self.assertEqual(p.solve(s.after('video', 0, 1)).action, 'image')
        self.assertEqual(p.solve(s.after('video', 1, 1)).action, 'text')
        with self.assertRaises(InvalidModel):
            s.after('witness', 0, 3)  # Cannot spend reserved four-channel emission budget.
        after = s.after('video', 0, 1)
        with self.assertRaises(InvalidModel):
            after.after('video', 1, 1)  # No repeated paid probe.

    def test_bellman_matches_independent_one_step_enumeration(self):
        model = Model(gamma=1.5)
        p = Portfolio(model)
        state = State((1,0,1,0), budget=5)
        # Oracle independently forms every possible terminal action from 32 truths.
        probs = p.posterior(state)
        def terminal(s):
            posterior = p.posterior(s)
            candidates = []
            for out in itertools.product((0,1), repeat=4):
                losses = tuple(-external_loss(out, t)
                               for t in range(16) for _ in range(2))
                candidates.append(certainty_equivalent(losses, posterior, model.gamma)
                                  - EMIT_COST*model.cost_penalty)
            return max(candidates)
        options = [terminal(state)]
        for action, cost in p.legal(state):
            obs_prob = p.outcome_distribution(state, action)
            children = tuple(terminal(state.after(action, i, cost)) for i in (0,1))
            options.append(certainty_equivalent(children, obs_prob, model.gamma)
                           - cost * model.cost_penalty)
        self.assertAlmostEqual(p.solve(state).value, max(options), places=12)

    def test_dynamic_dominates_static_in_same_declared_utility(self):
        law = Model()
        p = Portfolio(law)
        for reports in itertools.product((0,1), repeat=4):
            root = State(reports, budget=6)
            schedule = p.static_schedule(root)
            val = p._static_value(root, schedule)
            self.assertGreaterEqual(p.solve(root).value + 1e-11, val)

    def test_exact_actual_outputs_budget_and_policy_cost(self):
        law = Model(common_flip=.18)
        for mode in ('dynamic', 'static', 'myopic'):
            p = Portfolio(law)
            r = evaluate_exact(p, law, mode, 6)
            self.assertAlmostEqual(r['terminal_coverage'], 1.0, places=9)
            self.assertLessEqual(r['mean_symbolic_cost_units'], 6.00000001)
            self.assertGreaterEqual(r['mean_symbolic_cost_units'], EMIT_COST)
            self.assertGreaterEqual(r['mean_external_loss'], 0)
            self.assertLessEqual(r['mean_external_loss'], 1)
            self.assertGreaterEqual(r['cvar90_external_loss'], r['mean_external_loss']-1e-12)
        d = evaluate_exact(Portfolio(law), law, 'dynamic', 6)
        s = evaluate_exact(Portfolio(law), law, 'static', 6)
        self.assertLess(d['mean_external_loss'], s['mean_external_loss'])
        # Not claiming universal CVaR dominance; this scenario can trade off tail loss.

    def test_policy_does_not_use_test_truth_and_shift_is_explicit(self):
        assumed = Model(common_flip=.18)
        shifted = Model(common_flip=.36)
        p = Portfolio(assumed)
        nominal = evaluate_exact(p, assumed, 'dynamic', 6)
        out_of_law = evaluate_exact(p, shifted, 'dynamic', 6)
        self.assertGreater(out_of_law['mean_external_loss'], nominal['mean_external_loss'])
        # Observations alone cannot identify the true shared-error regime from a single draw.
        self.assertEqual(p.solve(State((1,1,1,1), budget=6)).action,
                         p.solve(State((1,1,1,1), budget=6)).action)

    def test_state_limit_does_not_silently_change_solution(self):
        p = Portfolio(Model(), max_states=1)
        with self.assertRaisesRegex(InvalidModel, 'planning-state cap'):
            p.solve(State((0,0,0,0), budget=6))


if __name__ == '__main__':
    unittest.main()
