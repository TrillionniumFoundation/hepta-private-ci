"""Actual Torch-vs-NumPy Bridge operator parity on original V6 trained weights.

Test features are deliberately synthetic, NOT pretrained Granite feature
vectors; these results prove numerical semantics, not language or reasoning.
"""
import io
import json
from pathlib import Path
import random
import os
import unittest
import zipfile

import numpy as np
import torch
from torch.nn import functional as F

from bridge_gradient_archive_replay import V6_ZIP_SHA256, sha_file, decode_fp32_checkpoint, SHAPES
from bridge_numpy_forward import bridge_forward, weights_from_checkpoint
from bridge_numpy_reference_torch import reference

ARCHIVE = Path(os.environ.get("HEPTA_V6_ORIGINAL_ARCHIVE", "/UNAVAILABLE/hepta_bridge_learning_v6_20261015.zip"))



def probes(seed=349):
    generator=np.random.default_rng(seed)
    b,f,t=3,4,5
    facts=generator.normal(0,1,size=(b,f,t,384)).astype('float32')
    q=generator.normal(0,1,size=(b,3,384)).astype('float32')
    c=generator.normal(0,1,size=(b,2,384)).astype('float32')
    fm=np.ones((b,f,t),dtype='bool')
    fm[:,1,-1]=False
    fm[0,3,:]=False
    qm=np.ones((b,3),dtype='bool'); qm[1,-1]=False
    cm=np.ones((b,2),dtype='bool'); cm[2,-1]=False
    return (facts,q,c),(fm,qm,cm)


class MatchedRealV6(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        torch.set_num_threads(1)
        if not ARCHIVE.is_file():
            raise unittest.SkipTest('Original archived V6 absent; no fallback to fabricated weights')
        if sha_file(ARCHIVE)!=V6_ZIP_SHA256:
            raise AssertionError('original V6 archive identity mismatch')
        cls.archive=zipfile.ZipFile(ARCHIVE)

    @classmethod
    def tearDownClass(cls):
        if hasattr(cls,'archive'): cls.archive.close()

    def test_actual_pretrained_trained_v6_checkpoint_tensor_parity_all_seeds(self):
        features,masks=probes()
        for seed in (41,47,53):
            for name in ('warmup','natural_only','replay','contrastive'):
                with self.subTest(seed=seed,checkpoint=name):
                    raw=self.archive.read(f'reader-v6-bridge/seed-{seed}/bridge/{name}.pt')
                    arr,identity=weights_from_checkpoint(raw)
                    self.assertEqual(identity['parameter_count'],42562)
                    self.assertEqual(len(arr),22)
                    n=bridge_forward(arr,features,masks,steps=3,return_trace=True)
                    t=reference(arr,features,masks,steps=3)
                    for step,(ns,ts) in enumerate(zip(n['steps'],t)):
                        for a,b in zip(ns,ts):
                            self.assertLessEqual(float(np.max(np.abs(a-b))),0.0015,
                                f'{seed}/{name} hop {step} mismatch')

    def test_many_shapes_masked_empty_and_nonzero_feedback(self):
        raw=self.archive.read('reader-v6-bridge/seed-41/bridge/warmup.pt')
        arr,_=weights_from_checkpoint(raw)
        features,masks=probes(742)
        for steps in (1,3,8):
            for reset in (False,True):
                feedback=np.random.default_rng(steps).normal(size=(3,4)).astype('float32')
                trace=bridge_forward(arr,features,masks,steps=steps,feedback=feedback,reset_state=reset,return_trace=True)
                other=reference(arr,features,masks,steps=steps,feedback=feedback,reset_state=reset)
                for a,b in zip(trace['steps'],other):
                    self.assertLessEqual(float(np.max(np.abs(a[1]-b[1]))),0.0015)

    def test_import_without_pytorch_and_bounded_bad_input_denied(self):
        raw=self.archive.read('reader-v6-bridge/seed-47/bridge/warmup.pt')
        arr,_=weights_from_checkpoint(raw)
        features,masks=probes(884)
        with self.assertRaises(ValueError):bridge_forward(arr,features,masks,steps=9)
        with self.assertRaises(ValueError):bridge_forward(arr,features,masks,steps=0)
        with self.assertRaises(ValueError):bridge_forward(arr,tuple(x.astype('float64') for x in features),masks)
        with self.assertRaises(ValueError):bridge_forward(arr,features,(masks[0].astype('uint8'),)+masks[1:])
        with self.assertRaises(ValueError):bridge_forward({**arr,'project.weight':np.ones((32,384),dtype='float64')},features,masks)
        with self.assertRaises(ValueError):bridge_forward(arr,features,masks,feedback=np.ones((3,5),dtype='float32'))
        nan=features[0].copy();nan[0,0,0,0]=float('nan')
        with self.assertRaises(ValueError):bridge_forward(arr,(nan,*features[1:]),masks)
        with self.assertRaises(ValueError):bridge_forward(arr,features,masks,state=np.full((3,32),2.,dtype='float32'))

    def test_weight_mutation_affects_predictions(self):
        raw=self.archive.read('reader-v6-bridge/seed-53/bridge/warmup.pt')
        arr,_=weights_from_checkpoint(raw)
        features,masks=probes(228)
        old=bridge_forward(arr,features,masks)
        mutated=dict(arr)
        mutated['head.2.bias']=arr['head.2.bias'].copy()
        mutated['head.2.bias'][1]+=1.0
        result=bridge_forward(mutated,features,masks)
        self.assertGreater(float(np.max(np.abs(old-result))),0.9)



class SyntheticNoOriginalRequired(unittest.TestCase):
    """Numerical mechanisms always run, even when historical ZIP is absent."""
    @classmethod
    def setUpClass(cls):
        torch.set_num_threads(1)
        generator=torch.Generator().manual_seed(1907)
        state={key:torch.randn(shape,generator=generator,dtype=torch.float32)*.05
               for key,shape in SHAPES.items()}
        stream=io.BytesIO()
        torch.save(state,stream)
        cls.raw=stream.getvalue()
        cls.weights,cls.identity=weights_from_checkpoint(cls.raw)

    def test_synthetic_checkpoint_restricted_fp32_parity(self):
        self.assertEqual(self.identity['parameter_count'],42562)
        self.assertEqual(len(self.weights),22)
        features,masks=probes(399)
        for depth in (1,3,8):
            tested=bridge_forward(self.weights,features,masks,steps=depth,return_trace=True)
            expected=reference(self.weights,features,masks,steps=depth)
            for actual,correct in zip(tested['steps'],expected):
                for a,b in zip(actual,correct):
                    self.assertLess(float(np.max(np.abs(a-b))),0.0015)

    def test_all_evidence_deleted_and_no_question_token_remains_finite(self):
        features,masks=probes(875)
        facts,question,candidate=features
        fm,qm,cm=masks
        fm=np.zeros_like(fm)
        qm=np.zeros_like(qm)
        for step in (1,3):
            a=bridge_forward(self.weights,features,(fm,qm,cm),steps=step)
            b=reference(self.weights,features,(fm,qm,cm),steps=step)[-1][1]
            self.assertTrue(bool(np.isfinite(a).all()))
            self.assertLess(float(np.max(np.abs(a-b))),0.0015)

    def test_fact_permutation_no_order_ids(self):
        features,masks=probes(181)
        before=bridge_forward(self.weights,features,masks,steps=3)
        after=bridge_forward(self.weights,(features[0][:,::-1,:,:].copy(),*features[1:]),
            (masks[0][:,::-1,:].copy(),*masks[1:]),steps=3)
        self.assertLess(float(np.max(np.abs(before-after))),.0002)

    def test_invalid_input_and_nan_parameters_rejected(self):
        features,masks=probes(182)
        broken=dict(self.weights)
        broken['head.0.bias']=broken['head.0.bias'].copy()
        broken['head.0.bias'][0]=float('nan')
        with self.assertRaises(ValueError):bridge_forward(broken,features,masks)
        with self.assertRaises(ValueError):bridge_forward(self.weights,features,masks,steps=True)
        with self.assertRaises(ValueError):bridge_forward(self.weights,features,masks,reset_state='false')
        with self.assertRaises(ValueError):bridge_forward(self.weights,features,masks,return_trace=1)
        # Explicit candidate logit cannot become an effect capability.
        self.assertEqual(self.identity['torch_imported'],False)

    def test_tensor_bytes_not_exposed_by_default(self):
        ordinary=decode_fp32_checkpoint(self.raw)
        self.assertEqual(set(ordinary),{
          'training_parameter_sha256','execution_parameter_sha256',
          'parameter_count','tensor_count','all_values_finite','torch_imported'})
        export=decode_fp32_checkpoint(self.raw,include_tensor_bytes=True)
        self.assertEqual(len(export['tensor_bytes']),22)
        with self.assertRaises(ValueError):decode_fp32_checkpoint(self.raw,include_tensor_bytes=1)

if __name__=='__main__':unittest.main()
