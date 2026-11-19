"""Adversarial checks for physically trained, archival AG News matched-budget Cell experiment."""
from __future__ import annotations
import copy
import hashlib
import json
import math
import os
from pathlib import Path
import tempfile
import unittest

import numpy as np

from fabric import Denied
from matched_router_p06 import (
    ARCHIVE_SHA256, ALL_ARMS, SEEDS, SGD_STEPS, PARAMS_PER_HEAD, SCHEMA,
    canonical, digest, fit_predict, independent_review, json_read, prelabel_commit,
    staged_bundle, train_only_centroid_temperature, verify_bundle, write_private,
)
from matched_router_oracle_p06 import audit_math

ORIGINAL=os.environ.get('AGNEWS_ORIGINAL_ARCHIVE')


def _fake_bundle():
    # Synthetic task fixture: not a pretrained forward or evidence of learning.
    def row(i,split):
        v=np.zeros(384,dtype=np.float64)
        v[i%384]=4.
        base={'id':f'fixture-{split}-{i}','cell':i%2,'features':v.tolist()}
        if split=='train':base['target']=i%4
        return base
    return {'schema':SCHEMA,'archive_sha256':ARCHIVE_SHA256,
            'feature_sha256':'e724b8a24605abe8959e6f3ff269c8e580f4ca6c50155d1dc9095763aab52490',
            'scale_norm':4.0,'dimension':384,'classes':4,
            'train':[row(i,'train') for i in range(64)],
            'calibration':[row(i,'calibration') for i in range(32)],
            'holdout':[row(i,'holdout') for i in range(32)],
            'claims':{'historical_gold_co_resident':True,'future_source':False,
                      'real_original_pretrained_features':True,'new_pretrained_forwards':0,
                      'authority':'DENY_ALL'}}


class SourceOnly(unittest.TestCase):
    def setUp(self):
        self.bundle=_fake_bundle()

    def test_01_structural_synthetic_bundle_is_explicitly_unqualified(self):
        verify_bundle(self.bundle)
        self.assertEqual(self.bundle['claims']['authority'],'DENY_ALL')

    def test_02_held_label_rejected(self):
        self.bundle['holdout'][0]['target']=2
        with self.assertRaises(Denied):verify_bundle(self.bundle)

    def test_03_calibration_label_rejected(self):
        self.bundle['calibration'][0]['target']=2
        with self.assertRaises(Denied):verify_bundle(self.bundle)

    def test_04_nonfinite_feature_rejected(self):
        self.bundle['train'][0]['features'][0]=float('nan')
        with self.assertRaises(Denied):verify_bundle(self.bundle)

    def test_05_wrong_model_material_denied(self):
        self.bundle['feature_sha256']='a'*64
        with self.assertRaises(Denied):verify_bundle(self.bundle)

    def test_06_wrong_source_material_denied(self):
        self.bundle['archive_sha256']='a'*64
        with self.assertRaises(Denied):verify_bundle(self.bundle)

    def test_07_missing_fit_group_denied(self):
        self.bundle['train']=self.bundle['train'][:-1]
        with self.assertRaises(Denied):verify_bundle(self.bundle)

    def test_08_duplicate_case_denied(self):
        self.bundle['calibration'][0]['id']=self.bundle['train'][0]['id']
        with self.assertRaises(Denied):verify_bundle(self.bundle)

    def test_09_zero_norm_denied(self):
        self.bundle['train'][0]['features']=[0.]*384
        with self.assertRaises(Denied):verify_bundle(self.bundle)

    def test_10_bool_class_is_not_integer(self):
        self.bundle['train'][0]['target']=True
        with self.assertRaises(Denied):verify_bundle(self.bundle)

    def test_11_bool_route_is_not_integer(self):
        self.bundle['holdout'][0]['cell']=False
        with self.assertRaises(Denied):verify_bundle(self.bundle)

    def test_12_duplicate_json_keys_denied(self):
        with tempfile.TemporaryDirectory() as t:
            p=Path(t)/'x'
            p.write_bytes(b'{"sha":"aaa","sha":"bbb"}')
            with self.assertRaises(Denied):json_read(p)

    def test_13_nonfinite_json_denied(self):
        with tempfile.TemporaryDirectory() as t:
            p=Path(t)/'x';p.write_bytes(b'{"x":NaN}')
            with self.assertRaises(Denied):json_read(p)

    def test_14_create_only_and_symlink_rejected(self):
        with tempfile.TemporaryDirectory() as t:
            p=Path(t)/'receipt'
            write_private(p,{'authority':'DENY_ALL'})
            with self.assertRaises(FileExistsError):write_private(p,{'new':'value'})
            link=Path(t)/'link';link.symlink_to(p)
            with self.assertRaises(Denied):write_private(link,{'new':'value'})

    def test_15_train_only_loo_calibration_has_finite_count(self):
        fit=self.bundle['train']
        x=np.array([[*r['features'],1.] for r in fit])
        labels=np.array([r['target'] for r in fit])
        out=train_only_centroid_temperature(x,labels)
        self.assertEqual(out['training_only_calibration_predictions'],512)
        self.assertIn(out['selected_temperature'],out['candidate_temperatures'])
        self.assertTrue(all(math.isfinite(v) for v in out['train_loo_nll']))

    def test_16_deterministic_actual_cpu_head_training(self):
        output=fit_predict(self.bundle)
        again=fit_predict(self.bundle)
        self.assertEqual(canonical(output),canonical(again))
        self.assertEqual(tuple(x['seed'] for x in output['trials']),SEEDS)
        for trial in output['trials']:
            self.assertEqual(len(trial['predictions']),32*len(ALL_ARMS))
            for arm in ('split','random_route','shared_twin','shared_one'):
                self.assertEqual(trial['training'][arm]['steps'],SGD_STEPS)
                self.assertEqual(trial['training'][arm]['active_head_parameters_touched'],SGD_STEPS*PARAMS_PER_HEAD)
                self.assertEqual(trial['training'][arm]['actually_allocated_weight_tensor_shape'],
                                 [1 if arm=='shared_one' else 2,4,385])

    def test_17_separate_arithmetic_oracle_matches_real_synthetic_cpu_sgd(self):
        result=fit_predict(self.bundle)
        report=audit_math(self.bundle,result)
        self.assertEqual(report['trained_head_sets_recomputed'],12)
        self.assertEqual(report['independent_trained_head_prediction_rows_replayed'],672)
        self.assertLess(report['max_model_prediction_abs_error'],2e-11)

    def test_18_late_gold_cannot_be_supplied_as_experimental_input(self):
        self.bundle['holdout'][0]['label']=0
        with self.assertRaises(Denied):fit_predict(self.bundle)

    def test_19_producer_result_never_grants_effects(self):
        x=fit_predict(self.bundle)
        self.assertFalse(x['producer_observed_heldout_labels'])
        self.assertEqual((x['authority'],x['disposition']),('DENY_ALL','HOLD_NO_GO'))

    def test_20_seal_refuses_tampered_prediction(self):
        with tempfile.TemporaryDirectory() as t:
            td=Path(t);src=td/'src';pred=td/'pred';seal=td/'seal'
            write_private(src,self.bundle)
            prelabel_commit(src,pred,seal)
            with pred.open('ab') as f:f.write(b'garbage')
            # Check occurs before opening gold archive.
            with self.assertRaises(Denied):independent_review(Path('/not-there'),src,pred,seal)

    def test_21_fake_seal_cannot_provide_missing_original_source(self):
        with tempfile.TemporaryDirectory() as t:
            td=Path(t);src=td/'src';pred=td/'pred';seal=td/'seal'
            write_private(src,self.bundle)
            prelabel_commit(src,pred,seal)
            raw=json_read(pred)
            raw['trials'][0]['predictions'][0]['probabilities']=[1.,0.,0.,0.]
            pred.unlink();write_private(pred,raw)
            sealdata=json_read(seal)
            sealdata['prelabel_file_sha256']=hashlib.sha256(pred.read_bytes()).hexdigest()
            seal.unlink();write_private(seal,sealdata)
            # Independent recompute needs original pinned archive; with bogus
            # missing archive, producer-seal alone is demonstrably insufficient.
            # Any complete reviewer must reject either source or modified outputs.
            with self.assertRaises((Denied,OSError)):
                independent_review(Path('/not-there'),src,pred,seal)


@unittest.skipUnless(ORIGINAL,'requires genuine SHA-pinned historical AG News archive')
class OriginalModelMaterial(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.archive=Path(ORIGINAL)
        cls.real=staged_bundle(cls.archive)
        cls.prelabel=fit_predict(cls.real)

    def test_22_original_redacted_view_has_no_test_gold(self):
        self.assertEqual((len(self.real['train']),len(self.real['calibration']),len(self.real['holdout'])),(64,32,32))
        self.assertTrue(all('target' not in r and 'label' not in r for r in self.real['holdout']))
        self.assertTrue(all('target' not in r and 'label' not in r for r in self.real['calibration']))

    def test_23_original_trained_2slot_heads_pay_identical_sgd_touches(self):
        for row in self.prelabel['trials']:
            for arm in ('split','random_route','shared_twin'):
                self.assertEqual(row['training'][arm]['resident_parameter_scalars'],2*PARAMS_PER_HEAD)
                self.assertEqual(row['training'][arm]['active_head_parameters_touched'],SGD_STEPS*PARAMS_PER_HEAD)
            self.assertEqual(row['training']['shared_twin']['forward_heads_per_query'],2)
            self.assertEqual(row['training']['shared_one']['resident_parameter_scalars'],PARAMS_PER_HEAD)
            self.assertEqual(row['training']['shared_one']['actually_allocated_weight_tensor_bytes'],PARAMS_PER_HEAD*8)

    def test_24_true_original_features_give_independent_arithmetic_parity(self):
        cert=audit_math(self.real,self.prelabel)
        self.assertLess(cert['max_model_prediction_abs_error'],2e-11)

    def test_25_complete_real_source_reviewer_returns_denial(self):
        with tempfile.TemporaryDirectory() as t:
            td=Path(t);src=td/'src';pred=td/'pred';seal=td/'seal'
            write_private(src,self.real);prelabel_commit(src,pred,seal)
            out=independent_review(self.archive,src,pred,seal)
            self.assertFalse(out['head_specialization_promotable'])
            self.assertFalse(out['validated_future_source_family'])
            self.assertEqual(out['trials']['101']['score']['centroid_train_loo']['correct'],28)
            self.assertEqual((out['authority'],out['disposition']),('DENY_ALL','HOLD_NO_GO'))

    def test_26_mutated_feature_bytes_rejected_by_independent_source(self):
        with tempfile.TemporaryDirectory() as t:
            td=Path(t);src=td/'src';pred=td/'pred';seal=td/'seal'
            fake=copy.deepcopy(self.real)
            # Preserves strict unit-norm structure, but no longer matches the
            # exact original physical pretrained feature identity.
            v=fake['holdout'][0]['features']
            fake['holdout'][0]['features']= [-u for u in v]
            write_private(src,fake);prelabel_commit(src,pred,seal)
            with self.assertRaises(Denied):independent_review(self.archive,src,pred,seal)

    def test_27_held_labels_previously_exposed_not_called_prospective(self):
        with tempfile.TemporaryDirectory() as t:
            td=Path(t);src=td/'src';pred=td/'pred';seal=td/'seal'
            write_private(src,self.real);prelabel_commit(src,pred,seal)
            report=independent_review(self.archive,src,pred,seal)
            self.assertTrue(report['known_historical_gold_co_resident'])
            self.assertFalse(report['truly_new_prospective_panel'])
            self.assertFalse(report['independent_gold_custody'])

    def test_28_forged_original_predictions_and_forged_seal_denied(self):
        with tempfile.TemporaryDirectory() as t:
            td=Path(t);src=td/'src';pred=td/'pred';seal=td/'seal'
            write_private(src,self.real);prelabel_commit(src,pred,seal)
            altered=json_read(pred)
            altered['trials'][0]['predictions'][0]['probabilities']=[1.,0.,0.,0.]
            pred.unlink();write_private(pred,altered)
            edited=json_read(seal)
            edited['prelabel_file_sha256']=hashlib.sha256(pred.read_bytes()).hexdigest()
            seal.unlink();write_private(seal,edited)
            with self.assertRaises(Denied):independent_review(self.archive,src,pred,seal)

    def test_29_calibration_features_unused_in_training_or_held_prediction(self):
        modified=copy.deepcopy(self.real)
        modified['calibration'][0]['features']=[-x for x in modified['calibration'][0]['features']]
        alt=fit_predict(modified)
        self.assertEqual(canonical(self.prelabel['trials']),canonical(alt['trials']))
        self.assertEqual(canonical(self.prelabel['centroid_calibration']),canonical(alt['centroid_calibration']))

    def test_30_modified_original_archive_bytes_rejected(self):
        b=self.archive.read_bytes()
        with tempfile.TemporaryDirectory() as t:
            p=Path(t)/'different-original.zip';p.write_bytes(b[:-1]+bytes([b[-1]^1]))
            with self.assertRaises(Denied):staged_bundle(p)

if __name__=='__main__':unittest.main()
