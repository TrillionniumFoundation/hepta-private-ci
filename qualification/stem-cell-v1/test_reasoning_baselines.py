import copy
import unittest
from unittest.mock import patch

from empirical_continuation import FrozenPairedCritic
from execution_meter import WorkLedger, TRANSFORMER_POLICY_SCHEMA
from generation_test_support import adapter, structural_verifier, train_tiny
from ndu_continuation import freeze_policy, PROFILE as NDU_PROFILE
from next_round_matrix import _digest
from paired_critic import freeze_protocol
from paired_execution import PHASES
from reasoning_baselines import freeze_baseline, PROFILE
from system2_execution import PublicTask, Verification, run_reasoning
from test_execution_meter import policy as work_policy
from test_paired_critic import fixture, fit
from transformer_work import PROFILE as METER_PROFILE


def policy_inputs():
    policy = work_policy('strict')
    policy.update(schema=TRANSFORMER_POLICY_SCHEMA, arithmetic_profile=METER_PROFILE)
    return policy, dict.fromkeys(PHASES, 10**7)


def ready_ndu(propose, verify, callback_profile, *, success=.9):
    # Explicit SYNTHETIC empirical data: fits test control paths, not this LM's calibration.
    original, rows = fixture(success=success)
    values = {k:v for k,v in original.items() if k not in ('schema', 'protocol_id')}
    values.update(callback_profile_sha256=callback_profile, formula_work_upper=1_000_000,
                  candidate_edges=[256], feedback_edges=[256])
    protocol = freeze_protocol(**values)
    for row in rows: row['protocol_id']=protocol['protocol_id']
    artifact = fit(protocol, rows)
    critic = FrozenPairedCritic(artifact, expected_id=artifact['artifact_id'],
                               callback_profile_sha256=callback_profile, propose=propose, verify=verify)
    wp, caps = policy_inputs()
    p = freeze_policy(objective_sha256=protocol['objective_sha256'], subject_id=protocol['subject_id'],
                       critic_sha256=artifact['artifact_id'], critic_cutoff_ns=protocol['cutoff_ns'],
                       expires_at_ns=protocol['expires_at_ns'], **protocol['coefficients'],
                       minimum_margin=0., max_estimate_age_ns=10**11,
                       execution=dict(max_calls=5, max_rounds=2, meter_policy=wp, phase_caps=caps),
                       empirical_protocol_id=protocol['protocol_id'])
    return p, critic


class FixedReasoningTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls): cls.m, cls.t, cls.train = train_tiny()

    def setUp(self):
        self.p = adapter(copy.deepcopy(self.m), copy.deepcopy(self.t))
        self.task = PublicTask('colour red',10**10+1)
        self.wp, self.caps = policy_inputs()
        self.profile = _digest([self.p.receipt()['policy'], 'test_structural_verifier_v1'])

    def fixed(self, strategy='fixed_depth', depth=2, **overrides):
        p = freeze_baseline(strategy=strategy, objective_sha256='a'*64,
                             callback_profile_sha256=self.profile, expires_at_ns=10**14,
                             meter_policy=self.wp, phase_caps=self.caps, max_rounds=depth)
        args = dict(propose=self.p, verify=structural_verifier, continue_values=None, value_profile=PROFILE,
                    max_rounds=depth, max_calls=2*depth, meter=WorkLedger(self.wp,self.caps),
                    fixed_policy=p, clock=lambda:10**10+5)
        args.update(overrides)
        return run_reasoning(self.task, **args)

    def test_three_strategies_same_generator_and_caps_no_dummy_valuation(self):
        a = self.fixed('no_search',1); b=self.fixed()
        pol,critic=ready_ndu(self.p,structural_verifier,self.profile)
        c=run_reasoning(self.task,propose=self.p,verify=structural_verifier,continue_values=critic,
                         value_profile=NDU_PROFILE,max_calls=5,max_rounds=2,ndu_policy=pol,
                         meter=WorkLedger(self.wp,self.caps),clock=lambda:10**10+5)
        self.assertEqual([r['calls'] for r in (a,b,c)],[2,4,5])
        self.assertEqual([r['candidate'] for r in (a,b,c)],['unsure','red done','red done'])
        self.assertEqual([e['kind'] for e in b['trace']],['propose','verify','propose','verify'])
        self.assertEqual([e['generation']['forward_attempts'] for e in c['trace'] if e['kind']=='propose'],[2,3])
        self.assertGreater(b['work_observation']['phase_flops']['search'],a['work_observation']['phase_flops']['search'])
        self.assertEqual(b['work_observation']['unknown_operators'],{})
        for result in (a,b,c): self.assertFalse(result['independent_success_established'])

    def test_low_supported_gain_stops_real_neural_generator(self):
        pol,critic=ready_ndu(self.p,structural_verifier,self.profile,success=.2)
        r=run_reasoning(self.task,propose=self.p,verify=structural_verifier,continue_values=critic,
                         value_profile=NDU_PROFILE,max_calls=5,max_rounds=2,ndu_policy=pol,
                         meter=WorkLedger(self.wp,self.caps),clock=lambda:10**10+5)
        self.assertEqual((r['calls'],r['candidate']),(3,'unsure'))
        self.assertEqual(r['status'],'ndu_stop:no_supported_net_gain')

    def test_fixed_depth_stops_on_same_verifier_acceptance(self):
        r=self.fixed(verify=lambda *a:Verification(True,'format accepted'))
        self.assertEqual(r['calls'],2)
        self.assertEqual(r['candidate'],'unsure')  # Acceptance is NOT target correctness.

    def test_budget_stop_keeps_partial_generation_receipt(self):
        self.caps=dict.fromkeys(PHASES,1)
        r=self.fixed()
        self.assertEqual(r['status'],'resource_budget_stop')
        self.assertEqual(r['calls'],1)
        self.assertEqual(r['trace'][0]['generation']['status'],'failed')
        self.assertIsNone(r['candidate'])
        self.assertIsNone(r['work_observation']['phase_flops']['search'])

    def test_expiry_inside_verifier_cannot_report_acceptance(self):
        now=[10**10+5]
        def verify(*args): now[0]=10**14; return Verification(True,'accepted')
        r=self.fixed(verify=verify,clock=lambda:now[0])
        self.assertEqual(r['status'],'callback_failed')
        self.assertEqual(r['trace'][-1]['status'],'failed')

    def test_unsupported_or_substituted_budget_and_fake_critic_reject(self):
        for change in (dict(max_calls=6),dict(continue_values=lambda *a:(1.,0.)),dict(value_profile=NDU_PROFILE),
                       dict(meter=WorkLedger(self.wp,dict.fromkeys(PHASES,1)))):
            with self.subTest(change=change),self.assertRaises(ValueError):self.fixed(**change)
        pol,_=ready_ndu(self.p,structural_verifier,self.profile)
        with self.assertRaises(ValueError):self.fixed(ndu_policy=pol)

    def test_no_search_depth_and_rehashed_policy_fields_reject(self):
        with self.assertRaises(ValueError):self.fixed('no_search',2)
        policy=freeze_baseline(strategy='fixed_depth',objective_sha256='a'*64,callback_profile_sha256=self.profile,
                               expires_at_ns=10**14,meter_policy=self.wp,phase_caps=self.caps,max_rounds=2)
        policy['stop_on_verified']=False
        with self.assertRaises(ValueError):self.fixed(fixed_policy=policy)

    def test_public_task_mutation_and_provider_failure_stay_failed(self):
        def mutate(task,*args): object.__setattr__(task,'prompt','changed');return 'answer'
        r=self.fixed(propose=mutate)
        self.assertEqual(r['status'],'callback_failed')
        self.assertEqual(self.task.prompt,'colour red')
        def fail(*args):raise OSError('test provider')
        r=self.fixed(propose=fail)
        self.assertEqual((r['calls'],r['status']),(1,'callback_failed'))


if __name__=='__main__':unittest.main()
