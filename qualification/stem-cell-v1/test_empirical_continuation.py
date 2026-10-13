import copy
import tempfile
import unittest
from dataclasses import asdict, replace
from unittest.mock import patch

import torch

from empirical_continuation import FrozenPairedCritic, EmpiricalEstimate, case_fingerprint
from execution_meter import WorkLedger
from ndu_continuation import PROFILE, DecisionContext, decide, freeze_policy
from next_round_matrix import _digest
from paired_execution import PHASES
from system2_execution import PublicTask, Verification, run_reasoning
from test_execution_meter import policy as work_policy
from test_paired_critic import fixture,fit


def ready(*,success=.9,cal_count=64,coefficient=0.,cap=1000):
    p,rows=fixture(success=success,cal_count=cal_count,coefficient=coefficient)
    artifact=fit(p,rows)
    calls=[]
    def propose(task,previous,feedback):
        calls.append(('propose',previous));torch.ones(3).add(1)
        return '4' if previous is None else '5'
    def verify(task,candidate):
        calls.append(('verify',candidate));torch.ones(3).add(1)
        return Verification(candidate=='5','try again')
    critic=FrozenPairedCritic(artifact,expected_id=artifact['artifact_id'],callback_profile_sha256='b'*64,
                             propose=propose,verify=verify)
    meter_policy=work_policy('strict');meter_policy['wall_time_ns']=20*10**9
    execution=dict(max_calls=5,max_rounds=2,meter_policy=meter_policy,phase_caps=dict.fromkeys(PHASES,cap))
    policy=freeze_policy(objective_sha256=p['objective_sha256'],subject_id=p['subject_id'],
                         critic_sha256=artifact['artifact_id'],critic_cutoff_ns=p['cutoff_ns'],expires_at_ns=p['expires_at_ns'],
                         **p['coefficients'],minimum_margin=0.,max_estimate_age_ns=10**11,
                         execution=execution,empirical_protocol_id=p['protocol_id'])
    task=PublicTask('Add the supplied numbers',10**10+1,(('2,3',100),))
    return artifact,policy,task,propose,verify,critic,calls


def run(bundle,**changes):
    _,p,t,prop,ver,critic,_=bundle
    meter=WorkLedger(p['execution']['meter_policy'],p['execution']['phase_caps'])
    args=dict(propose=prop,verify=ver,continue_values=critic,value_profile=PROFILE,ndu_policy=p,
              max_rounds=2,max_calls=5,meter=meter,clock=lambda:10**10+5)
    args.update(changes)
    return run_reasoning(t,**args)


class EmpiricalContinuationTests(unittest.TestCase):
    def test_fitted_data_really_control_next_model_calls(self):
        b=ready();r=run(b)
        self.assertEqual(r['status'],'verifier_accepted_not_independent_eval')
        self.assertEqual(r['calls'],5)
        self.assertEqual(r['candidate'],'5')
        self.assertEqual(r['empirical_critic']['estimator'],'frozen_group_mean_table')
        self.assertTrue(r['empirical_critic']['empirical_critic_fitted'])
        self.assertFalse(r['learned_critic_validated'])
        self.assertFalse(r['empirical_critic']['neural_critic_trained'])
        d=r['ndu_decisions'][0]
        self.assertEqual(d['comparison'],'conditional_group_mean_net_gain')
        self.assertFalse(d['segment_cost_subtracted_again'])
        self.assertTrue(d['realized_support_bounds_satisfied'])
        self.assertEqual(r['work_observation']['phase_flops']['search'],12)

    def test_low_utility_data_stop_without_second_generation(self):
        b=ready(success=.2);r=run(b)
        self.assertEqual(r['status'],'ndu_stop:no_supported_net_gain')
        self.assertEqual(r['calls'],3)
        self.assertEqual(len(b[-1]),2)

    def test_insufficient_calibration_returns_missing_support(self):
        r=run(ready(cal_count=1))
        self.assertEqual(r['status'],'ndu_stop:unsupported_continuation')
        self.assertEqual(r['calls'],3)

    def test_envelope_uses_budget_remaining_after_first_pair(self):
        r=run(ready(cap=105))  # first pair uses 6; declared segment needs 100.
        self.assertEqual(r['status'],'ndu_stop:infeasible_continuation')
        self.assertEqual(r['calls'],3)

    def test_substituted_callback_or_critic_block_before_execution(self):
        b=ready()
        with self.assertRaisesRegex(ValueError,'callback substituted'):
            run(b,propose=lambda *a:'5')
        self.assertEqual(b[-1],[])
        with self.assertRaisesRegex(ValueError,'fitted frozen'):
            run(b,continue_values=lambda *a:None)
        self.assertEqual(b[-1],[])

    def test_utility_coefficients_and_objective_cannot_change_after_fit(self):
        b=ready();p=b[1]
        for key,value in (('cost_per_formula_flop',.1),('subject_id','episode:other'),('critic_sha256','e'*64)):
            args={k:v for k,v in p.items() if k not in ('policy_id','schema','utility_profile')}
            args[key]=value;changed=freeze_policy(**args)
            with self.subTest(key=key),self.assertRaisesRegex(ValueError,'fixed objective'):
                run(b,ndu_policy=changed)
        self.assertEqual(b[-1],[])

    def test_no_silent_extension_to_multistep_horizon(self):
        b=ready();args={k:v for k,v in b[1].items() if k not in ('schema','policy_id','utility_profile')}
        args['execution']=copy.deepcopy(args['execution']);args['execution']['max_rounds']=3
        with self.assertRaises(ValueError):freeze_policy(**args)

    def test_runtime_has_no_outcome_file_reads_or_refit(self):
        b=ready()
        with patch('builtins.open',side_effect=AssertionError('no raw outcome reads')), \
             patch('paired_critic.fit_critic',side_effect=AssertionError('no runtime fitting')):
            r=run(b)
        self.assertEqual(r['calls'],5)

    def test_serialized_decision_replays_and_is_not_deterministic_support(self):
        b=ready();r=run(b);d=copy.deepcopy(r['ndu_decisions'][0])
        e=EmpiricalEstimate(**d['estimate']);ctx=DecisionContext(**d['context'])
        replay=decide(b[1],ctx,e,now_ns=d['decision_at_ns'],resources=d['post_critic_resources'])
        self.assertTrue(replay['continue_computation'])
        self.assertEqual(replay['net_gain_lower'],d['net_gain_lower'])
        self.assertFalse(replay['pointwise_confidence_established'])
        from ndu_continuation import ContinuationEstimate,ContinuationBranch
        old=ContinuationEstimate(e.context_id,e.critic_sha256,e.support_sha256,e.observed_through_ns,e.valid_until_ns,0.,
                                 (ContinuationBranch(1000000,1.,1.,10,0),))
        with self.assertRaisesRegex(ValueError,'deterministic scenario'):
            decide(b[1],ctx,old,now_ns=d['decision_at_ns'],resources=d['post_critic_resources'])

    def test_out_of_support_lengths_and_training_case_reuse_abstain(self):
        b=ready();a,p,t,prop,ver,critic,_=b
        critic.validate_binding(p,prop,ver)
        candidate,feedback='x'*64,'y'*64
        ctx=DecisionContext(p['policy_id'],_digest(asdict(t)),_digest(candidate),_digest(feedback),'a'*64,
                            t.as_of_ns,1,3,1000,10**10)
        self.assertIsNone(critic(t,candidate,feedback,ctx))
        from paired_critic import freeze_protocol as register
        proto=copy.deepcopy(a['protocol']);proto['pairs'][0]['case_sha256']=case_fingerprint(t,'4','try again')
        proto=register(**{k:v for k,v in proto.items() if k not in ('schema','protocol_id')})
        _,rows=fixture()
        for row in rows:row['protocol_id']=proto['protocol_id']
        a=fit(proto,rows)
        critic=FrozenPairedCritic(a,expected_id=a['artifact_id'],callback_profile_sha256='b'*64,propose=prop,verify=ver)
        args={k:v for k,v in p.items() if k not in ('schema','policy_id','utility_profile')}
        args.update(critic_sha256=a['artifact_id'],empirical_protocol_id=proto['protocol_id'])
        p=freeze_policy(**args);critic.validate_binding(p,prop,ver)
        ctx=replace(ctx,policy_id=p['policy_id'],candidate_sha256=_digest('4'),feedback_sha256=_digest('try again'))
        self.assertIsNone(critic(t,'4','try again',ctx))

    def test_actual_next_segment_exceeding_declared_envelope_is_fenced(self):
        b=list(ready()); original=b[3]
        def expensive(task,previous,feedback):
            if previous is not None:
                torch.ones(101).add(1)
            return original(task,previous,feedback)
        b[3]=expensive
        b[5]=FrozenPairedCritic(b[0],expected_id=b[0]['artifact_id'],callback_profile_sha256='b'*64,
                                propose=expensive,verify=b[4])
        r=run(b)
        self.assertEqual(r['status'],'ndu_stop:continuation_support_violated')
        self.assertEqual(r['candidate'],'5')
        self.assertEqual(r['calls'],5)
        self.assertFalse(r['ndu_decisions'][0]['realized_support_bounds_satisfied'])

    def test_artifact_expiry_age_and_context_mismatch(self):
        b=ready();r=run(b);d=r['ndu_decisions'][0]
        e=EmpiricalEstimate(**d['estimate']);ctx=DecisionContext(**d['context'])
        expired=decide(b[1],ctx,e,now_ns=e.valid_until_ns,resources=d['post_critic_resources'])
        self.assertEqual(expired['reason'],'expired_support')
        for change in (dict(context_id='e'*64),dict(critic_sha256='f'*64),dict(protocol_id='0'*64)):
            with self.subTest(change=change),self.assertRaises(ValueError):
                decide(b[1],ctx,replace(e,**change),now_ns=d['decision_at_ns'],resources=d['post_critic_resources'])
        badctx=replace(ctx,as_of_ns=e.observed_through_ns-1)
        with self.assertRaises(ValueError):
            decide(b[1],badctx,replace(e,context_id=badctx.context_id),now_ns=d['decision_at_ns'],resources=d['post_critic_resources'])

    def test_external_artifact_mutation_cannot_change_frozen_decisions(self):
        b=ready();b[0]['table']['0:0']['net_gain_lower']=-1.
        r=run(b)
        self.assertEqual(r['calls'],5)

    def test_hard_conditional_bounds_are_not_learned_from_sample_maxima(self):
        b=ready();r=run(b);d=r['ndu_decisions'][0]
        self.assertEqual(d['worst_branch_formula_work'],100)
        self.assertEqual(d['worst_branch_duration_ns'],5*10**9)
        self.assertFalse(d['support_authenticity_verified'])


if __name__=='__main__':unittest.main()
