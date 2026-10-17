"""True CPU TRAIN-only centroid fitting, and adversarial heldout label admission."""
from __future__ import annotations

import unittest
import train_only_centroid_v5 as ctr


class TrainCalibratorTests(unittest.TestCase):
    def setUp(self):
        import torch
        self.torch = torch
        torch.manual_seed(9)
        # Four linearly separable synthetic classes, not original embeddings.
        train = []
        labels = []
        for cls in range(4):
            for _ in range(16):
                row=torch.randn(384)*.01
                row[cls]=1.0
                train.append(torch.nn.functional.normalize(row,dim=0))
                labels.append(cls)
        self.train=torch.stack(train)
        self.labels=labels
        self.held=self.train[:32].clone()
        self.sources=[{'case_id':f'heldout:{i:064x}',
                       'source_sha256':f'{i:064x}','text':'synthetic test input'}
                      for i in range(32)]

    def test_train_only_zero_sgd_leaves_test_labels_unseen(self):
        r=ctr.calculate(self.train,self.labels,self.held,self.sources)
        self.assertEqual(r['new_head_sgd_steps'],0)
        self.assertFalse(r['heldout_labels_used_for_calibration'])
        self.assertEqual(r['new_model_forward_calls'],0)
        self.assertEqual(r['fit_per_class_counts'],[16]*4)
        self.assertIn(r['selected_temperature'],ctr.TEMPERATURES)
        self.assertEqual(len(r['output_rows']),32)
        for out in r['output_rows']:
            self.assertEqual(set(out),{'case_id','source_sha256','probabilities'})
            self.assertAlmostEqual(sum(out['probabilities']),1,places=6)

    def test_minimizer_depends_only_on_fit_not_held_features(self):
        r=ctr.calculate(self.train,self.labels,self.held,self.sources)
        other=self.torch.randn_like(self.held)
        other=self.torch.nn.functional.normalize(other,dim=-1)
        s=ctr.calculate(self.train,self.labels,other,self.sources)
        self.assertEqual(r['selected_temperature'],s['selected_temperature'])
        self.assertEqual(r['fit_only_loocv_multiclass_brier'],
                         s['fit_only_loocv_multiclass_brier'])
        self.assertEqual(r['train_feature_digest'],s['train_feature_digest'])
        self.assertNotEqual(r['output_rows'],s['output_rows'])

    def test_changed_fit_data_changes_selected_digest(self):
        r=ctr.calculate(self.train,self.labels,self.held,self.sources)
        modified=self.train.clone()
        modified[0,0] += .1
        m=ctr.calculate(modified,self.labels,self.held,self.sources)
        self.assertNotEqual(r['train_feature_digest'],m['train_feature_digest'])

    def test_label_leakage_or_duplicate_heldout_identity_rejected(self):
        bad=[dict(x) for x in self.sources]
        bad[0]['label']=0
        with self.assertRaisesRegex(ValueError,'label-free'):
            ctr.calculate(self.train,self.labels,self.held,bad)
        bad=[dict(x) for x in self.sources]
        bad[0]['case_id']=bad[1]['case_id']
        with self.assertRaisesRegex(ValueError,'unique'):
            ctr.calculate(self.train,self.labels,self.held,bad)

    def test_nonfinite_or_invalid_fit_and_bad_width(self):
        with self.assertRaises(ValueError):
            ctr.calculate(self.train[:63],self.labels,self.held,self.sources)
        with self.assertRaises(ValueError):
            ctr.calculate(self.train,self.labels[:-1],self.held,self.sources)
        with self.assertRaises(ValueError):
            ctr.calculate(self.train,self.labels,self.held[:16],self.sources)
        corrupt=self.train.clone()
        corrupt[0,0]=float('nan')
        with self.assertRaises(ValueError):
            ctr.calculate(corrupt,self.labels,self.held,self.sources)


if __name__=='__main__':unittest.main()
