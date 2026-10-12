"""Actual Torch training on explicit fixtures, not empirical semantic results."""
import unittest
import torch
from fbsde_outcome_policy import fit
from fbsde_depth_policy import scalar_score


class TeacherTensorTests(unittest.TestCase):
    def setUp(self):
        torch.set_num_threads(2)
        self.rows=[{'source_id':f'train:{i}','features':[i%2]+[0.]*14,
                    'model_gain':float(i%2),'outcome_gain':float(1-i%2)} for i in range(32)]

    def test_matched_initialization_learns_opposite_verified_targets(self):
        a=fit(torch,self.rows,'model');b=fit(torch,self.rows,'outcome')
        self.assertEqual(a['initial_sha256'],b['initial_sha256'])
        for r in self.rows:
            self.assertEqual(scalar_score(a['state'],r['features'])>=.5,bool(r['model_gain']))
            self.assertEqual(scalar_score(b['state'],r['features'])>=.5,bool(r['outcome_gain']))

    def test_no_test_labels_or_nan_can_enter_fit(self):
        self.rows[0]['source_id']='test:0'
        with self.assertRaises(ValueError):fit(torch,self.rows,'outcome')
        self.rows[0]['source_id']='train:0';self.rows[0]['outcome_gain']=float('nan')
        with self.assertRaises(ValueError):fit(torch,self.rows,'outcome')

    def test_single_class_is_reported_not_filtered_or_fabricated(self):
        for r in self.rows:r['outcome_gain']=0.
        r=fit(torch,self.rows,'outcome')
        self.assertEqual(r['positive_labels'],0);self.assertEqual(r['parameters'],265)
        self.assertLess(r['losses'][-1],r['losses'][0])

if __name__=='__main__':unittest.main()
