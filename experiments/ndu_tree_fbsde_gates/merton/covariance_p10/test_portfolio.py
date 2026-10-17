"""P10 source-only exact finite and independent-oracle falsification tests.

Constructed models, not physical model/effect outcomes. Additional source-pinned
original P5 audit is a separate mandatory workflow step after these checks.
"""
from __future__ import annotations

import copy
import json
import tempfile
import unittest
from fractions import Fraction as F
from pathlib import Path

import independent_audit as reviewer
import portfolio as producer


def fixture():
    """All values synthetic; exact paired actions are deliberately correlated."""
    train=[];calls=[];pairs=[]
    for i in range(16):
        tid=f'train-{i:05}'
        truth=i%4
        text=f'Synthetic training news passage {i}, category words '+('x'*26)+'.'
        actions={}
        for action in producer.ACTIONS:
            correct=(i%3==0) if action=='direct' else ((i%4 in (0,1)) if action=='verify'
                else (i%4==3))
            tokens=111 if action=='direct' else 203 if action=='reason' else 131
            row={'correct':int(correct),'tokens':tokens,'source_id':tid}
            actions[action]=row
            calls.append({'task_id':tid,'policy':'train','source_kind':'original_physical',
                'action':action,'predicted_class':truth if correct else (truth+1)%4,
                'input_tokens':tokens-4,'output_tokens':4,'thinking_mode':action=='reason'})
        train.append({'task_id':tid,'label':truth,'text':text,
                      'text_sha256':producer.sha(text.encode()),'bucket':'short','group':'train-row-parity-'+str(i%2)})
        pairs.append({'id':tid,'label':truth,'bucket':'short','actions':actions})
    held=[]
    for i in range(16):
        tid=f'held-{i:05}';text=f'Synthetic held news text {i} '+('w'*60)
        held.append({'task_id':tid,'text':text,'text_sha256':producer.sha(text.encode()),
                     'bucket':'short','group':'held-row-parity-'+str(i%2)})
    return ({'schema':'hepta.ndu-merton.p5.class-balanced-agnews-source.v1.train','rows':train},
            {'schema':'hepta.ndu-merton.p5.class-balanced-agnews-source.v1.held-public','rows':held},
            {'original_train_trace':calls},pairs)


class CovarianceBasics(unittest.TestCase):
    def test_01_exact_sample_moments_and_symmetry(self):
        pairs=fixture()[3]
        stats=producer.moments(pairs)
        self.assertEqual(stats['n'],16)
        self.assertEqual(stats['cov'][0][1],stats['cov'][1][0])
        self.assertGreaterEqual(stats['det'],0)

    def test_02_real_paired_variation_not_independent_marginals(self):
        stats=producer.moments(fixture()[3])
        self.assertNotEqual(stats['cov'][0][1],0)

    def test_03_prior_sample_regression_is_not_bsde(self):
        pairs=fixture()[3];stat=producer.moments(pairs)
        ans=producer.conditional_regression_sample(pairs,stat)
        self.assertTrue(ans is None or len(ans)==2)

    def test_04_singular_sample_covariance_returns_unavailable(self):
        rows=fixture()[3]
        for row in rows:
            for action in producer.ALTS:
                row['actions'][action]['correct']=row['actions']['direct']['correct']
                row['actions'][action]['tokens']=row['actions']['direct']['tokens']
        m=producer.moments(rows)
        self.assertEqual(m['det'],0)
        self.assertIsNone(producer.conditional_regression_sample(rows,m))

    def test_05_risk_penalty_is_nonnegative_for_psd_covariance(self):
        m=producer.moments(fixture()[3]);a,b=5,7
        self.assertLessEqual(producer.objective(a,b,m,'covariance'),producer.objective(a,b,m,'neutral'))

    def test_06_real_covariance_can_change_optimal_surrogate_allocation(self):
        m={'mu':(F(1,20),F(1,20)), 'cov':((F(1,4),F(-1,8)),(F(-1,8),F(1,4)))}
        self.assertNotEqual(producer.choose(m,'diagonal')[:2],producer.choose(m,'covariance')[:2])

    def test_07_no_action_receives_better_no_change_score(self):
        m=producer.moments(fixture()[3]);self.assertEqual(producer.choose(m,'direct'),(0,0,F(0)))

    def test_08_unregistered_risk_profile_fails(self):
        m=producer.moments(fixture()[3])
        with self.assertRaises(ValueError):producer.choose(m,'unknown')

    def test_09_out_of_simplex_fails(self):
        m=producer.moments(fixture()[3])
        with self.assertRaises(ValueError):producer.objective(10,10,m,'covariance')
        with self.assertRaises(ValueError):producer.objective(True,0,m,'covariance')

    def test_10_no_unpaired_action_in_training(self):
        pairs=fixture()[3]
        del pairs[0]['actions']['reason']
        with self.assertRaises(ValueError):producer.moments(pairs)

    def test_11_duplicate_training_identity_rejected(self):
        pairs=fixture()[3]
        pairs[1]['id']=pairs[0]['id']
        with self.assertRaises(ValueError):producer.moments(pairs)

    def test_12_bad_training_score_or_token_rejected(self):
        pairs=fixture()[3];pairs[2]['actions']['direct']['correct']=True
        with self.assertRaises(ValueError):producer.moments(pairs)
        pairs=fixture()[3];pairs[2]['actions']['direct']['tokens']=0
        with self.assertRaises(ValueError):producer.moments(pairs)


class IndependentFiniteControl(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.train,cls.held,cls.original,cls.pairs=fixture()
        cls.plan=producer.frozen_plan(cls.pairs,cls.held)

    def test_13_source_only_plan_contains_no_held_truth(self):
        self.assertFalse(self.plan['held_labels_seen'])
        self.assertTrue(all('label' not in x for x in self.held['rows']))

    def test_14_independent_optimizer_parity(self):
        stats=reviewer.recheck_plan(self.plan,self.train,self.held,self.original)
        self.assertEqual(stats['cov'][0][1],producer.moments(self.pairs)['cov'][0][1])

    def test_15_resealed_allocation_forgery_fails(self):
        fake=copy.deepcopy(self.plan)
        fake['policies']['covariance']['actions']['held-00000']='reason'
        fake['seal_sha256']=producer.digest({k:v for k,v in fake.items() if k!='seal_sha256'})
        with self.assertRaises(ValueError):reviewer.recheck_plan(fake,self.train,self.held,self.original)

    def test_16_resealed_covariance_forgery_fails(self):
        fake=copy.deepcopy(self.plan)
        fake['moment_covariance'][0][1]='0'
        fake['seal_sha256']=producer.digest({k:v for k,v in fake.items() if k!='seal_sha256'})
        with self.assertRaises(ValueError):reviewer.recheck_plan(fake,self.train,self.held,self.original)

    def test_17_identity_based_wrong_risk_cannot_be_resealed(self):
        fake=copy.deepcopy(self.plan)
        fake['gamma']['covariance']='0'
        fake['seal_sha256']=producer.digest({k:v for k,v in fake.items() if k!='seal_sha256'})
        with self.assertRaises(ValueError):reviewer.recheck_plan(fake,self.train,self.held,self.original)

    def test_18_foreign_model_run_id_rejected(self):
        fake=copy.deepcopy(self.plan)
        fake['origin_run_id']=123
        fake['seal_sha256']=producer.digest({k:v for k,v in fake.items() if k!='seal_sha256'})
        with self.assertRaises(ValueError):reviewer.recheck_plan(fake,self.train,self.held,self.original)

    def test_19_no_claim_flags_cannot_be_stripped(self):
        fake=copy.deepcopy(self.plan);fake['no_claims']=[]
        fake['seal_sha256']=producer.digest({k:v for k,v in fake.items() if k!='seal_sha256'})
        with self.assertRaises(ValueError):reviewer.recheck_plan(fake,self.train,self.held,self.original)

    def test_20_held_truth_injected_into_public_fails(self):
        altered=copy.deepcopy(self.held);altered['rows'][0]['label']=0
        with self.assertRaises(ValueError):producer.frozen_plan(self.pairs,altered)
        with self.assertRaises(ValueError):reviewer.recheck_plan(self.plan,self.train,altered,self.original)

    def test_21_held_text_changed_even_with_updated_digest_fails(self):
        altered=copy.deepcopy(self.held);altered['rows'][0]['text']+=' altered'
        altered['rows'][0]['text_sha256']=producer.sha(altered['rows'][0]['text'].encode())
        with self.assertRaises(ValueError):reviewer.recheck_plan(self.plan,self.train,altered,self.original)

    def test_22_wrong_trained_predictions_fail_second_oracle(self):
        altered=copy.deepcopy(self.original)
        altered['original_train_trace'][0]['predicted_class']=1 if altered['original_train_trace'][0]['predicted_class']==0 else 0
        with self.assertRaises(ValueError):reviewer.recheck_plan(self.plan,self.train,self.held,altered)

    def test_23_producer_never_uses_held_truth(self):
        altered=copy.deepcopy(self.held)
        altered['rows'][0]['label']=0
        with self.assertRaises(ValueError):producer.frozen_plan(self.pairs,altered)

    def test_24_no_change_and_matched_profile_required(self):
        self.assertTrue(all(a=='direct' for a in self.plan['policies']['direct']['actions'].values()))
        self.assertEqual(self.plan['policies']['covariance'],self.plan['policies']['ordinary_same_profile'])

    def test_25_true_training_action_census_rejects_duplicate(self):
        altered=copy.deepcopy(self.original)
        altered['original_train_trace'][0]=altered['original_train_trace'][1]
        with self.assertRaises(ValueError):reviewer.training_statistics(self.train,altered)


class SecurityAndArtifactTests(unittest.TestCase):
    def test_26_duplicate_json_key_rejected(self):
        with self.assertRaises(ValueError):producer.parse(b'{"x":1,"x":2}')
        with self.assertRaises(ValueError):reviewer._decode(b'{"x":1,"x":2}')

    def test_27_nonfinite_json_rejected(self):
        with self.assertRaises(ValueError):producer.parse(b'{"x":NaN}')
        with self.assertRaises(ValueError):reviewer._decode(b'{"x":Infinity}')

    def test_28_missing_original_pinned_artifacts_fail_closed(self):
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(ValueError):producer.verified_read(Path(d))
            with self.assertRaises(ValueError):reviewer.load(Path(d))

    def test_29_fake_original_digest_fails_closed(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)
            for name,path in producer.evidence_paths(root).items():
                if name=='held-private-labels.json':continue
                path.parent.mkdir(parents=True,exist_ok=True)
                path.write_text('{}',encoding='utf-8')
            with self.assertRaises(ValueError):producer.verified_read(root)

    def test_30_no_overwrite_audited_candidate_file(self):
        with tempfile.TemporaryDirectory() as d:
            target=Path(d)/'frozen.json'
            producer.no_overwrite(target,{'authority':'DENY_ALL'})
            with self.assertRaises(FileExistsError):producer.no_overwrite(target,{'authority':'DENY_ALL'})

    def test_31_independent_origin_requires_paid_calls(self):
        train,held,origin,pairs=fixture()
        origin['original_train_trace'][0]['source_kind']='synthetic_fixture'
        with self.assertRaises(ValueError):reviewer.training_statistics(train,origin)

    def test_32_actual_original_regression_is_not_a_fbsde(self):
        # Boundary: no reason to infer stochastic existence/uniqueness from OLS.
        self.assertIn('empirical_ols_z_not_bsde',producer.frozen_plan(fixture()[3],fixture()[1]))


if __name__=='__main__':unittest.main()
