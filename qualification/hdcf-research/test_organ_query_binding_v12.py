"""V12 source-first natural Beans/DINO/Granite adversarial tests; real ZIPs required.

No random-generated feature tensors are ever reported as pretrained model evidence.
No held labels are opened by the learner or during its parameter updates.
"""
from __future__ import annotations
import copy
import json
import os
from pathlib import Path
import tempfile
import unittest
from zipfile import ZipFile

import numpy as np

import organ_query_binding_v12 as m
import review_organ_binding_v12 as r

S = os.environ.get('HDCF_V12_SOURCE_ZIP', '/mnt/data/original-beans-source.zip')
F = os.environ.get('HDCF_V12_FEATURE_ZIP', '/mnt/data/original-beans-features.zip')
T = os.environ.get('HDCF_V12_TARGET_ZIP', '/mnt/data/original-beans-targets.zip')


class RealOriginalEvidence(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        for path in (S,F,T):
            if not Path(path).is_file():
                raise AssertionError('original immutable GitHub Actions ZIP required: '+path)
        cls.frozen = m.load_training_only(S,F)
        cls.pred = m.fit_and_seal(S,F)
        cls.tmp = tempfile.TemporaryDirectory()
        cls.pred_path = Path(cls.tmp.name)/'private-sealed.json'
        m.write_new(cls.pred_path,cls.pred)
        cls.review = r.review(source_zip=S,feature_zip=F,target_zip=T,
                              predictions=cls.pred_path)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_actual_pretrained_source_counts(self):
        self.assertEqual((len(self.frozen['train']),len(self.frozen['held'])),(36,24))
        self.assertEqual(self.frozen['train_X'].shape,(36,384))
        self.assertEqual(self.frozen['held_X'].shape,(24,384))

    def test_exact_three_nonduplicated_real_text_sources(self):
        self.assertEqual(self.frozen['T'].shape,(3,384))
        self.assertEqual(len(set(self.frozen['text_hashes'].values())),3)

    def test_original_model_revisions(self):
        self.assertEqual(len(m.DINO_REV),40)
        self.assertEqual(len(m.GRANITE_REV),40)
        self.assertEqual(len(m.DINO_WEIGHTS),64)

    def test_true_source_classes_train_only(self):
        self.assertEqual(sorted(np.bincount(self.frozen['train_labels'])),[12,12,12])
        self.assertFalse(any('target' in row or 'class_label' in row
                             for row in self.frozen['held']))

    def test_original_gram_isometry(self):
        p,s=m.permutation()
        original=self.frozen['T']
        transformed=original[:,p]*s[None,:]
        self.assertTrue(np.allclose(original@original.T,transformed@transformed.T,atol=1e-14))

    def test_actual_trained_organ_and_rotated_weights(self):
        d=self.pred['fit_cost']
        for name in d:
            self.assertEqual(d[name]['steps'],160)
            self.assertEqual(d[name]['parameters'],6144)
            self.assertEqual(d[name]['paid_scalar_updates'],983040)
            self.assertLess(d[name]['final_ce'],d[name]['start_ce'])

    def test_exact_numeric_prediction_parity(self):
        self.assertLess(self.pred['original_gram_invariant_max_score_abs_error'],1e-8)
        for row in self.pred['rows']:
            np.testing.assert_allclose(row['scores']['organ'],
                                       row['scores']['orthogonal_null'],atol=1e-8,rtol=0)

    def test_all_original_cues_are_present(self):
        self.assertEqual(self.pred['held_membership_pairs'],72)
        self.assertEqual(self.pred['train_membership_pairs'],108)
        self.assertTrue(all(len(row['scores']['organ'])==3 for row in self.pred['rows']))

    def test_bounded_binary_triplet_accounting(self):
        for arm,summary in self.review['arm_binary_membership'].items():
            self.assertEqual(summary['total'],72)
            self.assertEqual(summary['correct'],24+2*self.review['arm_correct_images'][arm])
        self.assertEqual(self.review['image_clusters'],24)

    def test_original_strong_vision_control_compared(self):
        self.assertEqual(self.review['arm_correct_images']['strong_original_dino'],20)
        self.assertEqual(self.review['arm_correct_images']['organ'],20)
        self.assertEqual(self.review['arm_correct_images']['visual_ridge'],20)
        self.assertEqual(self.review['paired_image_cluster_comparisons']['organ_versus_visual_ridge']['image_level_wins'],0)

    def test_wrong_text_cue_changes_task_predictions(self):
        self.assertEqual(self.review['arm_correct_images']['wrong_text_cue'],1)
        self.assertNotEqual(self.review['arm_correct_images']['wrong_text_cue'],
                            self.review['arm_correct_images']['organ'])

    def test_no_prod_or_semantic_gain_claim(self):
        for field in ('semantic_identifiability_proven',
                      'attention_or_time_reasoning_proven',
                      'service_rss_gpu_energy_p99_attested',
                      'automatic_cell_split_approved','production_authorized'):
            self.assertIs(self.review[field],False)
        self.assertEqual(self.review['disposition'],'HOLD_NO_GO_DENY_ALL')

    def test_24_cluster_paired_not_72_independent(self):
        self.assertEqual(r.paired_exact(1,1),1.0)
        self.assertEqual(r.paired_exact(0,0),1.0)
        self.assertEqual(r.paired_exact(12,0),2/(2**12))

    def test_prediction_seal_tamper_rejected(self):
        doc=copy.deepcopy(self.pred)
        doc['rows'][0]['scores']['organ'][0]+=0.125
        p=Path(self.tmp.name)/'tampered.json'
        m.write_new(p,doc)
        with self.assertRaises(m.Denied):
            r.review(source_zip=S,feature_zip=F,target_zip=T,predictions=p)

    def test_work_and_issuer_spoof_rejected(self):
        for field,val in [('paid_scalar_updates',123),('steps',0)]:
            doc=copy.deepcopy(self.pred)
            doc['fit_cost']['real_text_organ'][field]=val
            doc['prediction_seal_sha256']=m.sha(m.canonical({k:v for k,v in doc.items() if k!='prediction_seal_sha256'}))
            p=Path(self.tmp.name)/('spoof_'+field+'.json')
            m.write_new(p,doc)
            with self.assertRaises(m.Denied):
                r.review(source_zip=S,feature_zip=F,target_zip=T,predictions=p)

    def test_claimed_authority_rejected(self):
        doc=copy.deepcopy(self.pred)
        doc['production_authorized']=True
        doc['prediction_seal_sha256']=m.sha(m.canonical({k:v for k,v in doc.items() if k!='prediction_seal_sha256'}))
        p=Path(self.tmp.name)/'spoof_auth.json'
        m.write_new(p,doc)
        with self.assertRaises(m.Denied):
            r.review(source_zip=S,feature_zip=F,target_zip=T,predictions=p)

    def test_changed_case_group_rejected(self):
        doc=copy.deepcopy(self.pred)
        doc['rows'][0]['group_id']='fake'
        doc['prediction_seal_sha256']=m.sha(m.canonical({k:v for k,v in doc.items() if k!='prediction_seal_sha256'}))
        p=Path(self.tmp.name)/'spoof_group.json'
        m.write_new(p,doc)
        with self.assertRaises(m.Denied):
            r.review(source_zip=S,feature_zip=F,target_zip=T,predictions=p)

    def test_replaced_null_scores_rejected(self):
        doc=copy.deepcopy(self.pred)
        doc['rows'][1]['scores']['orthogonal_null']=[0.0,0.0,0.0]
        doc['prediction_seal_sha256']=m.sha(m.canonical({k:v for k,v in doc.items() if k!='prediction_seal_sha256'}))
        p=Path(self.tmp.name)/'spoof_null.json'
        m.write_new(p,doc)
        with self.assertRaises(m.Denied):
            r.review(source_zip=S,feature_zip=F,target_zip=T,predictions=p)

    def test_duplicate_source_rejected(self):
        doc=copy.deepcopy(self.pred)
        doc['rows'][1]['id']=doc['rows'][0]['id']
        doc['prediction_seal_sha256']=m.sha(m.canonical({k:v for k,v in doc.items() if k!='prediction_seal_sha256'}))
        p=Path(self.tmp.name)/'duplicate.json'
        m.write_new(p,doc)
        with self.assertRaises(m.Denied):
            r.review(source_zip=S,feature_zip=F,target_zip=T,predictions=p)

    def test_wrong_original_label_zip_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'corrupt.zip'
            path.write_bytes(Path(T).read_bytes()+b'X')
            with self.assertRaises(m.Denied):
                r.review(source_zip=S,feature_zip=F,target_zip=path,predictions=self.pred_path)

    def test_modified_original_model_feature_zip_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'corrupt.zip'
            path.write_bytes(Path(F).read_bytes()+b'X')
            with self.assertRaises(m.Denied):
                m.load_training_only(S,path)

    def test_missing_original_publisher_file_cannot_be_verified(self):
        with self.assertRaises(m.Denied):
            r.review(source_zip=S,feature_zip=F,target_zip=T,predictions=self.pred_path,
                     publisher_train='/nonexistent')

    def test_create_only_0600(self):
        path=Path(self.tmp.name)/'locked.json'
        m.write_new(path,{'ok':True})
        self.assertEqual(path.stat().st_mode & 0o777, 0o600)
        with self.assertRaises(FileExistsError):
            m.write_new(path,{'ok':False})

    def test_json_duplicate_and_nonfinite_rejected(self):
        with self.assertRaises(m.Denied):
            m.read_json(b'{"a":1,"a":2}')
        with self.assertRaises(m.Denied):
            m.read_json(b'{"x": NaN}')

    def test_unit_gradient_via_finite_difference(self):
        # Independently examine one actual gradient of rank-8 logits under
        # the same regularized cross entropy and fixed genuine TRAIN features.
        x=self.frozen['train_X']
        t=self.frozen['T']
        y=self.frozen['train_labels']
        rng=np.random.default_rng(m.SEED)
        a=rng.normal(0,.05,(m.WIDTH,m.RANK))
        b=rng.normal(0,.05,(m.WIDTH,m.RANK))
        def loss(A):
            scores=m.SCALE*((x@A)@(t@b).T)
            prob=m.sigmoid_scores(scores)
            return -np.mean(np.log(prob[np.arange(36),y])) + .5*m.L2*np.sum(A*A)
        prob=m.sigmoid_scores(m.SCALE*((x@a)@(t@b).T))
        err=prob.copy();err[np.arange(36),y]-=1;err/=36
        analytic=(m.SCALE*x.T@(err@(t@b))+m.L2*a)[3,4]
        pert=1e-6
        plus=a.copy();plus[3,4]+=pert
        minus=a.copy();minus[3,4]-=pert
        observed=(loss(plus)-loss(minus))/(2*pert)
        self.assertAlmostEqual(analytic,observed,places=6)


if __name__=='__main__':
    unittest.main()
