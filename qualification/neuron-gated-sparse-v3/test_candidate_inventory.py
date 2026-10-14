#!/usr/bin/env python3
"""Actual safetensors bytes; safety and corruption tests are synthetic research only."""
from __future__ import annotations
import hashlib
import math
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from candidate_inventory import expected_geometry, verify_artifact, Q


def make_model(path, arm='v3', width=16, rank=2):
    import torch
    from safetensors.torch import save_file
    spec = expected_geometry(arm, width, rank if arm == 'min_gru' else None)
    tensors={}
    for name,(dtype,shape) in spec.items():
        value = torch.zeros(shape, dtype=torch.int64 if dtype=='I64' else torch.float32)
        if name=='structure.projection':
            value.fill_(Q)
        elif name == 'temporal.gate_bias':
            value.fill_(Q//2)
        elif name == 'temporal.decay_per_step':
            value.fill_(Q//2)
        tensors[name] = value
    save_file(tensors,str(path))
    return tensors


class CandidatePhysicalInventoryTests(unittest.TestCase):
    def setUp(self):
        self.tmp=TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.file=Path(self.tmp.name)/'candidate.safetensors'

    def call(self, arm='v3', width=16, rank=None, count=None):
        data = self.file.read_bytes()
        geometry = expected_geometry(arm,width,rank)
        if count is None:
            count=sum(math.prod(shape) for _,shape in geometry.values())
        return verify_artifact(self.file,hashlib.sha256(data).hexdigest(),arm=arm,
                               width=width,rank=rank,expected_count=count)

    def test_all_four_physical_arms(self):
        for arm in ('v2','v3','ssm','min_gru'):
            with self.subTest(arm=arm):
                make_model(self.file,arm=arm)
                r=self.call(arm=arm,rank=2 if arm=='min_gru' else None)
                self.assertTrue(r['native_q24_parameter_constraints_verified'])
                self.assertFalse(r['native_q24_prediction_parity_verified'])
                self.assertFalse(r['production_qualification'])

    def test_wrong_shape_even_with_same_total_parameters(self):
        import torch
        from safetensors.torch import save_file
        weights=make_model(self.file)
        weights['head.weight']=torch.zeros((2,8))
        save_file(weights,str(self.file))
        with self.assertRaisesRegex(ValueError,'shape'):
            self.call()

    def test_same_count_extra_tensor_and_missing_tensor(self):
        import torch
        from safetensors.torch import save_file
        weights=make_model(self.file)
        weights.pop('head.bias')
        weights['unexpected.bias']=torch.zeros((1,))
        save_file(weights,str(self.file))
        with self.assertRaisesRegex(ValueError,'missing or unexpected'):
            self.call()

    def test_nonfinite_f32(self):
        from safetensors.torch import save_file
        weights=make_model(self.file)
        weights['head.weight'][0,0]=float('nan')
        save_file(weights,str(self.file))
        with self.assertRaisesRegex(ValueError,'NaN'):
            self.call()

    def test_native_q24_v3_bias_negative(self):
        from safetensors.torch import save_file
        weights=make_model(self.file)
        weights['temporal.gate_bias'][0]=-1
        save_file(weights,str(self.file))
        with self.assertRaisesRegex(ValueError,'gate/decay'):
            self.call()

    def test_native_q24_ssm_decay_negative(self):
        from safetensors.torch import save_file
        weights=make_model(self.file,arm='ssm')
        weights['temporal.decay_per_step'][0]=-1
        save_file(weights,str(self.file))
        with self.assertRaisesRegex(ValueError,'gate/decay'):
            self.call(arm='ssm')

    def test_min_gru_factor_out_of_bounds(self):
        from safetensors.torch import save_file
        weights=make_model(self.file,arm='min_gru')
        weights['temporal.gate_input'][0,0]=Q+1
        save_file(weights,str(self.file))
        with self.assertRaisesRegex(ValueError,'out of bounds'):
            self.call(arm='min_gru',rank=2)

    def test_projection_not_exact_identity(self):
        from safetensors.torch import save_file
        weights=make_model(self.file)
        weights['structure.projection'][3]=Q-1
        save_file(weights,str(self.file))
        with self.assertRaisesRegex(ValueError,'frozen Q24 identity'):
            self.call()

    def test_physical_hash_mutation(self):
        make_model(self.file)
        sha=hashlib.sha256(self.file.read_bytes()).hexdigest()
        with self.file.open('ab') as f: f.write(b'evil')
        with self.assertRaisesRegex(ValueError,'SHA256 mismatch'):
            verify_artifact(self.file,sha,arm='v3',width=16,rank=None,expected_count=81)

    def test_symlinked_artifact_and_directory(self):
        make_model(self.file)
        alias=Path(self.tmp.name)/'alias.safetensors'
        alias.symlink_to(self.file)
        sha=hashlib.sha256(self.file.read_bytes()).hexdigest()
        with self.assertRaisesRegex(ValueError,'symlink'):
            verify_artifact(alias,sha,arm='v3',width=16,rank=None,expected_count=81)
        directory=Path(self.tmp.name)/'aliasdir'
        directory.symlink_to(Path(self.tmp.name),target_is_directory=True)
        with self.assertRaisesRegex(ValueError,'symlink'):
            verify_artifact(directory/'candidate.safetensors',sha,arm='v3',width=16,rank=None,expected_count=81)

    def test_min_gru_rank_invalid(self):
        with self.assertRaisesRegex(ValueError,'minGRU rank'):
            expected_geometry('min_gru',16,None)


if __name__=='__main__':
    unittest.main()
