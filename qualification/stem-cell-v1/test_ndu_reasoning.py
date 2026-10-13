import copy
import json
import unittest
from dataclasses import asdict, replace

import torch

import test_ndu_continuation as fixtures
from execution_meter import WorkLedger
from ndu_continuation import PROFILE, ContinuationBranch, ContinuationEstimate
from paired_execution import PHASES
from system2_execution import PublicTask, Verification, run_reasoning
from test_execution_meter import policy as meter_policy
from work_record import validate_work_record


def run_case(*, control=None, critic=None, propose=None, verifier=None, cap=10000,
             ledger=None, clock=lambda:120, max_calls=8, mode='strict'):
    p=control or fixtures.policy(cap=cap,calls=max_calls,mode=mode)
    ledger=ledger or WorkLedger(meter_policy(mode),dict.fromkeys(PHASES,cap))
    calls=[]
    task=PublicTask('Add both publicly supplied integers',100,(('2, 3',99),))
    def generator(task,previous,feedback):
        calls.append(('propose',previous,feedback))
        # Real tensor computation, procedural fixture; not a trained generator.
        values=torch.tensor([float(x) for x in task.observations[0][0].split(',')])
        total=values.sum().item()
        return str(int(total if previous is not None else total-1))
    def check(task,candidate):
        calls.append(('verify',candidate))
        torch.ones(2).add(1)  # Explicitly observed verifier tensor work.
        return Verification(int(candidate)==sum(map(int,task.observations[0][0].split(','))),
                            'Include both input integers')
    def value(task,candidate,feedback,context):
        calls.append(('value',context.context_id))
        torch.ones(3).add(1)
        return fixtures.estimate(p,context,observed_through_ns=120,
                                  branches=(ContinuationBranch(1_000_000,.9,.95,10**9,10),))
    result=run_reasoning(task,propose=propose or generator,verify=verifier or check,
                         continue_values=critic or value,value_profile=PROFILE,ndu_policy=p,
                         meter=ledger,clock=clock,max_calls=max_calls)
    return result,calls,ledger


class NduReasoningTests(unittest.TestCase):
    def test_real_callbacks_continue_revise_and_account_all_three_kinds(self):
        r,calls,_=run_case()
        self.assertEqual(r['candidate'],'5')
        self.assertEqual(r['calls'],5)
        self.assertEqual([c[0] for c in calls],['propose','verify','value','propose','verify'])
        self.assertEqual(r['status'],'verifier_accepted_not_independent_eval')
        self.assertEqual(r['ndu_decisions'][0]['reason'],'supported_net_gain')
        obs=r['work_observation'];validate_work_record(obs)
        self.assertEqual({s['component'] for s in obs['scopes']},{'proposer','verifier','value'})
        self.assertEqual(obs['phase_flops']['search'],9)
        self.assertFalse(r['independent_success_established'])
        self.assertFalse(r['native_ndu_owner_integrated'])
        self.assertIsNone(r['measured_flops'])
        json.dumps(r,allow_nan=False)

    def test_expensive_continuation_stops_before_second_generation(self):
        r,calls,_=run_case(control=fixtures.policy(cap=10000,cost_per_formula_flop=.1))
        self.assertEqual(r['status'],'ndu_stop:no_supported_net_gain')
        self.assertEqual(r['calls'],3)
        self.assertEqual(sum(c[0]=='propose' for c in calls),1)

    def test_successful_first_answer_needs_no_critic(self):
        r,calls,_=run_case(propose=lambda *args:'5',critic=lambda *args:self.fail('unneeded critic'))
        self.assertEqual(r['calls'],2);self.assertEqual(r['ndu_decisions'],[])

    def test_critic_work_reduces_the_remaining_budget_before_decision(self):
        p=fixtures.policy(cap=30)
        def value(t,c,f,ctx):
            torch.ones(20).add(1)
            return fixtures.estimate(p,ctx,observed_through_ns=120,
                 branches=(ContinuationBranch(1_000_000,1.,1.,100,10),))
        r,calls,_=run_case(control=p,critic=value,cap=30)
        self.assertEqual(r['status'],'ndu_stop:infeasible_continuation')
        self.assertEqual(r['calls'],3)
        self.assertEqual(r['work_observation']['phase_flops']['search'],23)

    def test_unregistered_critic_operator_stops_without_later_callbacks(self):
        def unknown(*args):
            torch.ones(3).sin_()
        r,calls,_=run_case(critic=unknown)
        self.assertEqual(r['status'],'resource_budget_stop')
        self.assertEqual(sum(c[0]=='propose' for c in calls),1)
        validate_work_record(r['work_observation'])
        self.assertIsNone(r['work_observation']['phase_flops']['search'])

    def test_observe_mode_does_not_turn_unknown_cost_into_permission(self):
        p=fixtures.policy(cap=10000,mode='observe')
        def value(t,c,f,ctx):
            torch.ones(3).sin_()
            return fixtures.estimate(p,ctx,observed_through_ns=120)
        r,_,_=run_case(control=p,critic=value,mode='observe')
        self.assertEqual(r['status'],'ndu_stop:incomplete_work_coverage')
        self.assertEqual(r['calls'],3)

    def test_invalid_tuple_future_or_substituted_critic_is_rejected(self):
        p=fixtures.policy(cap=10000)
        for cb in (lambda *args:(1.,0.),lambda t,c,f,s: fixtures.estimate(p,s,critic_sha256='f'*64),
                   lambda t,c,f,s:fixtures.estimate(p,s,observed_through_ns=121)):
            with self.subTest(callback=cb):
                r,_,_=run_case(control=p,critic=cb)
                self.assertEqual(r['status'],'callback_failed');self.assertEqual(r['calls'],3)

    def test_unsupported_estimate_does_not_invent_a_value(self):
        r,_,_=run_case(critic=lambda *args:None)
        self.assertEqual(r['status'],'ndu_stop:unsupported_continuation')

    def test_fixed_callback_budget_cannot_be_expanded_by_value(self):
        r,calls,_=run_case(max_calls=4,critic=lambda *args:self.fail('cannot afford next round'))
        self.assertEqual(r['status'],'budget_exhausted');self.assertEqual(r['calls'],2)

    def test_policy_expired_before_start_executes_nothing(self):
        p=fixtures.policy(cap=10000,expires_at_ns=110)
        with self.assertRaises(ValueError):run_case(control=p,propose=lambda *args:self.fail('expired'))

    def test_meter_is_mandatory_and_policy_is_detached_from_external_dict(self):
        p=fixtures.policy(cap=10000)
        task=PublicTask('task',100)
        with self.assertRaises(ValueError):
            run_reasoning(task,propose=lambda *args:'x',verify=lambda *args:Verification(False,'bad'),
                          continue_values=lambda *args:None,value_profile=PROFILE,ndu_policy=p,clock=lambda:120)
        def value(t,c,f,ctx):
            p['cost_per_formula_flop']=999
            return fixtures.estimate(p,ctx,observed_through_ns=120,
                   branches=(ContinuationBranch(1_000_000,.9,.95,10**9,10),))
        r,_,_=run_case(control=p,critic=value)
        self.assertEqual(r['ndu_policy']['cost_per_formula_flop'],0)
        self.assertEqual(r['candidate'],'5')

    def test_repeated_context_substitution_and_task_mutation_fail(self):
        p=fixtures.policy(cap=10000)
        def value(t,c,f,ctx):
            old_id=ctx.context_id
            object.__setattr__(ctx,'rounds_left',999)
            return fixtures.estimate(p,ctx,observed_through_ns=120)
        r,_,_=run_case(control=p,critic=value)
        self.assertEqual(r['status'],'callback_failed')
        def mutate(t,*args):
            object.__setattr__(t,'prompt','changed goal')
            return '4'
        r,_,_=run_case(propose=mutate)
        self.assertEqual(r['status'],'callback_failed');self.assertEqual(r['calls'],1)

    def test_policy_expiring_during_proposal_prevents_the_next_callback(self):
        now=[101]
        def propose(*args):
            now[0]=111
            return '4'
        with self.assertRaises(ValueError):
            # The caller cannot claim a policy that expired before task start.
            run_case(control=fixtures.policy(cap=10000,expires_at_ns=99))
        r,_,_=run_case(control=fixtures.policy(cap=10000,expires_at_ns=110),clock=lambda:now[0],
                       propose=propose,verifier=lambda *args:self.fail('expired verifier'))
        self.assertEqual(r['status'],'callback_failed')
        self.assertEqual(r['trace'][-1]['kind'],'verify')
        self.assertEqual(r['trace'][-1]['status'],'failed')

    def test_retained_decision_can_be_replayed_from_its_actual_bound_inputs(self):
        from ndu_continuation import DecisionContext, decide
        r,_,_=run_case()
        recorded=json.loads(json.dumps(r['ndu_decisions'][0],allow_nan=False))
        raw=copy.deepcopy(recorded['estimate'])
        raw['branches']=tuple(ContinuationBranch(**b) for b in raw['branches'])
        replayed=decide(r['ndu_policy'],DecisionContext(**recorded['context']),
                        ContinuationEstimate(**raw),now_ns=recorded['decision_at_ns'],
                        resources=recorded['post_critic_resources'])
        for key,value in replayed.items():
            self.assertEqual(json.dumps(recorded[key],sort_keys=True),json.dumps(value,sort_keys=True),key)
        self.assertTrue(recorded['realized_support_bounds_satisfied'])

    def test_runtime_cannot_replace_frozen_caps_depth_or_meter_profile(self):
        p=fixtures.policy(cap=10000)
        for change in ({'cap':10001},{'max_calls':9},{'mode':'observe'}):
            with self.subTest(change=change),self.assertRaises(ValueError):
                run_case(control=p,**change)

    def test_actual_segment_cost_violation_cannot_be_reported_as_accepted(self):
        p=fixtures.policy(cap=10000)
        def value(t,c,f,ctx):
            return fixtures.estimate(p,ctx,observed_through_ns=120,
                 branches=(ContinuationBranch(1_000_000,.9,.95,10**9,0),))
        r,_,_=run_case(control=p,critic=value)
        self.assertEqual(r['status'],'ndu_stop:continuation_support_violated')
        self.assertEqual(r['candidate'],'5')  # Candidate retained, not successful admission.
        self.assertEqual(r['ndu_decisions'][0]['observed_segment_formula_work'],3)
        self.assertFalse(r['ndu_decisions'][0]['realized_support_bounds_satisfied'])

    def test_actual_segment_duration_violation_is_retained(self):
        p=fixtures.policy(cap=10000)
        def value(t,c,f,ctx):
            return fixtures.estimate(p,ctx,observed_through_ns=120,
                 branches=(ContinuationBranch(1_000_000,.9,.95,1,100),))
        r,_,_=run_case(control=p,critic=value)
        self.assertEqual(r['status'],'ndu_stop:continuation_support_violated')
        self.assertGreater(r['ndu_decisions'][0]['observed_segment_wall_ns'],1)

    def test_invalid_callback_is_failed_in_meter_not_only_trace(self):
        r,_,_=run_case(critic=lambda *args:(1.,0.))
        row=next(s for s in r['work_observation']['scopes'] if s['component']=='value')
        self.assertEqual(row['failed_calls'],1)
        self.assertIsNone(r['work_observation']['phase_flops']['search'])
        validate_work_record(r['work_observation'])

    def test_nonfinal_budget_view_does_not_seal_or_expose_live_state(self):
        ledger=WorkLedger(meter_policy(),dict.fromkeys(PHASES,10))
        a=ledger.budget_state('search');self.assertEqual(a['remaining_formula_work'],10)
        a['remaining_formula_work']=999
        with ledger.scope('search','value'):torch.ones(2).add(1)
        self.assertEqual(ledger.budget_state('search')['remaining_formula_work'],8)
        ledger.report()
        with self.assertRaises(ValueError):ledger.budget_state('search')


if __name__=='__main__':unittest.main()
