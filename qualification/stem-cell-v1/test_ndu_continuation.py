import copy
import math
import unittest
from dataclasses import replace

from ndu_continuation import (PROFILE, ContinuationBranch as Branch, ContinuationEstimate as Estimate,
                              DecisionContext, decide, freeze_policy, validate_policy)


def policy(**changes):
    from test_execution_meter import policy as work_policy
    from paired_execution import PHASES
    cap=changes.pop("cap", 10**6); calls=changes.pop("calls", 8); mode=changes.pop("mode", "strict")
    execution=dict(max_calls=calls,max_rounds=8,meter_policy=work_policy(mode),phase_caps=dict.fromkeys(PHASES,cap))
    args = dict(objective_sha256='a'*64, subject_id='episode:test-only', critic_sha256='b'*64,
                critic_cutoff_ns=10, expires_at_ns=10**12, discount_rate_per_second=0.,
                cost_per_formula_flop=0., cost_per_latency_ns=0., minimum_margin=0.,
                max_estimate_age_ns=10**10,execution=execution)
    return freeze_policy(**{**args, **changes})


def context(p):
    return DecisionContext(p['policy_id'], 'c'*64, 'd'*64, 'e'*64, 'f'*64,
                           100, 2, 6, 10**6, 10**11)


def estimate(p, c, **changes):
    args = dict(context_id=c.context_id, critic_sha256=p['critic_sha256'], support_sha256='0'*64,
                observed_through_ns=100, valid_until_ns=10**11, stop_upper=.25,
                branches=(Branch(1_000_000, .75, .85, 1000, 10),))
    return Estimate(**{**args, **changes})


def decision(p, c, e, **changes):
    args = dict(now_ns=101, resources={'remaining_formula_work': c.remaining_formula_work,
                                     'remaining_wall_ns': c.remaining_wall_ns - 1})
    return decide(p, c, e, **{**args, **changes})


class NduContinuationTests(unittest.TestCase):
    def test_supported_gain_costs_and_no_sunk_double_charge(self):
        p=policy(cost_per_formula_flop=.01, cost_per_latency_ns=.0001); c=context(p)
        r=decision(p,c,estimate(p,c))
        self.assertAlmostEqual(r['declared_continuation_lower'], .55)
        self.assertTrue(r['continue_computation'])
        self.assertFalse(r['sunk_critic_cost_subtracted_again'])
        self.assertFalse(r['confidence_bound_established'])

    def test_discount_is_branchwise_not_discount_at_mean_duration(self):
        p=policy(discount_rate_per_second=math.log(2)); c=context(p)
        branches=(Branch(500_000,1.,1.,10**9,10), Branch(500_000,1.,1.,3*10**9,10))
        r=decision(p,c,estimate(p,c,branches=branches))
        self.assertAlmostEqual(r['declared_continuation_lower'], .3125)
        self.assertNotAlmostEqual(r['declared_continuation_lower'], .25)

    def test_correlated_duration_and_value_keep_joint_distribution(self):
        p=policy(discount_rate_per_second=math.log(2)); c=context(p)
        branches=(Branch(500_000,0.,0.,10**9,0), Branch(500_000,1.,1.,3*10**9,0))
        r=decision(p,c,estimate(p,c,branches=branches,stop_upper=0.))
        self.assertAlmostEqual(r['declared_continuation_lower'], .0625)

    def test_uncertain_gain_or_equal_margin_stops(self):
        p=policy(minimum_margin=.5); c=context(p)
        self.assertFalse(decision(p,c,estimate(p,c))['continue_computation'])
        p=policy(); c=context(p)
        e=estimate(p,c,branches=(Branch(1_000_000,.1,.99,10,0),))
        self.assertFalse(decision(p,c,e)['continue_computation'])

    def test_rare_expensive_branch_must_fit_worst_case(self):
        p=policy(); c=context(p)
        e=estimate(p,c,branches=(Branch(999_999,1.,1.,10,1),Branch(1,1.,1.,10,10**6+1)))
        self.assertEqual(decision(p,c,e)['reason'],'infeasible_continuation')
        e=estimate(p,c,branches=(Branch(1_000_000,1.,1.,10**11,1),))
        self.assertEqual(decision(p,c,e)['reason'],'infeasible_continuation')

    def test_unknown_support_and_unknown_work_stop(self):
        p=policy(); c=context(p)
        self.assertEqual(decision(p,c,None)['reason'],'unsupported_continuation')
        self.assertEqual(decision(p,c,estimate(p,c), resources={'remaining_formula_work':None,
                         'remaining_wall_ns':1})['reason'],'incomplete_work_coverage')

    def test_context_critic_and_future_observation_cannot_be_substituted(self):
        p=policy(); c=context(p)
        for k,v in (('context_id','1'*64),('critic_sha256','2'*64),('observed_through_ns',101)):
            with self.subTest(k=k), self.assertRaises(ValueError):
                decision(p,c,estimate(p,c,**{k:v}))

    def test_expiry_age_and_clock_reversal(self):
        p=policy(max_estimate_age_ns=1); c=context(p)
        self.assertEqual(decision(p,c,estimate(p,c),now_ns=102)['reason'],'expired_support')
        self.assertEqual(decision(p,c,estimate(p,c,valid_until_ns=101))['reason'],'expired_support')
        with self.assertRaises(ValueError):decision(p,c,estimate(p,c),now_ns=99)

    def test_probability_mass_intervals_units_and_types(self):
        p=policy(); c=context(p); base=estimate(p,c).branches[0]
        for k,v in (('mass_ppm',999999),('mass_ppm',True),('duration_upper_ns',0),
                    ('formula_work_upper',-1),('value_lower',-.1),('value_lower',.9),
                    ('value_upper',float('inf'))):
            with self.subTest(k=k,v=v),self.assertRaises(ValueError):
                decision(p,c,estimate(p,c,branches=(replace(base,**{k:v}),)))
        with self.assertRaises(ValueError):decision(p,c,estimate(p,c,branches=list((base,))))

    def test_policy_is_bound_and_critic_is_prior_to_task(self):
        p=policy();validate_policy(p,task_as_of_ns=20)
        bad=copy.deepcopy(p);bad['cost_per_formula_flop']=1.
        with self.assertRaises(ValueError):validate_policy(bad,task_as_of_ns=20)
        with self.assertRaises(ValueError):validate_policy(p,task_as_of_ns=10)
        for value in (float('nan'),-1,True):
            with self.assertRaises(ValueError):policy(discount_rate_per_second=value)

    def test_resources_cannot_increase_after_critic_and_call_budget_is_bounded(self):
        p=policy();c=context(p)
        with self.assertRaises(ValueError):decision(p,c,estimate(p,c),resources={
             'remaining_formula_work':c.remaining_formula_work+1,'remaining_wall_ns':1})
        c=replace(c,calls_left=2)
        self.assertEqual(decision(p,c,estimate(p,c))['reason'],'insufficient_callback_budget')

    def test_arithmetic_overflow_rejects_not_optimistic_continue(self):
        p=policy(cost_per_formula_flop=1e308);c=context(p)
        with self.assertRaises(ValueError):decision(p,c,estimate(p,c))


if __name__=='__main__': unittest.main()
