"""P0.8 source-only adversarial tests. No test is a pretrained inference receipt."""
from __future__ import annotations
from contextlib import contextmanager
from pathlib import Path
import copy
import hashlib
import json
import os
import random
import tempfile
import unittest
from unittest.mock import patch
import numpy as np
import p08_cohort as c
import p08_run as run
import p08_review as reviewer

ORIGINAL=Path(os.getenv('AGNEWS_ORIGINAL_ARCHIVE','/mnt/data/hepta-mmbert-agnews-original-p08.zip'))

def fake_raw():
    rows=[]
    for cat in c.HUFF_LABEL:
        for i in range(16):
            rows.append({'category':cat,'link':f'https://www.huffpost.com/p/{cat.replace(" ","-")}-{i}',
                         'headline':f'Published {cat} news investigation series {i}',
                         'short_description':f'Independent journalist reports verified {i} sources for {cat}',
                         'date':f'2020-06-{i+1:02d}', 'authors':'source'})
    return b'\n'.join(c.dump(r) for r in rows)+b'\n'

@contextmanager
def fixture_panel():
    raw=fake_raw()
    with patch.object(c,'HUFF_SHA',c.sha(raw)),patch.object(reviewer,'HUFF_SHA',c.sha(raw)):
        original_make=c.make_panel
        def fixture_make(agnews,body):return original_make(agnews,body,production_source=False)
        actual_choose=c.choose_huff
        def fixture_choose(body,*,require_full=True):return actual_choose(body,require_full=False)
        with patch.object(reviewer,'make_panel',fixture_make),patch.object(c,'choose_huff',fixture_choose):
            panel,_=c.make_panel(ORIGINAL,raw,production_source=False)
            c.verify_panel(panel)
            yield panel,raw

def fabricated_features():
    """Test-only 128×384 deterministic simulated vectors, never actual mmBERT."""
    rng=np.random.default_rng(1001)
    f=rng.normal(0,1,(128,384))
    for i in range(128):f[i,0]+=0.2*(i%4)
    return f

def fake_physical():
    return {'model_repo':c.MODEL_REPO,'revision':c.MODEL_REV,'weight_sha256':c.MODEL_SAFETENSORS_SHA,
            'tokenizer_sha256':c.MODEL_TOKENIZER_SHA,'model_type':'modernbert',
            'actual_cpu_model_forward_invocations':32,'original_pretrained_feature_rows':128,
            'actual_forward_input_tokens':2200,
            'model_load_and_pretrained_forward_wall_ns_self_reported':1000000,
            'original_historical_checkpoint_reused':False,'gpu_backend_used':False,
            'original_weight_signature_issuer_attested':False}

class P08SourceTests(unittest.TestCase):
    def test_real_agnews_archive_identity(self):
        if not ORIGINAL.is_file():self.skipTest('original AG News pretrained archive absent')
        a,b=c.original_agnews(ORIGINAL)
        self.assertEqual((len(a),len(b)),(64,32));self.assertNotIn('target',b[0]);self.assertIn('target',a[0])
    def test_model_and_publisher_revisions_not_historical_model_reused(self):
        self.assertEqual(len(c.MODEL_REV),40);self.assertEqual(len(c.HUFF_REV),40)
        self.assertNotEqual(c.MODEL_REV,c.ORIGINAL_MODEL_REV)
        self.assertEqual(c.MODEL_SAFETENSORS_SHA,'7ee7a6939b730a35e5d2a3e2263a1d1e992d10bc7f86b3470e9cb3cd482c590d')
    def test_synthetic_cohort_selection_deterministic_and_balanced(self):
        rows=c.choose_huff(fake_raw(),require_full=False)
        self.assertEqual(len(rows),32)
        self.assertEqual(sorted([sum(r['target']==i for r in rows) for i in range(4)]),[8]*4)
        self.assertEqual(rows,c.choose_huff(fake_raw(),require_full=False))
        self.assertNotEqual(rows,c.choose_huff(fake_raw().replace(b'investigation',b'investigations'),require_full=False))
    def test_synthetic_wrong_huff_sha_fails(self):
        if not ORIGINAL.exists():self.skipTest('real AG News source unavailable')
        with self.assertRaises(c.Denied):c.make_panel(ORIGINAL,fake_raw(),production_source=True)
    def test_missing_category_fails(self):
        raw=b'\n'.join(line for line in fake_raw().splitlines() if b'WORLD NEWS' not in line)
        with self.assertRaises(c.Denied):c.choose_huff(raw,require_full=False)
    def test_huff_duplicate_json_key(self):
        raw=fake_raw()+b'{"category":"TECH","category":"BUSINESS"}\n'
        with self.assertRaises(ValueError):c.choose_huff(raw,require_full=False)
    def test_future_window_is_explicitly_false(self):
        if not ORIGINAL.is_file():self.skipTest('real AG News archive absent')
        with fixture_panel() as (p,_):
            self.assertFalse(p['claims']['future_window_verified'])
            self.assertFalse(p['claims']['original_model_reused'])
            self.assertNotIn('target',p['transfer'][0]);self.assertNotIn('target',p['retention'][0])
            self.assertEqual(c.sha(c.dump(p)),c.sha(c.dump(copy.deepcopy(p))))
    def test_forced_claim_fails(self):
        if not ORIGINAL.is_file():self.skipTest('real archive missing')
        with fixture_panel() as (p,_):
            p['claims']['production_authorized']=True
            with self.assertRaises(c.Denied):c.verify_panel(p)
    def test_leaked_transfer_target_denied(self):
        if not ORIGINAL.is_file():self.skipTest('real archive missing')
        with fixture_panel() as (p,_):
            p['transfer'][0]['target']=3
            with self.assertRaises(c.Denied):c.verify_panel(p)
    def test_wrong_model_digest_denied(self):
        if not ORIGINAL.is_file():self.skipTest('real archive missing')
        with fixture_panel() as (p,_):
            p['model_weight_sha256']='0'*64
            with self.assertRaises(c.Denied):c.verify_panel(p)
    def test_private_write_no_overwrite(self):
        with tempfile.TemporaryDirectory() as t:
            d=Path(t)/'x';c.put_private(d,b'first')
            self.assertEqual(d.read_bytes(),b'first')
            self.assertEqual(d.stat().st_mode & 0o777,0o600)
            with self.assertRaises(FileExistsError):c.put_private(d,b'second')
    def test_private_reader_refuses_symlink(self):
        with tempfile.TemporaryDirectory() as t:
            p=Path(t)/'target';p.write_bytes(b'some data');q=Path(t)/'link';q.symlink_to(p)
            with self.assertRaises(OSError):c.read_regular(q,100)
    def test_train_only_unsupervised_route(self):
        x=run.normalize(fabricated_features());a,m=run.route_two_cluster(x[:64],x)
        self.assertEqual(len(a),128);self.assertEqual(m.shape,(2,384))
        z=x.copy();z[64:]+=1000
        aa,mm=run.route_two_cluster(z[:64],z)
        self.assertTrue(np.array_equal(a[:64],aa[:64]));self.assertTrue(np.array_equal(m,mm))
    def test_independent_random_route_can_differ(self):
        keys=[f'case-{i}' for i in range(40)]
        self.assertTrue(any(c.route(i)!=run.route_random_control(i) for i in keys))
    def test_real_numerical_no_labels_train_budget(self):
        if not ORIGINAL.is_file():self.skipTest('original archive absent')
        with fixture_panel() as (p,_):
            out=run.learn_and_predict(p,fabricated_features())
            self.assertEqual(len(out['predictions']),192)
            self.assertEqual(out['baseline_work']['train_only_loo_fits'],512)
            for s in out['seeds']:
                for k,v in s['arms'].items():
                    self.assertEqual(v['actual_sgd_updates'],512)
                    self.assertEqual(v['actual_parameter_touches'],512*1540)
                    self.assertEqual(v['allocated_head_scalars'],1540 if k=='shared' else 3080)
            self.assertFalse(out['flags']['production_authorized'])
    def test_original_retention_gold_does_not_change_training(self):
        if not ORIGINAL.is_file():self.skipTest('original archive absent')
        with fixture_panel() as (p,_):
            changed=copy.deepcopy(p)
            changed['gold_commitment']='a'*64
            a=run.learn_and_predict(p,fabricated_features())
            b=run.learn_and_predict(changed,fabricated_features())
            self.assertEqual(a['predictions'],b['predictions'])
            self.assertEqual(a['seeds'],b['seeds'])
    def test_numerical_nan_rejected(self):
        if not ORIGINAL.is_file():self.skipTest('original archive absent')
        with fixture_panel() as (p,_):
            f=fabricated_features();f[3,8]=np.nan
            with self.assertRaises(c.Denied):run.learn_and_predict(p,f)
    def test_no_effect_code_or_user_jit(self):
        path=Path(__file__).with_name('p08_run.py').read_text()
        self.assertNotIn('mprotect(',path)
        self.assertNotIn('subprocess.Popen(',path)
        self.assertNotIn('exec(',path)
    def test_paired_binomial_wins(self):
        self.assertEqual(reviewer.exact_two_sided(0,5),.0625)
        self.assertEqual(reviewer.exact_two_sided(5,0),.0625)
        self.assertEqual(reviewer.exact_two_sided(1,1),1.)
    def test_review_genuine_no_go_with_synthetic_source_and_asserted_physical(self):
        """Fixture tests a reviewer, not an actually verified model or result."""
        if not ORIGINAL.is_file():self.skipTest('original archive absent')
        with fixture_panel() as (p,raw):
            out=run.learn_and_predict(p,fabricated_features());out['physical']=fake_physical()
            with tempfile.TemporaryDirectory() as temp:
                d=Path(temp)
                for name,value in [('panel',c.dump(p)),('prelabel',c.dump(out)),('huff',raw)]:c.put_private(d/name,value)
                r=reviewer.review(agnews=ORIGINAL,huff=d/'huff',panel_file=d/'panel',
                                  prelabel_file=d/'prelabel',sealed_sha=c.sha(c.dump(out)))
                self.assertEqual(r['new_huffpost_historical_source_count'],32)
                self.assertFalse(r['prospective_future_window_verified'])
                self.assertEqual(r['disposition'],'HOLD_NO_GO')
                self.assertFalse(r['production_authorized'])
    def test_tampered_prelabel_denied(self):
        if not ORIGINAL.is_file():self.skipTest('original archive absent')
        with fixture_panel() as (p,raw):
            out=run.learn_and_predict(p,fabricated_features());out['physical']=fake_physical()
            with tempfile.TemporaryDirectory() as temp:
                d=Path(temp)
                for name,value in [('panel',c.dump(p)),('prelabel',c.dump(out)),('huff',raw)]:c.put_private(d/name,value)
                with self.assertRaises(c.Denied):reviewer.review(agnews=ORIGINAL,huff=d/'huff',panel_file=d/'panel',
                                         prelabel_file=d/'prelabel',sealed_sha='0'*64)
    def test_label_or_identity_corruption_denied(self):
        if not ORIGINAL.is_file():self.skipTest('original archive absent')
        with fixture_panel() as (p,raw):
            out=run.learn_and_predict(p,fabricated_features());out['physical']=fake_physical()
            out['predictions'][0]['p']['split']=[1.,0.,0.,0.,0.]
            with tempfile.TemporaryDirectory() as temp:
                d=Path(temp)
                for name,value in [('panel',c.dump(p)),('prelabel',c.dump(out)),('huff',raw)]:c.put_private(d/name,value)
                with self.assertRaises(c.Denied):reviewer.review(agnews=ORIGINAL,huff=d/'huff',panel_file=d/'panel',
                                         prelabel_file=d/'prelabel',sealed_sha=c.sha(c.dump(out)))
if __name__=='__main__':unittest.main()
