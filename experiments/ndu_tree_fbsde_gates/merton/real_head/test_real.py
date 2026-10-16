"""Source-backed regressions. Missing original archives are failures, not skips."""
import copy
import math
import os
import tempfile
import unittest
from fractions import Fraction as Q
from pathlib import Path
from material import LOCKS, canonical, load_sources, prepare, sha, strict_loads, write_new
from learning import (ARMS,HORIZONS,STEPS,alpha_from,augmented_select,execute,feature,fit,
                      full_questions,predict,select,sigmoid,validate_fold)
from audit_real import check_row,close,ref_fit,ref_predict

class RealHeadTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.paths={k:Path(os.environ['HEPTA_MERTON_ASSETS'])/(str(v[0])+'.zip') for k,v in LOCKS.items()}
        cls.rows,cls.labels,cls.provenance=load_sources(cls.paths)
        cls.tmp=tempfile.TemporaryDirectory();cls.folder=Path(cls.tmp.name)/'material'
        prepare(cls.paths,cls.folder)
        cls.fold=strict_loads((cls.folder/'fold-0.json').read_bytes())
        cls.search=execute(cls.fold,'ndu_discrete',8)

    @classmethod
    def tearDownClass(cls):cls.tmp.cleanup()

    def test_01_original_source_census(self):
        self.assertEqual((len(self.rows),len(self.labels)),(33,33))
        self.assertEqual(len({r['group'] for r in self.rows}),4)
        self.assertEqual(len({(r['group'],r['question']) for r in self.rows}),8)

    def test_02_human_label_lineage(self):
        self.assertEqual(self.provenance['label_source_sha256'],'5eb64893afc5af7828b2f3b41d6a4574eb7a82cbb17c86c75842f5f95f679ada')
        self.assertFalse(self.provenance['new_download_of_original_parquet'])

    def test_03_original_archive_tamper(self):
        with tempfile.TemporaryDirectory() as t:
            p=Path(t)/'bad.zip';p.write_bytes(self.paths['reader'].read_bytes()+b'bad')
            with self.assertRaises(ValueError):load_sources(dict(self.paths,reader=p))

    def test_04_split_has_no_held_labels(self):
        for i in range(4):
            f=strict_loads((self.folder/f'fold-{i}.json').read_bytes());validate_fold(f)
            self.assertTrue(all('label' not in r for r in f['held_inputs']))
            self.assertNotIn(f['held_group'],{r['group'] for r in f['train']})

    def test_05_reject_held_label_injection(self):
        f=copy.deepcopy(self.fold);f['held_inputs'][0]['label']=0
        with self.assertRaises(ValueError):validate_fold(f)

    def test_06_reject_group_leak(self):
        f=copy.deepcopy(self.fold);f['train'][0]['group']=f['held_group']
        with self.assertRaises(ValueError):validate_fold(f)

    def test_07_reject_duplicate_id(self):
        f=copy.deepcopy(self.fold);f['train'][0]['id']=f['held_inputs'][0]['id']
        with self.assertRaises(ValueError):validate_fold(f)

    def test_08_reject_nonfinite_feature(self):
        f=copy.deepcopy(self.fold);f['held_inputs'][0]['x'][0]=float('nan')
        with self.assertRaises(ValueError):validate_fold(f)

    def test_09_query_centering_does_not_use_labels(self):
        for g,q in {(r['group'],r['question']) for r in self.rows}:
            rows=[r for r in self.rows if (r['group'],r['question'])==(g,q)]
            for j in range(4):self.assertAlmostEqual(sum(r['x'][j] for r in rows),0,places=12)

    def test_10_zero_steps_reads_no_labels(self):
        h,r=fit(None,0);self.assertEqual(h['weights'],[0.0]*5)
        self.assertEqual((r['steps'],r['train_ids'],r['loss_trace']),(0,[],[]))

    def test_11_zero_head_matches_frozen(self):
        h,_=fit(None,0)
        self.assertEqual(predict(h,self.rows),[sigmoid(r['base']) for r in self.rows])

    def test_12_actual_parameters_change(self):
        h,r=fit(self.fold['train'],32)
        self.assertTrue(any(x!=0 for x in h['weights']))
        self.assertEqual(len(r['loss_trace']),32)
        self.assertGreater(r['cpu_ns'],0)

    def test_13_train_only_scaling(self):
        a,_=fit(self.fold['train'],8);f=copy.deepcopy(self.fold)
        for r in f['held_inputs']:r['x']=[1e5]*4
        b,_=fit(f['train'],8);self.assertEqual(a,b)

    def test_14_independent_SGD_all_checkpoints(self):
        for n in STEPS:
            h,r=fit(self.fold['train'],n);ref,trace=ref_fit(self.fold['train'],n)
            close(h['weights'],ref['weights']);close(h['scales'],ref['scales']);close(r['loss_trace'],trace)
            close(predict(h,self.fold['held_inputs']),ref_predict(ref,self.fold['held_inputs']))

    def test_15_gradient_finite_difference(self):
        rows=self.fold['train'];h,r=fit(rows,8);theta=h['weights'];sc=h['scales']
        groups={(x['group'],x['question']) for x in rows}
        mass=[1/(len(groups)*sum((y['group'],y['question'])==(x['group'],x['question']) for y in rows)) for x in rows]
        def loss(w):return sum(m*2*(p-x['label'])**2 for x,p,m in zip(rows,predict({'weights':w,'scales':sc},rows),mass))
        for j in range(5):
            expected=sum(m*4*(p-x['label'])*p*(1-p)*feature(x,sc)[j] for x,p,m in zip(rows,predict(h,rows),mass))
            a=list(theta);b=list(theta);a[j]+=1e-5;b[j]-=1e-5
            self.assertAlmostEqual(expected,(loss(a)-loss(b))/2e-5,places=7)

    def test_16_invalid_step_budget(self):
        for n in (True,-1,1,129,32.0):
            with self.assertRaises(ValueError):fit(self.fold['train'],n)

    def test_17_full_question_not_candidate_accuracy(self):
        rows=[{'id':'a','group':'g','question':0,'label':0},{'id':'b','group':'g','question':0,'label':1}]
        self.assertEqual(full_questions(rows,[0.1,0.1]),[0])
        self.assertEqual(full_questions(rows,[0.1,0.9]),[1])

    def test_18_preference_uses_bounded_observed_success(self):
        self.assertEqual(alpha_from([0,0,0]),Q(1,2));self.assertEqual(alpha_from([1,1,1]),0)
        with self.assertRaises(ValueError):alpha_from([True])

    def test_19_same_objective_reference(self):
        for alpha in (Q(0),Q(1,4),Q(1,2)):
            for h in HORIZONS:
                k,_=select(self.search['candidate_quotes'],h,alpha)
                self.assertEqual(k,augmented_select(self.search['candidate_quotes'],h,alpha))

    def test_20_all_pilots_remain_charged(self):
        r=self.search
        self.assertEqual(sum(x['steps'] for x in r['fits'] if x['role']=='pilot'),504)
        self.assertGreater(r['stages']['pilot_cpu_ns'],0)
        self.assertGreaterEqual(r['lifecycle_cpu_ns'],sum(r['stages'].values()))

    def test_21_no_update_really_zero_fit(self):
        r=execute(self.fold,'no_update',1)
        self.assertEqual((r['update_steps_actually_executed'],r['stages']['pilot_cpu_ns']),(0,0))
        self.assertEqual(r['fits'][0]['train_ids'],[])

    def test_22_fixed_control_does_not_search(self):
        r=execute(self.fold,'fixed_32',1)
        self.assertEqual((r['update_steps_actually_executed'],len(r['fits'])),(32,1))
        self.assertEqual(r['calibration'],[])

    def test_23_separate_replay_accepts_real_row(self):
        pp=check_row(self.search,self.fold,self.labels)
        self.assertEqual(len(pp),len(self.fold['held_inputs']))

    def reject(self,mutate):
        r=copy.deepcopy(self.search);mutate(r)
        with self.assertRaises(ValueError):check_row(r,self.fold,self.labels)

    def test_24_weight_tamper(self):
        self.reject(lambda r:r['fits'][1]['head']['weights'].__setitem__(0,100.0))

    def test_25_prediction_tamper(self):
        self.reject(lambda r:r['test_probabilities'][0].update(p=0.123456))

    def test_26_fake_encoder_calls(self):self.reject(lambda r:r.update(fresh_encoder_forwards=1))

    def test_27_cost_quote_tamper(self):
        self.reject(lambda r:r['candidate_quotes']['32'].update(estimated_refit_cpu_ns='0'))

    def test_28_fake_training_count(self):self.reject(lambda r:r.update(update_steps_actually_executed=0))

    def test_29_missing_pilot(self):self.reject(lambda r:r['fits'].pop(0))

    def test_30_wrong_whole_question_label(self):
        self.reject(lambda r:r['calibration'][0]['complete_questions'].__setitem__(0,1-r['calibration'][0]['complete_questions'][0]))

    def test_31_phase_double_counting(self):
        self.reject(lambda r:r['stages'].update(pilot_cpu_ns=r['lifecycle_cpu_ns']+1))

    def test_32_unknown_horizon(self):
        for h in (True,0,2,65):
            with self.assertRaises(ValueError):execute(self.fold,'no_update',h)

    def test_33_unknown_controller(self):
        with self.assertRaises(ValueError):execute(self.fold,'invented_fbsde',1)

    def test_34_create_only_material(self):
        with self.assertRaises(FileExistsError):prepare(self.paths,self.folder)

    def test_35_strict_JSON(self):
        for raw in ('{"a":1,"a":2}','{"a":NaN}'):
            with self.assertRaises(ValueError):strict_loads(raw)

    def test_36_preserve_cached_source_bytes(self):
        for k,p in self.paths.items():self.assertEqual(sha(p.read_bytes()),LOCKS[k][1])

if __name__=='__main__':unittest.main()
