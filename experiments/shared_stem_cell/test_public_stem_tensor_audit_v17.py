"""Synthetic checkpoint header fixtures only: no pretrained efficacy claims."""
import hashlib
from pathlib import Path
import tempfile
import unittest

import torch
from safetensors.torch import save_file
from public_stem_material_v8 import PINNED_RELEASES
from public_stem_tensor_audit_v17 import (audit_headers, TensorHeaderError,
                                         EMBEDDING, DECODER)

class HeaderAuditTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.model = self.root / 'model'; self.model.mkdir()
    def snapshot(self, tensors, candidate='mmbert-small'):
        path=self.model/'model.safetensors'
        save_file(tensors, path)
        return {'revision':PINNED_RELEASES[candidate], 'kind':'masked_lm',
                'files': {path.name:hashlib.sha256(path.read_bytes()).hexdigest()}}
    def test_embedding_and_decoder_reported_without_loading_weights(self):
        tensors={EMBEDDING:torch.zeros(4,3),DECODER:torch.zeros(4,3),
                 'model.norm.weight':torch.ones(3)}
        m=self.snapshot(tensors)
        report=audit_headers(self.model,m,'mmbert-small')
        self.assertEqual(report['tensor_count'],3)
        self.assertTrue(report['stored_modernbert_embedding'])
        self.assertTrue(report['stored_modernbert_decoder'])
        self.assertEqual(report['tied_tensor_geometry'][EMBEDDING]['shape'],[4,3])
        self.assertFalse(report['observed_forward'])
        self.assertEqual(report['authority'],'DENY_ALL')
    def test_source_embedding_absent_is_visible_without_fake_repair(self):
        m=self.snapshot({DECODER:torch.zeros(4,3)})
        report=audit_headers(self.model,m,'mmbert-small')
        self.assertFalse(report['stored_modernbert_embedding'])
        self.assertTrue(report['stored_modernbert_decoder'])
        self.assertFalse(report['loaded_checkpoint_verified'])
    def test_hash_drift_rejects_before_audit(self):
        m=self.snapshot({EMBEDDING:torch.ones(2,2)})
        (self.model/'model.safetensors').write_bytes(b'changed')
        with self.assertRaisesRegex(TensorHeaderError,'hash mismatch'):
            audit_headers(self.model,m,'mmbert-small')
    def test_other_source_or_wrong_revision_rejected(self):
        m=self.snapshot({EMBEDDING:torch.ones(2,2)})
        with self.assertRaisesRegex(TensorHeaderError,'immutable reviewed'):
            audit_headers(self.model,{**m,'revision':'e'*40},'mmbert-small')
        with self.assertRaisesRegex(TensorHeaderError,'unregistered'):
            audit_headers(self.model,m,'unreviewed_alias')
    def test_symlinked_weight_rejected(self):
        m=self.snapshot({EMBEDDING:torch.ones(2,2)})
        p=self.model/'model.safetensors'
        raw=self.root/'original.safetensors';p.rename(raw);p.symlink_to(raw)
        with self.assertRaisesRegex(TensorHeaderError,'linked'):
            audit_headers(self.model,m,'mmbert-small')

if __name__=='__main__': unittest.main()
