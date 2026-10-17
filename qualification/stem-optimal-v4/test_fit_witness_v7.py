"""Original FP32 tensor-backed producer vs independent stdlib FIT-only LOO replay.

Hermetic numeric experiments are synthetic and do not constitute new EG2 forwards.
"""
from __future__ import annotations

import copy
import hashlib
import json
import math
import struct
import unittest

import fit_witness_v7 as producer
import review_fit_witness_v7 as observer
import train_only_centroid_v5 as baseline


def canonical(data):
    return json.dumps(data,sort_keys=True,ensure_ascii=False,
                      allow_nan=False,separators=(',',':')).encode()


class OriginalFitReplayTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import torch
        import torch.nn.functional as F
        torch.set_num_threads(2)
        torch.manual_seed(341)
        cls.train=[]
        cls.labels=[]
        fit=[]
        for klass in range(4):
            for i in range(16):
                feat=torch.randn(384, dtype=torch.float32)*0.06
                feat[klass] += 0.6
                cls.train.append(F.normalize(feat,dim=0))
                cls.labels.append(klass)
                text=f'public fit synthetic category {klass} example {i}'
                sha=hashlib.sha256(text.encode()).hexdigest()
                fit.append({'case_id':'fit:'+sha,'source_sha256':sha,
                            'text':text,'label':klass})
        cls.train=torch.stack(cls.train)
        cls.held=F.normalize(torch.randn(32,384),dim=-1)
        held=[]
        for i in range(32):
            text=f'public heldout synthetic example {i}'
            sha=hashlib.sha256(text.encode()).hexdigest()
            held.append({'case_id':'heldout:'+sha,'source_sha256':sha,'text':text})
        cls.source={'train':fit,'heldout':held,'cohort':'hard-charge-four-intents-v3',
                    'research_only':True,'production_authorized':False}
        cls.source['source_plan_sha256']=hashlib.sha256(canonical(cls.source)).hexdigest()
        cls.cal=baseline.calculate(cls.train,cls.labels,cls.held,held)
        cls.witness=producer.build(cls.source,cls.train,cls.cal,
                                   source_weight_sha256=observer.MODEL_WEIGHT_SHA,
                                   projection=observer.PROJECTION)
        cls.receipt={'source_plan_sha256':cls.source['source_plan_sha256'],
                     'actual_weight_sha256':observer.MODEL_WEIGHT_SHA,
                     'model_repo':observer.MODEL_REPO,
                     'model_revision':observer.MODEL_REVISION,
                     'projection':observer.PROJECTION,
                     'train_only_centroid':cls.cal,
                     'fit_feature_witness_sha256':hashlib.sha256(canonical(cls.witness)).hexdigest(),
                     'production_authorized':False,'authority':'DENY_ALL'}

    def test_original_float32_calibration_replays_without_torch_in_observer(self):
        result=observer.verify(self.source,self.witness,self.receipt)
        self.assertEqual(result['fit_examples_replayed'],64)
        self.assertLess(result['max_loss_abs_error_vs_fp32'],5e-5)
        self.assertEqual(result['independently_replayed_temperature'],
                         self.cal['selected_temperature'])
        self.assertFalse(result['heldout_gold_seen'])
        self.assertEqual(result['new_encoder_forwards'],0)

    def test_feature_payload_change_even_if_witness_resealed(self):
        witness=copy.deepcopy(self.witness)
        witness['rows'][1]['fp32'][0] += 0.0001
        receipt=copy.deepcopy(self.receipt)
        receipt['fit_feature_witness_sha256']=hashlib.sha256(canonical(witness)).hexdigest()
        with self.assertRaisesRegex(ValueError,'FIT source tensor/label bytes mismatch|exact finite FP32'):
            observer.verify(self.source,witness,receipt)

    def test_source_label_swap_or_roster_tamper(self):
        source=copy.deepcopy(self.source)
        source['train'][1]['label']=(source['train'][1]['label']+1)%4
        with self.assertRaisesRegex(ValueError,'source plan digest'):
            observer.verify(source,self.witness,self.receipt)
        source=copy.deepcopy(self.source)
        source['heldout'][0]['label']=0
        with self.assertRaisesRegex(ValueError,'TEST gold leaked'):
            observer.verify(source,self.witness,self.receipt)

    def test_claimed_fit_loss_or_selected_temperature_tamper(self):
        for mutate in (lambda c: c['fit_only_loocv_multiclass_brier'].__setitem__(0,0.1),
                       lambda c: c.__setitem__('selected_temperature', 0.333)):
            receipt=copy.deepcopy(self.receipt)
            mutate(receipt['train_only_centroid'])
            with self.assertRaises(ValueError):
                observer.verify(self.source,self.witness,receipt)

    def test_model_digest_or_receipt_binding_tamper(self):
        for key,value in [('model_weights_sha256','f'*64),('projection','fake'),
                          ('label_free_heldout',False),('production_authorized',True)]:
            w=copy.deepcopy(self.witness);w[key]=value
            r=copy.deepcopy(self.receipt)
            r['fit_feature_witness_sha256']=hashlib.sha256(canonical(w)).hexdigest()
            with self.assertRaises(ValueError):
                observer.verify(self.source,w,r)
        r=copy.deepcopy(self.receipt)
        r['fit_feature_witness_sha256']='0'*64
        with self.assertRaises(ValueError):
            observer.verify(self.source,self.witness,r)

    def test_no_float64_fabrication_or_nonfinite_features(self):
        w=copy.deepcopy(self.witness)
        w['rows'][0]['fp32'][0]+=1e-10
        r=copy.deepcopy(self.receipt)
        r['fit_feature_witness_sha256']=hashlib.sha256(canonical(w)).hexdigest()
        with self.assertRaisesRegex(ValueError,'exact finite FP32'):
            observer.verify(self.source,w,r)
        w=copy.deepcopy(self.witness)
        w['rows'][0]['fp32'][0]=float('nan')
        r=copy.deepcopy(self.receipt)
        # Do not allow serializing NaN into a content digest.
        with self.assertRaises(ValueError):canonical(w)

    def test_producer_rejects_mismatched_feature_digest(self):
        import torch
        changed=self.train.clone()
        changed[0,0]+=0.0001
        with self.assertRaises(ValueError):
            producer.build(self.source,changed,self.cal,
                           source_weight_sha256=observer.MODEL_WEIGHT_SHA,
                           projection=observer.PROJECTION)

if __name__=='__main__':unittest.main()
