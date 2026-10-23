"""Adversarial independent-outcome and finite Bellman reference for joint control."""
from fractions import Fraction
import math
import unittest

from portfolio import (
    Allocation, Config, SHOCK_PROBS, State, actions, advance,
    charge, decode_all, decoded_external_loss,
)
from information_acquisition import (
    WITNESS_ACCURACY, all_outputs, map_label, posterior,
    witness_probability,
)
from joint_evidence_generation import (
    EMIT, QUERY, SHOCK_EXACT, JointController, JointState,
    admitted_actions, full_outcome_audit, generation_successor,
    independent_fixture_score, materialize_four, mode_state,
    query_successor, terminal_value,
)


class JointEvidenceGenerationTests(unittest.TestCase):
    def setUp(self):
        self.cfg = Config(horizon=2, cost_shadow_price=0.05,
                          risk_aversion=1, activation_cost=1)
        self.start = (2, 2, 0, 0)

    def test_evidence_and_generation_compete_in_one_action_set(self):
        hard = mode_state('hard', self.start, 10)
        easy = mode_state('easy', self.start, 10)
        ctl = JointController(self.cfg)
        self.assertEqual(ctl.solve(hard)[0], QUERY)
        self.assertEqual(ctl.solve(easy)[0], Allocation((0, 0, 1, 1)))
        # Querying uses exactly one physical unit and one generation decision;
        # a later allocation and mandatory four-emission reserve remain payable.
        queried = query_successor(hard, self.cfg, 0)
        self.assertEqual(queried.generation.remaining, 9)
        self.assertEqual(queried.generation.step, 1)
        self.assertEqual(queried.p_zero, Fraction(49, 50))
        self.assertEqual(ctl.solve(queried)[0], Allocation((0, 0, 1, 1)))
        self.assertNotIn(QUERY, admitted_actions(queried, self.cfg))

    def test_full_decoded_terminal_law_matches_recursion(self):
        for risk in (0, .5, 1, 3):
            cfg = Config(horizon=2, cost_shadow_price=.05, risk_aversion=risk)
            for mode in ('easy', 'hard'):
                with self.subTest(risk=risk, mode=mode):
                    state = mode_state(mode, self.start, 10)
                    ctl = JointController(cfg)
                    exact = ctl.solve(state)[1]
                    audit = full_outcome_audit(state, cfg, lambda s: ctl.solve(s)[0])
                    self.assertAlmostEqual(audit['recursive_fullpath_utility'], exact,
                                           places=9)
                    self.assertTrue(audit['four_outputs_emitted'])
                    self.assertEqual(audit['budget_violations'], 0)
                    self.assertLessEqual(audit['mean_modeled_cost'], 10)
                    self.assertGreater(audit['distinct_decoded_hashes'], 0)

    def test_no_query_is_a_nested_subset_not_a_strong_baseline(self):
        state = mode_state('hard', self.start, 10)
        full = JointController(self.cfg)
        no_query = JointController(self.cfg, allow_query=False)
        a = full_outcome_audit(state, self.cfg, lambda s: full.solve(s)[0])
        b = full_outcome_audit(state, self.cfg, lambda s: no_query.solve(s)[0])
        self.assertGreater(a['recursive_fullpath_utility'],
                           b['recursive_fullpath_utility'] + .1)
        self.assertGreater(a['query_probability'], 0)
        self.assertEqual(b['query_probability'], 0)
        # This proves an ablation mechanism only, not superiority over
        # all external static/MoE/online-control baselines.

    def test_shared_wrong_modal_agreement_is_not_factual_accuracy(self):
        easy = mode_state('easy', (2, 2, 2, 2), 4)
        raw = materialize_four(easy)
        self.assertEqual(set(raw), {'text', 'audio', 'image', 'video'})
        self.assertTrue(all(raw[m]['claim'] == all_outputs(0)[m] for m in raw))
        self.assertEqual(independent_fixture_score(raw, truth=0, cfg=self.cfg), 0)
        self.assertEqual(independent_fixture_score(raw, truth=1, cfg=self.cfg), 4)
        # Refinement alone never changes posterior or the repeated wrong fact.
        cfg = Config(horizon=1)
        s = mode_state('easy', (2, 2, 0, 0), 12)
        changed = generation_successor(s, Allocation((0, 0, 1, 1)), 2, cfg)
        self.assertEqual(changed.p_zero, s.p_zero)
        self.assertEqual(map_label(changed.p_zero), 0)
        self.assertGreaterEqual(independent_fixture_score(
            materialize_four(changed), truth=1, cfg=cfg), 4)

    def test_query_cannot_spend_mandatory_emission_reserve(self):
        cfg = Config(horizon=2, risk_aversion=1)
        state = mode_state('hard', (2, 2, 2, 2), cfg.emission_reserve)
        self.assertEqual(JointController(cfg).solve(state)[0], EMIT)
        self.assertEqual(admitted_actions(state, cfg), (EMIT,))
        with self.assertRaises(ValueError):
            query_successor(state, cfg, 0)
        self.assertEqual(full_outcome_audit(state, cfg,
                         lambda s: JointController(cfg).solve(s)[0])['mean_modeled_cost'], 4)

    def test_allocation_response_changes_after_real_observed_shock(self):
        # With zero entropic-risk parameter the hard case first improves
        # image/video. A low observed gain leads to another refinement,
        # whereas a higher gain makes paid evidence the next action.
        cfg = Config(horizon=2, risk_aversion=0, cost_shadow_price=.05)
        s = mode_state('hard', self.start, 10)
        ctl = JointController(cfg)
        a = ctl.solve(s)[0]
        self.assertEqual(a, Allocation((0, 0, 1, 1)))
        weak = generation_successor(s, a, 0, cfg)
        strong = generation_successor(s, a, 2, cfg)
        self.assertEqual(ctl.solve(weak)[0], a)
        self.assertEqual(ctl.solve(strong)[0], QUERY)
        self.assertEqual(s.p_zero, strong.p_zero)

    def test_fraction_risk_neutral_oracle_independent_of_value_solver(self):
        # Completely separate exact rational backward induction; neither
        # terminal_value nor JointController.solve is called in the oracle.
        cfg = Config(horizon=2, risk_aversion=0, cost_shadow_price=.25)
        price = Fraction(1, 4)
        def oracle(s):
            predicted = 0 if s.p_zero >= Fraction(1, 2) else 1
            qual = decoded_external_loss(decode_all(s.generation), cfg.sync_penalty)
            expected_wrong = 1 - s.p_zero if predicted == 0 else s.p_zero
            best = -Fraction(qual) - 4 * expected_wrong - price * 4
            if s.generation.step == cfg.horizon:
                return best
            if not s.witness_seen and s.generation.remaining >= 5:
                child = Fraction(0)
                for observation in (0, 1):
                    p_obs = witness_probability(s.p_zero, observation)
                    gen = State(s.generation.levels, s.generation.remaining - 1,
                                s.generation.step + 1, s.generation.active_mask)
                    child += p_obs * oracle(JointState(gen, posterior(s.p_zero,
                                                               observation), True))
                best = max(best, -price + child)
            for allocation in actions(s.generation, cfg)[1:]:
                paid = charge(s.generation, allocation, cfg)
                continuation = Fraction(0)
                for shock, p_shock in enumerate(SHOCK_EXACT):
                    next_gen = advance(s.generation, allocation, shock, cfg)
                    continuation += p_shock * oracle(JointState(
                        next_gen, s.p_zero, s.witness_seen))
                best = max(best, -price * paid + continuation)
            return best

        for mode in ('easy', 'hard'):
            for budget in (7, 9, 10):
                with self.subTest(mode=mode, budget=budget):
                    state = mode_state(mode, self.start, budget)
                    self.assertAlmostEqual(JointController(cfg).solve(state)[1],
                                           float(oracle(state)), places=11)

    def test_deny_invalid_actions_beliefs_and_witness_provenance(self):
        cfg = self.cfg
        with self.assertRaises(ValueError):
            JointState(State((0, 0, 0, 0), 8), .5)
        with self.assertRaises(ValueError):
            JointState(State((0, 0, 0, 0), 8), Fraction(1, 2), 0)
        with self.assertRaises(ValueError):
            JointController(cfg, query_cost=0)
        with self.assertRaises(ValueError):
            admitted_actions(mode_state('hard', self.start, 10), cfg, query_cost=.5)
        with self.assertRaises(ValueError):
            query_successor(mode_state('hard', self.start, 10), cfg, 2)
        with self.assertRaises(ValueError):
            independent_fixture_score({'text': {'claim': 'symbol:0'}}, 1, cfg)
        with self.assertRaises(ValueError):
            full_outcome_audit(mode_state('hard', self.start, 10), cfg,
                               lambda s: QUERY)

if __name__ == '__main__':
    unittest.main()
