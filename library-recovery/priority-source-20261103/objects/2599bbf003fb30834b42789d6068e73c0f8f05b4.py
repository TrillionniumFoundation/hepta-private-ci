"""Adversarial, differential and smoke tests for V3 independent research tools."""
import copy
import hashlib
import json
import math
from pathlib import Path
import tempfile
import unittest
import numpy as np
from mpmath import mp

from fpt_reference import FPT, boundary_derivatives
from fpt_time_brackets import bracket, refinement
from simple_fd_oracle import solve
from simplified_stopping import SimpleStopping
from precision_limits import casts, deterministic_limit,zero_discount_sensitivity
from backbone_promotion_gate import compare,MODELS
from cpu_kernel_replay import initial,step,crash_recovery,benchmark
from media_bytes_gate import check_bytes
from multimodal_gate import check_pairs
from recurrent_factorial_pilot import (test_local_slope as slope_check, make_dataset,
                                       RecurrentSurrogate, model_parameters_sha,run_pilot)


class P0TimeBoundsTests(unittest.TestCase):
    def test_monotone_refinement(self):
        p=FPT(.8,-.3,.7,.9,.05)
        r=refinement(p,counts=(8,16,32),dps=70)
        self.assertFalse(r['certified_real_interval'])
        widths=list(map(lambda x:mp.mpf(x['width']),r['slabs']))
        self.assertGreater(widths[0],widths[1]);self.assertGreater(widths[1],widths[2])
    def test_refinements_multiple_drift_signs(self):
        for p in (FPT(.6,.3,.7,.5,.1),FPT(.2,-.5,.9,1.,.03)):
            r=refinement(p,counts=(12,24),dps=65)
            self.assertGreater(float(r['reference_gap']),0)
    def test_exact_degenerate(self):
        for p in (FPT(.8,.1,.7,1.,0.),FPT(0.,.1,.7,1.,.2),FPT(.8,.1,.7,0.,.2)):
            r=bracket(p)
            self.assertEqual(r['lower'],'0.0')
            self.assertTrue(r['exact_degenerate'])
    def test_bad_domain_rejected(self):
        for p in (FPT(.8,0.,0.,.9,.05),FPT(.8,0.,.5,.9,-.1),
                  FPT(-.8,0.,.5,.9,.1),FPT(.8,math.nan,.5,.9,.1)):
            with self.assertRaises(ValueError):bracket(p)
    def test_precision_loss_flagged(self):
        p=FPT(math.log(1.000000000000002),
              .007595780582070804-3.5072936797757205e-7-1.8581469732429565**2/2,
              1.8581469732429565,2.2216211523554883e-8,.007595780582070804)
        r=casts(p)
        self.assertGreater(mp.mpf(r['reference_gap']),0)
        for fmt in ('binary64','float32','bfloat16'):
            self.assertEqual(r['casts'][fmt]['classification'],'DENY_LOST_POSITIVE_GAP')
    def test_smooth_gradient_interior(self):
        p=FPT(.8,-.3,.7,.9,.05)
        r=boundary_derivatives(p)
        self.assertLess(float(r['abs_delta']),1e-30)
    def test_det_sigma_to_zero(self):
        for p,expected in [(FPT(.7,-.5,.001,2.,.2),1),
                           (FPT(.7,-.5,.001,1.,.2),0),
                           (FPT(.7,.5,.001,2.,.2),0)]:
            r=deterministic_limit(p)
            self.assertEqual(r['F'],float(expected))
        with self.assertRaises(ValueError):
            deterministic_limit(FPT(.5,-.5,.2,1.,.1))
    def test_small_q_first_moment(self):
        p=FPT(.8,-.3,.7,.9,.05)
        r=zero_discount_sensitivity(p,q_small=1e-8,dps=80)
        self.assertLess(abs(float(r['ratio_to_zero_q_limit'])-1),1e-8)
    def test_fd_second_order_convergence(self):
        p=SimpleStopping(.05,.03,.4,.08)
        a=[solve(p,n=n)['max_abs_error'] for n in (200,400,800)]
        self.assertTrue(a[2]<a[1]<a[0])
        self.assertGreater(a[0]/a[1],3.5)
        self.assertGreater(a[1]/a[2],3.5)
        self.assertLess(a[2],.0001)
    def test_fd_truncation_bias_detected(self):
        p=SimpleStopping(.05,.03,.4,.08)
        accurate=solve(p,n=800,right_bc='analytic_value')['max_abs_error']
        biased=solve(p,n=800,right_bc='leading_asymptote')['max_abs_error']
        self.assertGreater(biased,100*accurate)
        with self.assertRaises(ValueError):solve(p,right_bc='fabricated')

class P1P2RecurrentTests(unittest.TestCase):
    def test_gate_value_slope_exact_at_anchor(self):
        for r in slope_check():
            self.assertLess(r['value_difference'],1e-12)
            self.assertLess(r['derivative_difference'],1e-12)
    def test_same_initial_trainable_weights(self):
        import torch
        fingerprints=set()
        for arm in ('control','call','risk','margin','call+risk+margin'):
            torch.manual_seed(19)
            m=RecurrentSurrogate(arm)
            fingerprints.add(model_parameters_sha(m))
        self.assertEqual(len(fingerprints),1)
    def test_event_generators_all_have_bit_labels(self):
        for task in ('overwrite_reset','irregular_time','selective_copy','long_range','mqar'):
            x,y=make_dataset(16,30,72,task=task)
            self.assertEqual(tuple(x.shape),(30,16,6))
            self.assertTrue(all(v in (0,1) for v in y.numpy()))
    def test_mqar_independent_replay(self):
        a,truth=make_dataset(48,30,100,task='mqar')
        for x,y in zip(a.numpy(),truth.numpy()):
            memory=[0,0]
            for event in x[:-1]:
                if event[2]==1:
                    memory[int(event[0])]=int(event[1])
            self.assertEqual(memory[int(x[-1,0])],int(y))
    def test_local_forward_all_arms(self):
        from fair_ablation import ARMS
        x,_=make_dataset(8,3,10)
        for arm in ARMS:
            m=RecurrentSurrogate(arm)
            self.assertTrue(np.isfinite(m(x).detach().numpy()).all())
    def test_short_train_runs_untrusted(self):
        p=run_pilot(seeds=(7,),train_n=12,holdout_n=20,
                    train_length=6,holdout_length=12,
                    training_steps=2,batch_size=8)
        self.assertEqual(len(p['rows']),8)
        self.assertTrue(p['matched_parameter_data_step_constraints'])
        self.assertFalse(p['full_training_flops_equal'])
        self.assertFalse(p['production_evidence_accepted'])

class P3ByteTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root=Path(__file__).resolve().parents[1]/'reports/toy_media_corpus'
        cls.manifest=cls.root/'manifest.json'
    def test_actual_40_fourmodality_files_and_splits(self):
        if not self.manifest.is_file():self.skipTest('optional synthetic media corpus not packaged')
        records=json.loads(self.manifest.read_text())
        self.assertEqual(len(records),40)
        self.assertTrue(check_bytes(records,self.root)['byte_integrity_metadata_valid'])
    def test_symlink_inside_root_denied(self):
        if not self.manifest.is_file():self.skipTest('optional media corpus not packaged')
        rec=json.loads(self.manifest.read_text())[0]
        with tempfile.TemporaryDirectory(dir=self.root) as scratch:
            link=Path(scratch)/'alias.png'
            real=self.root/rec['files']['image']['path']
            link.symlink_to(real)
            forged=copy.deepcopy(rec)
            forged['files']['image']['path']=str(link.relative_to(self.root))
            problems=check_bytes([forged],self.root)
            self.assertFalse(problems['byte_integrity_metadata_valid'])
            self.assertTrue(any('symlink' in f for f in problems['failures']))
    def test_cross_split_duplicate_digest_rejected(self):
        if not self.manifest.is_file():self.skipTest('optional media corpus not packaged')
        records=json.loads(self.manifest.read_text())
        a=next(r for r in records if r['split']=='train')
        b=next(r for r in records if r['split']=='holdout')
        def meta(row):
            return {'sample_id':row['sample_id'],'entity_id':row['entity_id'],
                    'scene_id':row['scene_id'],'split':row['split'],
                    't_start_sec':row['t_start_sec'],'t_end_sec':row['t_end_sec'],
                    'provenance':row['provenance'],
                    'asset_sha256':{m:x['sha256'] for m,x in row['files'].items()}}
        x,y=meta(a),meta(b)
        y['asset_sha256']['audio']=x['asset_sha256']['audio']
        result=check_pairs([x,y])
        self.assertFalse(result['metadata_valid'])
        self.assertTrue(any('media_digest leaks across splits' in issue for issue in result['failures']))

    def test_missing_media_rejected(self):
        if not self.manifest.is_file():self.skipTest('optional media corpus not packaged')
        rec=json.loads(self.manifest.read_text())[0]
        forged=copy.deepcopy(rec)
        forged['files']['video']['path']='../../etc/passwd'
        problems=check_bytes([forged],self.root)
        self.assertFalse(problems['byte_integrity_metadata_valid'])

class P4P5Tests(unittest.TestCase):
    def test_disk_checkpoint_shape_mismatch_rejected(self):
        from cpu_kernel_replay import write_checkpoint,read_checkpoint
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'snap.bin'
            write_checkpoint(path,initial(64),3)
            with self.assertRaises(ValueError):read_checkpoint(path,256)

    def test_multi_scale_cpu_oracle(self):
        for n in (64,256,1024,4096):
            h=step(initial(n),1)
            self.assertTrue(np.isfinite(h).all())
    def test_abrupt_exit_and_bitwise_replay(self):
        out=crash_recovery(64,total=25,kill_after=11)
        self.assertEqual(out['abrupt_exit_code'],127)
        self.assertTrue(out['bit_exact_replayed'])
        self.assertTrue(out['corrupt_checkpoint_rejected'])
    def test_numpy_real_benchmark_stays_unqualified(self):
        for r in benchmark(scales=(64,256),events=8):
            self.assertTrue(r['not_rust'])
            self.assertGreater(r['p99_ms'],0)
            self.assertIsNone(r['energy_joules'])
    def test_p5_missing_metadata_rejected(self):
        r=compare([],task_ids=('copy','mqar','irregular'),seed_ids=(1,2,3))
        self.assertFalse(r['production_qualified'])
        self.assertEqual(r['decision'],'DENY')
    def test_p5_self_reported_positive_still_not_production(self):
        rows=[]
        for task in ('copy','mqar','irregular'):
            for seed in range(8):
                for model in MODELS:
                    rows.append({
                        'task':task,'seed':seed,'model':model,
                        'source_sha':'a'*40,'data_sha256':'b'*64,
                        'holdout_sha256':'c'*64,'environment_sha256':'d'*64,
                        'raw_train_log_sha256':'e'*64,'raw_eval_log_sha256':'f'*64,
                        'train_tokens':10000,'train_flops':500000,'train_wall_seconds':5.,
                        'eval_flops':1000,'training_joules':100.,'inference_joules':10.,
                        'peak_rss_bytes':2000000,'preparation_joules':1.,
                        'validation_joules':1.,'switch_joules':1.,'cleanup_joules':1.,
                        'quality':.99 if model=='hybrid_hcsn' else .90})
        r=compare(rows,task_ids=('copy','mqar','irregular'),seed_ids=range(8))
        self.assertTrue(r['metadata_comparable'])
        self.assertTrue(r['potential_research_advantage'])
        self.assertEqual(r['decision'],'REVIEW_REQUIRED')
        self.assertFalse(r['production_qualified'])
    def test_p5_negative_transfer_guard(self):
        rows=[]
        for task in ('copy','mqar','irregular'):
            for seed in range(8):
                for model in MODELS:
                    quality=.8 if model!='hybrid_hcsn' else (.6 if task=='mqar' else .9)
                    rows.append({
                        'task':task,'seed':seed,'model':model,
                        'source_sha':'a'*40,'data_sha256':'b'*64,
                        'holdout_sha256':'c'*64,'environment_sha256':'d'*64,
                        'raw_train_log_sha256':'e'*64,'raw_eval_log_sha256':'f'*64,
                        'train_tokens':10000,'train_flops':500000,'train_wall_seconds':5.,
                        'eval_flops':1000,'training_joules':100.,'inference_joules':10.,
                        'peak_rss_bytes':2000000,'preparation_joules':1.,
                        'validation_joules':1.,'switch_joules':1.,'cleanup_joules':1.,
                        'quality':quality})
        r=compare(rows,task_ids=('copy','mqar','irregular'),seed_ids=range(8))
        self.assertTrue(r['metadata_comparable'])
        self.assertFalse(r['potential_research_advantage'])
        self.assertEqual(r['decision'],'DENY')

if __name__=='__main__':unittest.main()
