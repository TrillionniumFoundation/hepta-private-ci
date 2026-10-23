"""Adversarial golden tests for NDU-DMGP shadow research gates."""
from dataclasses import replace
from math import cos, sin
import unittest
from reference import (
    Action, Claim, Freeze, GenerationState, JointSample, LearningProposal,
    Outcome, RiskEstimate, SemanticPlan, Unavailable, WorkReceipt, allocate,
    closure_audit, compare_work, global_credit, joint_covariance,
    low_rank_diagonal, paired_future_evaluation, qualify_next_snapshot,
    recursive_stop_choice, verify_cross_modal,
)

F = Freeze('objective-v1', 3, 'generator-owner', 'critic-owner',
           'outcome-observer', 'frozen-critic-sha', 'feature-snapshot-sha')


def outcomes(n=30):
    rows = []
    for i in range(n):
        for arm, val, latency in [('A0', .32, 3000), ('A5', .53 + .02 * sin(i), 1800)]:
            rows.append(Outcome(str(i), arm, F.objective, F.generation,
                                F.observer, F.actor, F.critic_digest,
                                'same-prompt-' + str(i), 'future', val,
                                latency, 50 if arm == 'A0' else 100,
                                50, f'{i}:{arm}:execution'))
    return tuple(rows)


def samples(n=36):
    return tuple(JointSample(str(i), 'task=text+image', F.objective, F.observer,
                             (.35 + .12 * sin(i * .5),
                              .4 + .08 * cos(i * .7),
                              .2 + .05 * sin(i * .9 + .3))) for i in range(n))


def plan_claims():
    plan = SemanticPlan(('text', 'audio', 'video'),
                        (('opening', 'speaker1', 0, 500),
                         ('finale', 'speaker2', 500, 1000)), 30)
    claims = tuple(Claim(m, e, person, start, end, f'evidence:{m}:{e}', F.observer)
                   for m in plan.modalities
                   for e, person, start, end in plan.events)
    return plan, claims


class IdentityAndReward(unittest.TestCase):
    def test_external_future_effect_is_observed(self):
        avg, lcb, n = paired_future_evaluation(outcomes(), F, 'A0', 'A5', 1e-5)
        self.assertGreater(lcb, 0)
        self.assertGreater(avg, lcb)
        self.assertEqual(n, 30)

    def test_self_judging_reward_fails_closed(self):
        with self.assertRaisesRegex(Unavailable, 'distinct'):
            replace(F, observer=F.actor).validate()
        with self.assertRaisesRegex(Unavailable, 'distinct'):
            replace(F, critic=F.actor).validate()

    def test_train_label_and_repeated_episode_fail(self):
        rows = outcomes()
        with self.assertRaisesRegex(Unavailable, 'leakage'):
            paired_future_evaluation((replace(rows[0], split='train'),) + rows[1:],
                                     F, 'A0', 'A5', 0)
        with self.assertRaisesRegex(Unavailable, 'double counted'):
            paired_future_evaluation((replace(rows[1], work_key=rows[0].work_key),)
                                     + rows[:1] + rows[2:], F, 'A0', 'A5', 0)
        with self.assertRaisesRegex(Unavailable, 'unmatched input'):
            paired_future_evaluation((replace(rows[1], source_digest='other'),)
                                     + rows[:1] + rows[2:], F, 'A0', 'A5', 0)

    def test_future_support_floor_cannot_be_overridden(self):
        with self.assertRaisesRegex(Unavailable, 'cannot lower'):
            paired_future_evaluation(outcomes(), F, 'A0', 'A5', 0,
                                     min_episodes=2)

    def test_critic_revision_and_future_support_fail(self):
        with self.assertRaisesRegex(Unavailable, 'drift'):
            paired_future_evaluation((replace(outcomes()[0], critic_digest='new'),)
                                     + outcomes()[1:], F, 'A0', 'A5', 0)
        with self.assertRaisesRegex(Unavailable, 'too few'):
            paired_future_evaluation(outcomes(8), F, 'A0', 'A5', 0)


class ModalConsistency(unittest.TestCase):
    def test_forward_reverse_and_time_align(self):
        p, c = plan_claims()
        self.assertEqual(len(verify_cross_modal(p, c, F)), 64)

    def test_receipt_is_bound_to_claim_evidence_and_pairwise_timing(self):
        p, c = plan_claims()
        altered_evidence = (replace(c[0], evidence_digest='different-source'),) + c[1:]
        self.assertNotEqual(verify_cross_modal(p, c, F),
                            verify_cross_modal(p, altered_evidence, F))
        # Both shifts satisfy the plan tolerance individually, but a 50 ms
        # disagreement violates the pairwise synchronization tolerance (30).
        drifted = (replace(c[0], start_ms=25),
                   replace(c[2], start_ms=0),
                   replace(c[4], start_ms=-25))
        with self.assertRaises(Unavailable):
            verify_cross_modal(p, drifted + c[1:2] + c[3:4] + c[5:], F)
        overlapping = replace(p, events=(('opening', 'speaker1', 0, 500),
                                         ('finale', 'speaker2', 400, 1000)))
        with self.assertRaises(Unavailable):
            verify_cross_modal(overlapping, c, F)

    def test_missing_output_and_hallucinated_claim(self):
        p, c = plan_claims()
        with self.assertRaisesRegex(Unavailable, 'forward audit'):
            verify_cross_modal(p, c[:-1], F)
        with self.assertRaisesRegex(Unavailable, 'reverse audit'):
            verify_cross_modal(p, c + (replace(c[0], event='unobserved'),), F)

    def test_entity_timing_and_observer_inconsistency(self):
        p, c = plan_claims()
        for modified in (replace(c[0], entity='speaker3'),
                         replace(c[0], start_ms=80),
                         replace(c[0], observer=F.actor),
                         replace(c[0], evidence_digest='')):
            with self.assertRaises(Unavailable):
                verify_cross_modal(p, (modified,) + c[1:], F)


class CovarianceAndPolicy(unittest.TestCase):
    def test_joint_centered_shrinkage_spd(self):
        r = joint_covariance(samples(), F, 'task=text+image')
        self.assertEqual(r.sample_count, 36)
        self.assertAlmostEqual(r.covariance[0][1], r.covariance[1][0])
        self.assertGreater(r.covariance[0][0], 0)
        self.assertLess(r.condition_upper, 1e6)

    def test_diagonal_and_low_rank_plus_diagonal_are_psd(self):
        r = joint_covariance(samples(), F, 'task=text+image')
        self.assertEqual(low_rank_diagonal(r, 0, 1).rank_retained, 0)
        self.assertEqual(low_rank_diagonal(r, 1, 1).rank_retained, 1)
        self.assertEqual(low_rank_diagonal(r, 3).covariance, r.covariance)
        with self.assertRaises(Unavailable):
            low_rank_diagonal(r, 1, 0.0)

    def test_not_identified_and_wrong_conditional_context(self):
        with self.assertRaisesRegex(Unavailable, 'insufficient'):
            joint_covariance(samples(5), F, 'task=text+image')
        with self.assertRaisesRegex(Unavailable, 'conditional'):
            joint_covariance(samples(), F, 'other')
        collinear = tuple(JointSample(str(i), 'same', F.objective, F.observer,
                                      (.15 * sin(i), .30 * sin(i))) for i in range(35))
        with self.assertRaisesRegex(Unavailable, 'rank-deficient'):
            joint_covariance(collinear, F, 'same', shrink=.7)

    def test_grid_route_and_deterministic_fallback(self):
        r = joint_covariance(samples(), F, 'task=text+image')
        acts = (Action('text', 'text', 1000), Action('image', 'image', 1500),
                Action('audio', 'audio', 3000))
        w = allocate(acts, r, 2000, .5, .01, (1/3, 1/3, 1/3))
        self.assertAlmostEqual(sum(w.weights), 1)
        self.assertEqual(w.weights[2], 0)
        self.assertGreaterEqual(w.variance, 0)
        self.assertEqual(allocate(acts, None, 2000, .5, 0,
                                  (1/3,1/3,1/3)).profile, 'deterministic-fallback')
        with self.assertRaisesRegex(Unavailable, 'no feasible'):
            allocate(acts, None, 50, .5, 0, (1/3,1/3,1/3))


class StabilityAndCredit(unittest.TestCase):
    def test_next_snapshot_only_immutable_critic(self):
        p = LearningProposal(3, 4, F.actor, F.observer, F.critic_digest,
                             .01, .04, .21, .12, -.01)
        self.assertIn('next-snapshot', qualify_next_snapshot(p, F))
        for bad in (replace(p, candidate_generation=3),
                    replace(p, critic_digest='unfrozen'),
                    replace(p, kl_divergence=.8),
                    replace(p, future_candidate_lcb=.1),
                    replace(p, old_task_degradation=-.08)):
            with self.assertRaises(Unavailable):
                qualify_next_snapshot(bad, F)

    def test_full_coalition_credit_with_conservation(self):
        coalition = {frozenset(): .0, frozenset({'a'}): .15,
                     frozenset({'b'}): .20, frozenset({'a','b'}): .36}
        credit = global_credit(coalition, ('a', 'b'), F.observer, F,
                               randomized=True, min_support=40)
        self.assertAlmostEqual(sum(credit.values()), .36)

    def test_noncausal_and_synergy_do_not_become_local_reward(self):
        x = {frozenset(): .0, frozenset({'a'}): .1,
             frozenset({'b'}): .1, frozenset({'a','b'}): .8}
        with self.assertRaisesRegex(Unavailable, 'interaction'):
            global_credit(x, ('a','b'), F.observer, F, True, 30)
        x[frozenset({'a','b'})] = .2
        with self.assertRaisesRegex(Unavailable, 'intervention'):
            global_credit(x, ('a','b'), F.observer, F, False, 30)
        with self.assertRaisesRegex(Unavailable, 'incomplete'):
            global_credit({frozenset(): 0}, ('a','b'), F.observer, F, True, 30)

    def test_stop_and_continuation_with_risk(self):
        s = GenerationState(3, 3000, 2, .5)
        acts = (Action('caption', 'text', 1000), Action('picture', 'image', 2000))
        choice, _ = recursive_stop_choice(s, acts, {'caption': .16, 'picture': .02},
                                          cost_per_us=1e-6)
        self.assertEqual(choice, 'caption')
        self.assertEqual(recursive_stop_choice(s, acts, {'caption': .16,
                       'picture': .02}, risk_penalty={'caption': 1.0})[0], 'stop')
        self.assertEqual(recursive_stop_choice(replace(s, remaining_steps=0),
                         acts, {'caption': .16})[0], 'stop')


class PerformanceAndClosure(unittest.TestCase):
    def test_measured_cost_gates_and_p95(self):
        b = tuple(WorkReceipt(str(i), f'b{i}', 3000, 30, 20, 4096, True)
                  for i in range(30))
        c = tuple(WorkReceipt(str(i), f'c{i}', 1500, 160, 35, 4096, True)
                  for i in range(30))
        r = compare_work(b, c)
        self.assertFalse(r['production_efficiency_evidence'])
        self.assertTrue(r['unverified_host_metric_candidate'])
        self.assertGreater(r['decoder_saved_us'], r['extra_controller_us'])
        self.assertFalse(compare_work(b, (replace(c[0], measured_on_host=False),)
                                       + c[1:])['production_efficiency_evidence'])
        with self.assertRaisesRegex(Unavailable, 'duplicate physical'):
            compare_work(b, (replace(c[0], physical_work_key='b1'),) + c[1:])

    def test_history_has_additional_predictive_value(self):
        train = tuple((sin(i*.6), cos(i*.45), 2*sin(i*.6)+3*cos(i*.45))
                      for i in range(30))
        future = tuple((sin(i*.6), cos(i*.45), 2*sin(i*.6)+3*cos(i*.45))
                       for i in range(30,60))
        result = closure_audit(train, future)
        self.assertFalse(result['closure_not_rejected'])
        self.assertGreater(result['history_gain'], .9)

    def test_history_is_irrelevant(self):
        train = tuple((sin(i*.6), cos(i*.45), 2*sin(i*.6)) for i in range(30))
        future = tuple((sin(i*.6), cos(i*.45), 2*sin(i*.6))
                       for i in range(30,60))
        result = closure_audit(train, future)
        self.assertTrue(result['closure_not_rejected'])
        with self.assertRaisesRegex(Unavailable, 'too little'):
            closure_audit(train[:3], future)


if __name__ == '__main__':
    unittest.main()
