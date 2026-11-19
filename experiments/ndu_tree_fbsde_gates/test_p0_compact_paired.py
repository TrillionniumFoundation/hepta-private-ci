"""Offline fixture-only tests. No pretrained weights, no external truth certification."""
import copy
import hashlib
import json
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

import torch
import p0_compact_paired as trial
import p0_compact_score as score


def make_case(kind,i,label):
    state=f"{kind} distinct immutable AG News source {i}, category {label}"
    h=hashlib.sha256(state.encode()).hexdigest()
    joint={"state":state,"question":"Which category does the news report describe?",
           "options":["world","sports"]}
    return {"case_id":h[:24],"group_id":h,"source_digest":h,
            "joint_input_digest":trial.digest(joint),"split":kind,"joint_input":joint,
            "label":label,"label_name":joint["options"][label]}

def fixture_panels():
    original={"cases":[]};fresh={"cases":[],"same_public_source_family":True,
           "chronological_future_claim":False,"production_promotion":"DENY_ALL"}
    for kind,n in [('train',64),('calibration',16),('test',32)]:
        for label in (0,1):
            original['cases'].extend(make_case(kind,i,label) for i in range(n))
    for label in (0,1):
        fresh['cases'].extend(make_case('new_holdout',i,label) for i in range(64))
    return original,fresh

def material(original,fresh,tmp):
    z=Path(tmp)/'artifact.zip'
    with zipfile.ZipFile(z,'w') as out:
        out.writestr('stem-agnews-new-source-panel.json',trial.canon(fresh))
    return z

class FakeEncoder:
    def __init__(self,model_id,*,max_tokens=512):
        self.model_id=model_id; self.forward_count=0;self.load_wall_ns=1000
    def forward(self,row):
        self.forward_count+=1
        # Deterministic source-derived *fixture* features, not natural semantics.
        h=hashlib.sha256(row['source_digest'].encode()).digest()
        x=torch.zeros(384,dtype=torch.float32)
        x[0]=float(h[0])/255.;x[1]=float(h[1])/255.;x[2]=float(h[2])/255.
        return x,1000,48
    def finish(self):return {'model.safetensors':'b'*64}

class ContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        original,fresh=fixture_panels()
        cls.original=original;cls.fresh=fresh
        cls.tmp=tempfile.TemporaryDirectory();cls.zip=material(original,fresh,cls.tmp.name)
        cls.src,cls.lab=trial.prepare(original,cls.zip,fixture=True)
    @classmethod
    def tearDownClass(cls):cls.tmp.cleanup()
    def test_full_cohort(self):
        self.assertEqual(len(self.src['train']),128)
        self.assertEqual(len(self.src['calibration']),32)
        self.assertEqual(len(self.src['future_source_only']),192)
        self.assertTrue(trial.validate_prep(self.src,self.lab))
    def test_source_only(self):
        self.assertFalse(any('label' in r for r in self.src['future_source_only']))
    def test_full_actual_archive_sha_is_required(self):
        with self.assertRaises(trial.P0Error):trial.prepare(self.original,self.zip)
    def test_missing_future_source(self):
        s=copy.deepcopy(self.src);s['future_source_only'].pop()
        with self.assertRaises(trial.P0Error):trial.validate_prep(s,self.lab)
    def test_bad_label_attack(self):
        l=copy.deepcopy(self.lab);l['labels'][0]['group_id']='f'*64
        with self.assertRaises(trial.P0Error):trial.validate_prep(self.src,l)
    def test_future_label_leak(self):
        s=copy.deepcopy(self.src);s['future_source_only'][0]['label']=0
        with self.assertRaises(trial.P0Error):trial.validate_prep(s)
    def test_overlap(self):
        s=copy.deepcopy(self.src);s['future_source_only'][0]= {k:v for k,v in s['train'][0].items() if k not in ('label','label_name')}
        s['future_source_only'][0]['split']='test'
        with self.assertRaises(trial.P0Error):trial.validate_prep(s)
    def test_unknown_model(self):
        with self.assertRaises(trial.P0Error):trial.execute(self.src,'other')
    def test_q24_ties_even(self):
        v=torch.zeros(384);v[0]=1.0
        y=trial.q24_feature(torch,v)
        self.assertEqual(y[0].item(),1.0)
        self.assertEqual(y.shape[0],384)
    def test_q24_nonfinite(self):
        v=torch.zeros(384);v[0]=float('nan')
        with self.assertRaises(trial.P0Error):trial.q24_feature(torch,v)
    def test_gated_parameters(self):
        m=trial.make_heads(torch)
        self.assertEqual(sum(x.numel() for x in m['learned_gate'].parameters()),7434)
        self.assertEqual(trial._head_digest(torch,m['frozen_gate']),trial._head_digest(torch,m['learned_gate']))
    def test_train_updates_and_freezes(self):
        with patch.object(trial,'LocalEncoder',FakeEncoder):
            r=trial.execute(self.src,'granite97')
        self.assertEqual(r['actual_encoder_forward_count'],352)
        self.assertNotEqual(r['head_stats']['learned_gate']['head_sha256'],r['head_stats']['frozen_gate']['head_sha256'])
        self.assertEqual(r['head_stats']['learned_gate']['parameters'],7434)
        self.assertFalse(r['p0_accepted']);self.assertFalse(r['p1_accepted'])
    def test_frozen_training_schedule_is_model_invariant(self):
        with patch.object(trial,'LocalEncoder',FakeEncoder):
            a=trial.execute(self.src,'granite97')
            b=trial.execute(self.src,'mmbert_small')
        self.assertEqual([x['probs'] for x in a['future_predictions']],
                         [x['probs'] for x in b['future_predictions']])
        self.assertEqual(a['head_stats']['learned_gate']['head_sha256'],b['head_stats']['learned_gate']['head_sha256'])
    def test_evaluator_no_model_authority(self):
        with patch.object(trial,'LocalEncoder',FakeEncoder):
            a=trial.execute(self.src,'granite97')
            b=trial.execute(self.src,'mmbert_small')
        reports={'granite97':a,'mmbert_small':b}
        out=score.score(self.src,self.lab,reports,source_digest=trial.digest(self.src),
                        labels_digest=trial.digest(self.lab),report_digests={k:trial.digest(v) for k,v in reports.items()})
        self.assertEqual(out['models']['granite97']['quality']['new_holdout']['learned_gate']['cases'],128)
        self.assertEqual(out['paired']['new_holdout.learned_gate.granite_vs_mmbert']['delta_accuracy'],0)
        self.assertFalse(out['production_accepted'])
    def test_scorer_rejects_model_mismatch(self):
        with patch.object(trial,'LocalEncoder',FakeEncoder):
            a=trial.execute(self.src,'granite97')
            b=trial.execute(self.src,'mmbert_small')
        a['source_sha256']='0'*64
        reports={'granite97':a,'mmbert_small':b}
        with self.assertRaises(score.ScoreError):
            score.score(self.src,self.lab,reports,source_digest=trial.digest(self.src),
                        labels_digest=trial.digest(self.lab),report_digests={k:trial.digest(v) for k,v in reports.items()})
    def test_scorer_rejects_99_p99_samples(self):
        with self.assertRaises(score.ScoreError):score.percentile([1]*99,.99)
    def test_exact_pair_binomial(self):
        self.assertEqual(score.exact_pair_binomial(0,0),1.)
        self.assertAlmostEqual(score.exact_pair_binomial(5,0),.0625)
        self.assertEqual(score.exact_pair_binomial(10,10),1.)

if __name__=='__main__':unittest.main()
