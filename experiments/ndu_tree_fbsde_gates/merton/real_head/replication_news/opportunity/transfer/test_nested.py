"""Original-archive numerical and adversarial nested-exclusion regressions."""
from __future__ import annotations

import contextlib
import copy
import io
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import numpy as np

from nested import (Head, config, encode, fit_prior, groups, lifecycle, loads,
                    prepare, read_worker, run, sha, sources, POSTURE)
from audit_nested import audit, forecast_score, partition


class Nested(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.archive=Path(os.environ['NEWS_ARCHIVE'])
        cls.tmp=tempfile.TemporaryDirectory();cls.root=Path(cls.tmp.name)
        cls.material=cls.root/'material';prepare(cls.archive,cls.material)
        cls.manifest=loads((cls.material/'manifest.json').read_bytes())
        cls.a=read_worker(cls.material/'fold-0/worker.npz',cls.manifest['folds'][0]['worker_sha256'])
        cls.prior=fit_prior(cls.a)
        cls.runs=cls.root/'runs'
        with contextlib.redirect_stdout(io.StringIO()):
            for f,rec in enumerate(cls.manifest['folds']):
                run(cls.material/f'fold-{f}/worker.npz',rec['worker_sha256'],cls.runs/f'fold-{f}')
        cls.result=audit(cls.archive,cls.material,cls.runs,cls.root/'audited.json')

    @classmethod
    def tearDownClass(cls):cls.tmp.cleanup()

    def mutate_worker(self, fn):
        a={k:v.copy() for k,v in self.a.items()};fn(a)
        p=self.root/'changed-worker.npz'
        with p.open('wb') as f:np.savez(f,**a)
        return p,sha(p.read_bytes())

    def rejected(self, fn):
        import shutil
        with tempfile.TemporaryDirectory() as t:
            root=Path(t);m=root/'material';r=root/'runs'
            shutil.copytree(self.material,m);shutil.copytree(self.runs,r)
            fn(m,r)
            with self.assertRaises(ValueError):audit(self.archive,m,r,root/'audit.json')

    def reseal(self, r, name, fn):
        folder=r/'fold-0';obj=loads((folder/name).read_bytes());fn(obj)
        (folder/name).write_bytes(encode(obj))
        s=loads((folder/'sealed.json').read_bytes())
        field={'prior.json':'prior_sha256','forecast.json':'forecast_sha256','diagnostic.json':'diagnostic_sha256'}[name]
        s[field]=sha((folder/name).read_bytes());(folder/'sealed.json').write_bytes(encode(s))

    def test_01_outer_unique_full_exclusion(self):
        held=[]
        for f in self.manifest['folds']:
            self.assertEqual(len(f['fit_ids']),48);self.assertEqual(len(f['eval_ids']),16)
            self.assertFalse(set(f['fit_ids'])&set(f['eval_ids']));held+=f['eval_ids']
        self.assertEqual(len(set(held)),64)
        self.assertFalse(set(held)&set(self.manifest['excluded_original_holdout_ids']))

    def test_02_inner_does_not_touch_outer(self):
        ids=self.a['fit_ids'].tolist()
        for valid in groups(ids,3,'inner'):
            train=[i for i in range(48) if i not in valid]
            self.assertEqual((len(train),len(valid)),(32,16))
            self.assertFalse({ids[i] for i in train+valid}&set(self.a['eval_ids']))

    def test_03_assignment_ignores_label_changes(self):
        ids=self.a['fit_ids'].tolist();old=groups(ids,3,'inner')
        altered=self.a['fit_y'].copy();altered[:]=(altered+1)%4
        self.assertFalse(np.array_equal(altered,self.a['fit_y']))
        self.assertEqual(groups(ids,3,'inner'),old)
        self.assertEqual([tuple(x) for x in old],partition(ids,3,'inner'))

    def test_04_worker_excludes_labels(self):
        p,d=self.mutate_worker(lambda a:a.update(eval_y=np.zeros(16,dtype=int)))
        with self.assertRaises(ValueError):read_worker(p,d)

    def test_05_changed_digest_rejected(self):
        with self.assertRaises(ValueError):read_worker(self.material/'fold-0/worker.npz','0'*64)

    def test_06_role_overlap_rejected(self):
        p,d=self.mutate_worker(lambda a:a['eval_ids'].__setitem__(0,a['fit_ids'][0]))
        with self.assertRaises(ValueError):read_worker(p,d)

    def test_07_nonfinite_features(self):
        p,d=self.mutate_worker(lambda a:a['fit_x'].__setitem__((0,0),np.nan))
        with self.assertRaises(ValueError):read_worker(p,d)

    def test_08_invalid_labels(self):
        p,d=self.mutate_worker(lambda a:a['fit_y'].__setitem__(0,4))
        with self.assertRaises(ValueError):read_worker(p,d)

    def test_09_target_features_do_not_change_prior(self):
        b={k:v.copy() for k,v in self.a.items()};b['eval_x'][:]=1e20
        changed=fit_prior(b)
        for k in ('curves','fits','actual_updates','scoring_calls'):self.assertEqual(changed[k],self.prior[k])

    def test_10_cal_labels_do_not_change_prior(self):
        b={k:v.copy() for k,v in self.a.items()};b['cal_y'][:]=(b['cal_y']+1)%4
        changed=fit_prior(b)
        self.assertEqual(changed['fits'],self.prior['fits'])

    def test_11_zero_gradients_for_fixed0(self):
        with patch.object(Head,'step',side_effect=AssertionError('unpaid gradient')):
            r=lifecycle(self.a,self.prior,'fixed0',config()['scenarios'][0],lambda e:None)
        self.assertEqual(r['actual_updates'],0)

    def test_12_exact_fixed8_counter(self):
        seen=[];old=Head.step
        def counting(h):seen.append(h.updates);old(h)
        with patch.object(Head,'step',counting):r=lifecycle(self.a,self.prior,'fixed8',config()['scenarios'][0],lambda e:None)
        self.assertEqual(seen,list(range(8)));self.assertEqual(r['actual_updates'],8)
        self.assertEqual(r['calibration_calls'],0)

    def test_13_budget_and_invalid_target(self):
        h=Head(self.a['fit_x'],self.a['fit_y'],7)
        for target in (8,True,-1,256):
            with self.subTest(target=target),self.assertRaises(ValueError):h.advance(target)
        self.assertEqual(h.updates,0)

    def test_14_cannot_predict_future_checkpoint(self):
        h=Head(self.a['fit_x'],self.a['fit_y'])
        with self.assertRaises(ValueError):h.predict(self.a['eval_x'],8)

    def test_15_zero_returns_uniform(self):
        h=Head(self.a['fit_x'],self.a['fit_y'])
        self.assertTrue(np.array_equal(h.predict(self.a['eval_x']),np.full((16,4),.25)))

    def test_16_source_shape_not_silently_promoted(self):
        for n in (16,64):
            with self.subTest(n=n),self.assertRaises(ValueError):Head(np.zeros((n,384)),np.zeros(n,dtype=int))

    def test_17_full_separate_replay(self):
        self.assertEqual(self.result['verified_folds'],4)
        self.assertEqual(self.result['policy_lifecycles'],20)
        self.assertEqual(self.result['prior_updates'],1536)
        self.assertEqual(self.result['diagnostic_updates'],512)
        self.assertEqual(self.result['forecast_coordinate_count'],16)

    def test_18_negative_claims(self):
        self.assertFalse(self.result['transfer_qualified']);self.assertFalse(self.result['production_accepted'])
        self.assertFalse(self.result['original_holdout_used']);self.assertEqual(self.result['new_sources'],0)
        self.assertIsNone(self.result['independent_task_family_count'])

    def test_19_forecast_distribution_normalized(self):
        from fractions import Fraction as Q
        for c in self.result['forecasts']:
            self.assertEqual(sum(Q(p) for p in c['predictive_count_mass']),1)
            self.assertTrue(0<=c['model_interval95_counts'][0]<=c['model_interval95_counts'][1]<=16)

    def test_20_resealed_prior_weight_tamper(self):
        def mutate(m,r):self.reseal(r,'prior.json',lambda p:p['fits'][0]['checkpoints']['8'][0].__setitem__(0,99))
        self.rejected(mutate)

    def test_21_resealed_future_prediction_tamper(self):
        def mutate(m,r):self.reseal(r,'diagnostic.json',lambda p:p['probabilities']['8'][0].__setitem__(0,.99))
        self.rejected(mutate)

    def test_22_resealed_forecast_tamper(self):
        def mutate(m,r):self.reseal(r,'forecast.json',lambda p:p['prior_rates']['8'].__setitem__(0,1.0))
        self.rejected(mutate)

    def test_23_outer_label_change_does_not_change_worker(self):
        worker=self.material/'fold-0/worker.npz';before=worker.read_bytes()
        path=self.material/'fold-0/labels.json';old=path.read_bytes()
        try:
            labels=loads(old);key=next(iter(labels));labels[key]=(labels[key]+1)%4;path.write_bytes(encode(labels))
            self.assertEqual(worker.read_bytes(),before)
            self.assertEqual(read_worker(worker,sha(before))['fit_y'].tolist(),self.a['fit_y'].tolist())
            with self.assertRaises(ValueError):audit(self.archive,self.material,self.runs,self.root/'badlabel-audit.json')
        finally:path.write_bytes(old)

    def test_24_missing_row(self):
        def mutate(m,r):
            p=r/'fold-0/sealed.json';s=loads(p.read_bytes());s['rows'].pop();p.write_bytes(encode(s))
        self.rejected(mutate)

    def test_25_fabricated_new_sources(self):
        def mutate(m,r):
            p=r/'fold-0/sealed.json';s=loads(p.read_bytes());s['new_sources']=64;p.write_bytes(encode(s))
        self.rejected(mutate)

    def test_26_incorrect_cost_counter(self):
        def mutate(m,r):
            p=r/'fold-0/sealed.json';s=loads(p.read_bytes());s['diagnostic_updates']=0;p.write_bytes(encode(s))
        self.rejected(mutate)

    def test_27_failure_has_no_success_seal(self):
        dst=self.root/'injected-failure';rec=self.manifest['folds'][0]
        with patch.object(Head,'step',side_effect=RuntimeError('injected')):
            with self.assertRaises(RuntimeError):run(self.material/'fold-0/worker.npz',rec['worker_sha256'],dst)
        self.assertFalse((dst/'sealed.json').exists())
        self.assertEqual(loads((dst/'journal.jsonl').read_bytes().splitlines()[-1])['kind'],'failure')

    def test_28_outputs_cannot_overwrite(self):
        rec=self.manifest['folds'][0]
        with self.assertRaises(FileExistsError):run(self.material/'fold-0/worker.npz',rec['worker_sha256'],self.runs/'fold-0')

    def test_29_original_excluded_holdout_stays_excluded(self):
        excluded=set(self.manifest['excluded_original_holdout_ids'])
        for f in self.manifest['folds']:self.assertFalse(excluded&set(f['fit_ids']+f['eval_ids']))

    def test_30_step0_forecast_not_reported_as_trained(self):
        for row in self.result['forecasts']:
            if row['step']==0:self.assertEqual(row['observed_correct'],sum(
                v==0 for v in loads((self.material/f"fold-{row['fold']}"/'labels.json').read_bytes()).values()))

    def test_31_sample_size_transfer_explicit(self):
        p=config();self.assertEqual((p['prior_fit_rows'],p['target_fit_rows']),(32,48))
        self.assertEqual(p['posture'],POSTURE)
        self.assertTrue(all(r['denominator']==64 for r in self.result['summaries']))

    def test_32_strict_partition_rejects_bad_input(self):
        for ids,n in ((['x']*48,3),(['a','b'],3),([1,2,3],3)):
            with self.assertRaises(ValueError):groups(ids,n,'inner')


if __name__=='__main__':unittest.main()
