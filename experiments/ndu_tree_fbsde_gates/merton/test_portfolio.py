"""Adversarial exact-rational tests; no assertions disabled by python -O."""
from __future__ import annotations

import contextlib
import copy
import io
import json
import tempfile
import unittest
from dataclasses import replace
from fractions import Fraction as Q
from pathlib import Path

from audit import Reference, audit, public_key, strict_load
from portfolio import (ARMS, PROFILES, Case, Model, Planner, State, aggregate,
                       canonical, manifest_spec, preference_next, rational, root, run, suite)


class Contracts(unittest.TestCase):
    def solve(self, c: Case, arm: str = "bellman_neutral"):
        p = Planner(c, arm)
        return p.solve(root(c)), p.policy[root(c).key()], p

    def test_01_fraction_inputs_reject_boolean_float(self):
        for x in (True, 0.5, float('nan'), None):
            with self.subTest(x=x), self.assertRaises(ValueError):
                rational(x)
        self.assertEqual(rational('1/2'), Q(1, 2))

    def test_02_case_rejects_invalid_bounds(self):
        for change in ({'budget': -1}, {'budget': True}, {'deadline': 17}, {'episodes': 0},
                       {'p0': Q(2)}, {'price': Q(-1)}, {'initial_preference': Q(3, 4)},
                       {'sensors': ('bit0','bit0')}, {'duplicate_hints': 1}):
            with self.subTest(change=change), self.assertRaises(ValueError):
                Case('invalid', **change)

    def test_03_case_wire_roundtrip(self):
        for c in suite():
            self.assertEqual(Case.from_wire(c.wire()), c)

    def test_04_world_law_is_normalized(self):
        for c in suite():
            self.assertEqual(sum(w[0] for w in Model(c).worlds), 1)

    def test_05_invalid_and_duplicate_action_rejected(self):
        m=Model(suite()[0]); s=root(m.case)
        with self.assertRaises(ValueError): m.transitions(s, 'read_future_label')
        nxt=m.transitions(s, 'bit0')[0][2]
        with self.assertRaises(ValueError): m.transitions(nxt, 'bit0')

    def test_06_impossible_history_rejected(self):
        m=Model(Case('degenerate', p0=Q(0)))
        with self.assertRaises(ValueError): m.posterior((('bit0',1),))

    def test_07_exact_xor_complementarity(self):
        v,a,_=self.solve(suite()[0])
        self.assertEqual((v,a),(Q(21,25),'bit0'))
        for arm in ('no_compute','myopic_voi'):
            self.assertEqual(self.solve(suite()[0],arm)[0],Q(1,2))

    def test_08_and_short_circuit_cost(self):
        c=suite()[4]; v,_,p=self.solve(c)
        result=Reference(c).replay(p.policy,'neutral')
        self.assertEqual(v,Q(22,25))
        self.assertEqual(result.tokens,3)
        self.assertEqual(result.success,1)

    def test_09_budget_three_cannot_complete_xor(self):
        self.assertEqual(self.solve(suite()[1])[0],Q(1,2))

    def test_10_deadline_is_independent_of_token_budget(self):
        self.assertEqual(self.solve(suite()[3])[:2],(Q(1,2),'submit0'))
        self.assertEqual(self.solve(replace(suite()[0],deadline=0))[:2],(Q(0),'quit'))

    def test_11_resource_shadow_marginals_are_discrete(self):
        values=[self.solve(replace(suite()[0],budget=b))[0] for b in range(6)]
        self.assertEqual([b-a for a,b in zip(values,values[1:])],
                         [Q(0),Q(0),Q(0),Q(17,50),Q(0)])

    def test_12_duplicate_is_not_new_evidence(self):
        c=suite()[5]; m=Model(c)
        first=m.posterior((('hint0',0),))
        again=m.posterior((('hint0',0),('hint1',0)))
        self.assertEqual(first,again)
        with self.assertRaises(ValueError): m.posterior((('hint0',0),('hint1',1)))

    def test_13_conditional_error_covariance_not_embedding_similarity(self):
        def covariance(c):
            worlds=Model(c).worlds
            mean0=sum(p*int(sig[2]!=t) for p,t,sig in worlds)
            mean1=sum(p*int(sig[3]!=t) for p,t,sig in worlds)
            both=sum(p*int(sig[2]!=t)*int(sig[3]!=t) for p,t,sig in worlds)
            return both-mean0*mean1
        self.assertEqual(covariance(suite()[5]),Q(3,16))
        self.assertEqual(covariance(suite()[6]),0)

    def test_14_independence_does_not_guarantee_two_vote_gain(self):
        for c in suite()[5:7]:
            v,_,p=self.solve(c)
            self.assertEqual(v,Q(71,100))
            self.assertEqual(Reference(c).replay(p.policy,'neutral').tokens,1)

    def test_15_price_is_not_charged_twice(self):
        c=suite()[0]; v,_,p=self.solve(c)
        r=Reference(c).replay(p.policy,'neutral')
        self.assertEqual((r.success,r.fees,r.tokens),(Q(1),Q(4,25),Q(4)))
        self.assertEqual(v,r.success-r.fees)

    def test_16_expensive_information_rejected(self):
        self.assertEqual(self.solve(suite()[9])[:2],(Q(1,2),'submit0'))

    def test_17_one_task_investment_rejected(self):
        self.assertEqual(self.solve(suite()[10])[:2],(Q(21,25),'bit0'))

    def test_18_three_task_investment_selected(self):
        c=suite()[11]; v,a,p=self.solve(c); r=Reference(c).replay(p.policy,'neutral')
        self.assertEqual((v,a),(Q(261,100),'invest'))
        self.assertEqual((r.success,r.investments,r.tokens),(Q(3),Q(1),Q(8)))

    def test_19_expensive_investment_rejected(self):
        c=suite()[12]; v,a,p=self.solve(c)
        self.assertEqual(v,Q(109,50))
        self.assertNotEqual(a,'invest')
        self.assertEqual(Reference(c).replay(p.policy,'neutral').investments,0)

    def test_20_resource_shock_counts_as_loss_not_fee(self):
        c=suite()[13]; _,_,p=self.solve(c); r=Reference(c).replay(p.policy,'neutral')
        self.assertLessEqual(r.tokens+r.shock_loss,c.budget)
        self.assertGreater(r.shock_loss,0)
        self.assertEqual(r.utility,r.success-r.fees)

    def test_21_investment_is_single_and_persistent(self):
        c=suite()[11]; m=Model(c); nxt=m.transitions(root(c),'invest')[0][2]
        self.assertTrue(nxt.trained)
        self.assertNotIn('invest',m.actions(nxt))
        after=m.transitions(nxt,'submit0')[0][2]
        self.assertTrue(after.trained)
        self.assertEqual(m.cost(after,'bit0')[0],1)

    def test_22_preference_update_bounded_observed_outcome(self):
        self.assertEqual(preference_next(Q(1,4),0),Q(1,2))
        self.assertEqual(preference_next(Q(1,4),1),Q(1,8))
        self.assertEqual(preference_next(Q(0),1),0)
        self.assertEqual(preference_next(Q(1,2),0),Q(1,2))

    def test_23_preference_is_not_changed_by_purchased_observation(self):
        c=suite()[11]; m=Model(c)
        for _,_,nxt in m.transitions(root(c),'bit0'):
            self.assertEqual(nxt.preference,c.initial_preference)

    def test_24_recursive_aggregator_constant_and_translation(self):
        rows=((Q(1,4),Q(-2)),(Q(3,4),Q(3)))
        for alpha in (Q(0),Q(1,4),Q(1,2)):
            self.assertEqual(aggregate(((Q(1),Q(4)),),alpha),4)
            self.assertEqual(aggregate(tuple((p,v+7) for p,v in rows),alpha),aggregate(rows,alpha)+7)

    def test_25_recursive_aggregator_monotone(self):
        for a in range(5):
            alpha=Q(a,8)
            self.assertLessEqual(aggregate(((Q(1,2),Q(0)),(Q(1,2),Q(1))),alpha),
                                 aggregate(((Q(1,2),Q(1)),(Q(1,2),Q(1))),alpha))

    def test_26_invalid_recursive_law_rejected(self):
        for rows in ((),((Q(0),Q(0)),),((Q(1,2),Q(0)),)):
            with self.assertRaises(ValueError): aggregate(rows,Q(1,4))

    def test_27_exact_independent_oracle_all_profiles(self):
        # 15 cases x 3 profiles. No fit or sampled accuracy claim.
        for c in suite():
            ref=Reference(c)
            for arm,profile in zip(ARMS[2:],PROFILES):
                with self.subTest(case=c.name,profile=profile):
                    v,_,p=self.solve(c,arm)
                    self.assertEqual(v,ref.best(root(c),profile)[0])
                    self.assertEqual(v,ref.replay(p.policy,profile).utility)

    def test_28_public_keys_do_not_contain_future_truth(self):
        c=suite()[7]; _,_,p=self.solve(c)
        for key in p.policy:
            row=json.loads(key)
            self.assertEqual(len(row),6)
            self.assertNotIn('target',key)
        self.assertEqual(public_key(root(c)),root(c).key())

    def test_29_fixed_and_endogenous_are_not_same_objective(self):
        c=suite()[14]; _,_,p=self.solve(c,'ndu_discrete'); ref=Reference(c)
        self.assertNotEqual(ref.replay(p.policy,'fixed').utility,ref.replay(p.policy,'endogenous').utility)

    def test_30_unknown_arm_rejected(self):
        with self.assertRaises(ValueError): Planner(suite()[0],'pretend_fbsde')


class Evidence(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp=tempfile.TemporaryDirectory()
        cls.directory=Path(cls.tmp.name)/'baseline'
        with contextlib.redirect_stdout(io.StringIO()): run(cls.directory)
        cls.manifest=json.loads((cls.directory/'manifest.json').read_text())
        cls.sealed=json.loads((cls.directory/'policies.json').read_text())

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def rejected(self, mutate):
        with tempfile.TemporaryDirectory() as tmp:
            folder=Path(tmp)
            m,p=copy.deepcopy(self.manifest),copy.deepcopy(self.sealed)
            mutate(m,p)
            (folder/'manifest.json').write_bytes(canonical(m))
            (folder/'policies.json').write_bytes(canonical(p))
            with self.assertRaises(ValueError): audit(folder,folder/'audit.json')

    def test_31_separate_replay_full_panel(self):
        report=audit(self.directory,Path(self.tmp.name)/'accepted.json')
        self.assertEqual(report['audited_policy_rows'],75)
        self.assertEqual(report['same_profile_oracle_equalities'],45)
        self.assertFalse(report['observed_neural_training'])
        self.assertFalse(report['model_efficacy_established'])
        self.assertTrue(all(Q(r['neutral_regret']) >= 0 for r in report['rows']))

    def test_32_root_value_tamper(self):
        self.rejected(lambda m,p:p['rows'][0].update(root_value='999'))

    def test_33_missing_policy_row(self):
        self.rejected(lambda m,p:p['rows'].pop())

    def test_34_duplicate_policy_row(self):
        self.rejected(lambda m,p:p['rows'].append(p['rows'][0]))

    def test_35_source_binding_tamper(self):
        self.rejected(lambda m,p:p['source_sha256'].update({'portfolio.py':'0'*64}))

    def test_36_objective_drift(self):
        self.rejected(lambda m,p:m.update(objective='maximize self score'))

    def test_37_synthetic_training_not_real_training(self):
        self.rejected(lambda m,p:m.update(real_optimizer_steps=1))

    def test_38_budget_bypass_in_policy(self):
        def mutate(m,p):
            row=next(r for r in p['rows'] if r['case']=='xor-no-compute' and r['arm']=='no_compute')
            key=next(iter(row['policy']))
            row['policy'][key]='bit0';row['root_action']='bit0'
        self.rejected(mutate)

    def test_39_missing_reachable_action(self):
        self.rejected(lambda m,p:p['rows'][0]['policy'].clear())

    def test_40_fabricated_authority(self):
        self.rejected(lambda m,p:p.update(posture='PRODUCTION'))

    def test_41_manifest_rule_tamper_even_with_rehash(self):
        import hashlib
        def mutate(m,p):
            m['preference_rule']='change goal'
            p['manifest_sha256']=hashlib.sha256(canonical(m)).hexdigest()
        self.rejected(mutate)

    def test_42_duplicate_json_keys_rejected(self):
        path=Path(self.tmp.name)/'duplicate.json';path.write_text('{"a":1,"a":2}')
        with self.assertRaises(ValueError): strict_load(path)

    def test_43_exclusive_output_no_overwrite(self):
        before=(self.directory/'manifest.json').read_bytes()
        with self.assertRaises(FileExistsError): run(self.directory)
        self.assertEqual((self.directory/'manifest.json').read_bytes(),before)

    def test_44_manifest_roundtrip_exact(self):
        self.assertEqual(self.manifest,manifest_spec())


if __name__=='__main__':
    unittest.main()
