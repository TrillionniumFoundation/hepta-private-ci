"""Original-archive tests; missing source is an error, never a silent skip."""
import contextlib
import copy
import io
import os
import shutil
import struct
import tempfile
import unittest
from fractions import Fraction as Q
from pathlib import Path
import numpy as np
import audit_news as reviewer
from material_news import PROTOCOL_SHA, encode, loads, original, packet, prepare, sha, spec, tensor, write
from trial_news import choose, design, fit, preference, probabilities, run

class Contracts(unittest.TestCase):
    def test_01_protocol_locked(self):self.assertEqual(spec()['head_parameters'],1540)
    def test_02_protocol_separate_profile(self):self.assertIn('not_ModernBERT',spec()['profile'])
    def test_03_duplicate_json_refused(self):
        with self.assertRaises(ValueError):loads('{"a":1,"a":2}')
    def test_04_nonfinite_json_refused(self):
        with self.assertRaises(ValueError):loads('{"a":NaN}')
    def test_05_nonfinite_write_refused(self):
        with self.assertRaises(ValueError):encode({'x':float('inf')})
    def test_06_tensor_truncation(self):
        for raw in (b'',b'1234',struct.pack('<Q',20000)):
            with self.subTest(raw=raw),self.assertRaises(ValueError):tensor(raw)
    def test_07_wrong_tensor_schema(self):
        h=encode({'x':{}})
        with self.assertRaises(ValueError):tensor(struct.pack('<Q',len(h))+h)
    def test_08_probability_normalization(self):
        x=np.ones((3,385));w=np.zeros((385,4));p=probabilities(x,w)
        np.testing.assert_array_equal(p,np.full((3,4),.25))
    def test_09_train_budget_rejected(self):
        for b in ((),(True,),(-1,),(129,)):
            with self.subTest(b=b),self.assertRaises(ValueError):fit(np.ones((64,385)),np.zeros(64,dtype=int),b)
    def test_10_zero_steps_no_hidden_fit(self):
        snaps,losses=fit(np.ones((64,385)),np.zeros(64,dtype=int),(0,))
        self.assertEqual(losses,[]);self.assertFalse(snaps[0].any())
    def test_11_preference_clip(self):
        self.assertEqual(preference([0]*4)[-1],Q(1,2));self.assertEqual(preference([8]*4)[-1],Q(0))
    def test_12_preference_no_drift_at_half(self):self.assertEqual(preference([4]*4),[Q(1,4)]*5)
    def test_13_neutral_and_risk_can_differ(self):
        c={0:[8,8,8,0],8:[5,5,5,5]}
        self.assertEqual(choose(c,'neutral',Q(1,2))[0],0)
        self.assertEqual(choose(c,'ndu_discrete',Q(1,2))[0],8)
    def test_14_same_profile_control(self):
        for alpha in (Q(0),Q(1,4),Q(1,2)):
            c={0:[1,2,1,2],8:[2,2,2,2],32:[2,2,2,2]}
            self.assertEqual(choose(c,'ndu_discrete',alpha),choose(c,'augmented_same_profile',alpha))
    def test_15_tie_prefers_cheap_checkpoint(self):self.assertEqual(choose({128:[1]*4,8:[1]*4},'neutral',Q(0))[0],8)
    def test_41_scalar_prediction_preserves_float64(self):
        x=np.array([1.001],dtype=np.float32);m=[float(x[0])-1e-9];scale=[1e-6]
        result=reviewer.reference_row(x,m,scale)
        self.assertEqual(result,[(float(x[0])-m[0])/scale[0],1.])
        self.assertGreater(result[0],0.0009)
    def test_16_unknown_selector(self):
        with self.assertRaises(ValueError):choose({0:[1]*4},'fake_solver',Q(0))

class OriginalEvidence(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.archive=Path(os.environ['NEWS_ARCHIVE']);cls.temp=tempfile.TemporaryDirectory()
        cls.root=Path(cls.temp.name);cls.mat=cls.root/'material';cls.run_dir=cls.root/'run'
        prepare(cls.archive,cls.mat)
        with contextlib.redirect_stdout(io.StringIO()):run(cls.mat,cls.run_dir)
        cls.seal=loads((cls.run_dir/'sealed.json').read_bytes())
    @classmethod
    def tearDownClass(cls):cls.temp.cleanup()
    def audit(self,run_dir,out):
        with contextlib.redirect_stdout(io.StringIO()):return reviewer.audit(self.archive,self.mat,run_dir,out)
    def reject(self,change):
        with tempfile.TemporaryDirectory() as t:
            d=Path(t)/'run';shutil.copytree(self.run_dir,d);s=copy.deepcopy(self.seal)
            change(s)
            (d/'sealed.json').write_bytes(encode(s))
            for r in s['rows']:(d/f"{r['repeat']}-{r['arm']}.json").write_bytes(encode(r))
            with self.assertRaises(ValueError):self.audit(d,Path(t)/'score.json')
    def test_17_original_split_census(self):
        rows,x,p=original(self.archive);self.assertEqual(x.shape,(128,384));self.assertEqual([len(v) for v in p.values()],[64,32,32])
    def test_18_worker_no_held_labels(self):
        a,_=packet(self.mat/'worker.npz');self.assertNotIn('y_holdout',a)
    def test_19_actual_prefix_equals_independent_restart(self):
        a,_=packet(self.mat/'worker.npz');mean=a['x_train'].astype(float).mean(0)
        scale=np.maximum(np.sqrt(np.mean((a['x_train']-mean)**2,axis=0)),1e-6)
        x=design(a['x_train'],mean,scale);p,_=fit(x,a['y_train'],(0,8,32,128))
        for n in (8,32,128):
            q,_=fit(x,a['y_train'],(n,));np.testing.assert_array_equal(p[n],q[n])
    def test_20_complete_scalar_audit(self):
        r=self.audit(self.run_dir,self.root/'score.json')
        self.assertEqual(r['verified_lifecycles'],27);self.assertEqual(r['verified_checkpoint_comparisons'],63)
        self.assertEqual(r['same_profile_choice_replays'],12);self.assertEqual(r['actual_updates'],2040)
        self.assertFalse(r['production_accepted']);self.assertEqual(len(r['summaries']),9)
    def test_21_original_archive_tamper(self):
        p=self.root/'bad.zip';p.write_bytes(self.archive.read_bytes()+b'x')
        with self.assertRaises(ValueError):original(p)
    def test_22_source_code_hash_tamper(self):self.reject(lambda s:s['source_sha256'].update({'trial_news.py':'0'*64}))
    def test_23_missing_arm(self):self.reject(lambda s:s['rows'].pop())
    def test_24_duplicate_arm(self):self.reject(lambda s:s['rows'].append(s['rows'][0]))
    def test_25_weight_tamper(self):
        def f(s):s['rows'][0]['weights'][0][0]+=.2
        self.reject(f)
    def test_26_probability_reseal_tamper(self):
        def f(s):s['rows'][0]['probabilities'][0]=[1.,0.,0.,0.]
        self.reject(f)
    def test_27_free_training_tamper(self):
        def f(s):next(r for r in s['rows'] if r['arm']=='neutral')['actual_steps']=0
        self.reject(f)
    def test_28_holdout_gold_field_refused(self):self.reject(lambda s:s.update(y_holdout=[0]*32))
    def test_29_false_model_execution_refused(self):self.reject(lambda s:s.update(fresh_encoder_calls=128))
    def test_30_false_production_field_refused(self):self.reject(lambda s:s.update(production_accepted=True))
    def test_31_calibration_tamper(self):
        def f(s):next(r for r in s['rows'] if r['arm']=='ndu_discrete')['calibration_blocks']['8'][0]+=1
        self.reject(f)
    def test_32_preference_tamper(self):
        def f(s):next(r for r in s['rows'] if r['arm']=='ndu_discrete')['preference_trace'][-1]='0'
        self.reject(f)
    def test_33_budget_tamper(self):
        def f(s):next(r for r in s['rows'] if r['arm']=='fixed8')['selected_steps']=32
        self.reject(f)
    def test_34_unknown_lifecycle_field(self):
        self.reject(lambda s:s['rows'][0].update(heldout_accuracy_used=True))
    def test_35_missing_phase_cost(self):
        def f(s):next(r for r in s['rows'] if r['arm']=='neutral')['phases'].pop('calibration_and_selection')
        self.reject(f)
    def test_36_boolean_counter_refused(self):self.reject(lambda s:s['rows'][0].update(actual_steps=False))
    def test_37_do_not_overwrite_evidence(self):
        with self.assertRaises(FileExistsError):prepare(self.archive,self.mat)
        with self.assertRaises(FileExistsError):run(self.mat,self.run_dir)
    def test_38_changed_worker_rejected(self):
        with tempfile.TemporaryDirectory() as t:
            d=Path(t);shutil.copytree(self.mat,d/'m');p=d/'m'/'worker.npz';p.write_bytes(p.read_bytes()+b'x')
            with self.assertRaises(ValueError):packet(p)
    def test_39_original_test_labels_checked(self):
        p=self.mat/'scorer-labels.json';old=p.read_bytes()
        try:
            y=loads(old);k=next(iter(y));y[k]=(y[k]+1)%4;p.write_bytes(encode(y))
            with self.assertRaises(ValueError):self.audit(self.run_dir,self.root/'bad-score.json')
        finally:p.write_bytes(old)
    def test_40_journal_omission_refused(self):
        with tempfile.TemporaryDirectory() as t:
            d=Path(t)/'run';shutil.copytree(self.run_dir,d);p=d/'attempts.jsonl';p.write_bytes(p.read_bytes().split(b'\n',1)[1])
            with self.assertRaises(ValueError):self.audit(d,Path(t)/'score.json')

if __name__=='__main__':unittest.main()
