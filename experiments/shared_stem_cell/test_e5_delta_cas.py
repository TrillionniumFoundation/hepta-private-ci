"""Actual CPU Q24 synthetic two-wave delta and POSIX CAS adversarial tests."""
import copy
import tempfile
import unittest
from pathlib import Path
import torch
from e5_delta_cas import (
    Invalid,ZERO,config,fresh,wave,state_hash,schedule,commit,restore,freeze,
)

class TestDelta(unittest.TestCase):
    @classmethod
    def setUpClass(cls):torch.set_num_threads(1)
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)/'store';self.root.mkdir(mode=0o700)
        self.cfg=config(64,8,20261014,'tenant.A','a'*64,'b'*64)
        self.s=fresh(self.cfg)
        wave(self.s,self.cfg,1)
        self.first=commit(self.root,self.cfg,1,ZERO,self.s)

    def test_second_wave_exact_and_only_wave_delta(self):
        start,_=restore(self.root,self.cfg,1)
        wave(start,self.cfg,2)
        cumulative=len(freeze(start,self.cfg))
        second=commit(self.root,self.cfg,1,self.first['manifest_sha256'],start)
        self.assertLess(second['snapshot_bytes'],cumulative)
        self.assertLess(second['snapshot_bytes'],second['full_head_fp32_bytes'])
        again,receipt=restore(self.root,self.cfg,1)
        self.assertEqual(state_hash(again),state_hash(start))
        self.assertEqual(receipt['wave'],2)
    def test_stale_cas_denied(self):
        state,_=restore(self.root,self.cfg,1);wave(state,self.cfg,2)
        commit(self.root,self.cfg,1,self.first['manifest_sha256'],state)
        with self.assertRaises(Invalid):commit(self.root,self.cfg,1,self.first['manifest_sha256'],state)
    def test_wrong_epoch_scope_fence_and_source_denied(self):
        for keyword,value in [('scope','tenant.B'),('fence','c'*64),('source','d'*64)]:
            cfg=dict(self.cfg);cfg[keyword]=value
            with self.subTest(field=keyword),self.assertRaises(Invalid):restore(self.root,cfg,1)
        with self.assertRaises(Invalid):restore(self.root,self.cfg,2)
    def test_missing_head_after_published_commit_denied(self):
        (self.root/'HEAD.json').unlink()
        with self.assertRaises(Invalid):restore(self.root,self.cfg,1)
    def test_checkpoint_bytes_tamper_denied(self):
        name=next((self.root/'objects').glob('*.safetensors'))
        with name.open('r+b') as f:f.seek(-10,2);f.write(b'abc')
        with self.assertRaises(Invalid):restore(self.root,self.cfg,1)
    def test_no_unauthorized_or_pretrained_origin_claim(self):
        self.assertFalse(self.first['production_promotion_permitted'])
        self.assertFalse(self.first['powerloss_or_wal_verified'])
    def test_wrong_training_lineage_denied(self):
        state,_=restore(self.root,self.cfg,1);wave(state,self.cfg,2)
        state['weights']['output.bias'][0,0]+=7
        with self.assertRaises(Invalid):commit(self.root,self.cfg,1,self.first['manifest_sha256'],state)
    def test_nonadvancing_second_wave_denied(self):
        state,_=restore(self.root,self.cfg,1)
        with self.assertRaises(Invalid):commit(self.root,self.cfg,1,self.first['manifest_sha256'],state)

if __name__=='__main__':unittest.main()
