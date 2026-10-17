"""All V13 tests use byte-pinned ORIGINAL DINO/Granite feature material.

No synthetic stand-in can replace the original publisher/model archive; tests
fail if original archives are not supplied. TEST targets enter reviewer only.
"""
import copy
import os
from pathlib import Path
import unittest

import numpy as np

import class_withheld_transfer_v13 as v


class OriginalClassWithheldTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = Path(os.environ['HDCF_V13_SOURCE_ZIP'])
        cls.features = Path(os.environ['HDCF_V13_FEATURE_ZIP'])
        cls.targets = Path(os.environ['HDCF_V13_TARGET_ZIP'])
        for f in (cls.source, cls.features, cls.targets):
            if not f.is_file():
                raise AssertionError('missing real source/feature/held-target archive')
        cls.data = v.load_training_only(cls.source,cls.features)
        cls.doc = v.build_prediction(cls.source,cls.features)

    def tampered(self):
        doc=copy.deepcopy(self.doc)
        doc['prediction_seal_sha256']=v.sha(v.canonical({
            k:x for k,x in doc.items() if k!='prediction_seal_sha256'}))
        return doc

    def assert_denied(self,doc):
        with self.assertRaises((v.Denied,ValueError,TypeError,KeyError,AssertionError)):
            v.verify_source_and_predictions(doc,self.source,self.features)

    def test_original_model_source_and_frozen_training_geometry(self):
        r=self.data
        v.checked_shape(r['train_X'],r['train_labels'],r['T'])
        self.assertEqual(r['held_X'].shape,(24,384))
        self.assertEqual(set(r['strong']),{x['case_id'] for x in r['held']})
        self.assertEqual(len(set(r['text_hashes'].values())),3)

    def test_exact_three_real_paid_organ_models(self):
        self.assertEqual(set(self.doc['folds']),set(v.FOLDS))
        for k,name in enumerate(v.FOLDS):
            cost=self.doc['folds'][name]['work']
            self.assertEqual(cost['steps'],160)
            self.assertEqual(cost['parameter_count'],6144)
            self.assertEqual(cost['paid_scalar_updates'],983040)
            self.assertEqual(cost['seen_class_indices'],[z for z in range(3) if z!=k])
            self.assertEqual(cost['withheld_images_fit'],0)
            self.assertEqual(cost['train_images'],24)

    def test_independent_original_optimizers_and_complete_predictions(self):
        v.verify_source_and_predictions(self.doc,self.source,self.features)

    def test_late_source_labels_and_three_fold_actual_outcomes(self):
        review=v.review_after_seal(self.doc,self.source,self.features,self.targets)
        self.assertEqual([review['unseen_class_per_fold'][name]['unseen_correct']
                         for name in v.FOLDS],[1,1,0])
        self.assertEqual([review['unseen_class_per_fold'][name]['total_correct']
                         for name in v.FOLDS],[16,16,13])
        self.assertEqual(review['privileged_frozen_visual_prototype_correct'],20)
        self.assertEqual(review['vision_only_ridge_correct'],20)
        self.assertEqual(review['full_three_class_trained_organ_correct'],20)
        self.assertEqual(review['disposition'],'HOLD_NO_GO_DENY_ALL')
        self.assertFalse(review['future_time_generalization_proven'])
        self.assertFalse(review['unseen_class_learned_semantics_proven'])

    def test_all_test_case_ids_exact_and_unique(self):
        originals=[x['case_id'] for x in self.data['held']]
        for key in v.FOLDS:
            self.assertEqual([x['id'] for x in self.doc['folds'][key]['rows']],originals)
            self.assertEqual(len(set(originals)),24)

    def test_incomplete_fold_denied(self):
        d=copy.deepcopy(self.doc);d['folds'].pop('healthy');self.assert_denied(self.tampered_doc(d))

    @staticmethod
    def tampered_doc(d):
        d['prediction_seal_sha256']=v.sha(v.canonical({k:x for k,x in d.items() if k!='prediction_seal_sha256'}))
        return d

    def test_forged_original_output_with_resigned_seal_rejected(self):
        d=copy.deepcopy(self.doc)
        d['folds']['angular_leaf_spot']['rows'][0]['scores'][0]+=0.15
        self.assert_denied(self.tampered_doc(d))

    def test_forged_actual_sgd_weights_with_resigned_seal_rejected(self):
        d=copy.deepcopy(self.doc)
        d['folds']['bean_rust']['work']['weights_sha256']='f'*64
        self.assert_denied(self.tampered_doc(d))

    def test_train_withheld_example_contribution_rejected(self):
        d=copy.deepcopy(self.doc)
        d['folds']['healthy']['work']['withheld_images_fit']=1
        self.assert_denied(self.tampered_doc(d))

    def test_wrong_organ_exclusion_rejected(self):
        d=copy.deepcopy(self.doc)
        d['folds']['healthy']['work']['seen_class_indices']=[0,2]
        self.assert_denied(self.tampered_doc(d))

    def test_missing_image_and_duplicated_original_id_rejected(self):
        d=copy.deepcopy(self.doc)
        d['folds']['bean_rust']['rows'][0]['id']=d['folds']['bean_rust']['rows'][1]['id']
        self.assert_denied(self.tampered_doc(d))

    def test_tampered_privileged_original_baseline_rejected(self):
        d=copy.deepcopy(self.doc)
        d['frozen_three_class_visual_reference'][0]['predicted_class']='healthy' if d['frozen_three_class_visual_reference'][0]['predicted_class']!='healthy' else 'bean_rust'
        self.assert_denied(self.tampered_doc(d))

    def test_false_future_or_promotion_claim_rejected(self):
        for field,value in [('original_historical_public_not_future',False),
                            ('production_authorized',True),
                            ('automatic_cell_split_authorized',True),
                            ('zero_shot_semantic_transfer_verified',True),
                            ('new_pretrained_model_forwards',1)]:
            d=copy.deepcopy(self.doc);d[field]=value
            with self.subTest(field=field):self.assert_denied(self.tampered_doc(d))

    def test_wrong_archive_identity_denied(self):
        with self.assertRaises(v.Denied):
            v.verify_source_and_predictions(self.doc,self.targets,self.features)
        with self.assertRaises(v.Denied):
            v.review_after_seal(self.doc,self.source,self.features,self.source)

    def test_wrong_visual_prototype_or_ridge_scores_denied(self):
        d=copy.deepcopy(self.doc)
        d['vision_only_ridge_scores'][0][0]+=0.2
        self.assert_denied(self.tampered_doc(d))

    def test_no_claim_that_24_images_are_72_independent_sources(self):
        out=v.review_after_seal(self.doc,self.source,self.features,self.targets)
        self.assertEqual(out['held_images'],24)
        self.assertEqual([z['historical_unseen_class_test_images'] for z in out['unseen_class_per_fold'].values()],[8,8,8])
        self.assertFalse(out['independent_source_issuers_verified'])


if __name__=='__main__':
    unittest.main()
