"""Actual Torch training and numeric teacher; no pretrained or language claim."""
import copy
import unittest
from unittest.mock import patch
import torch
from fbsde_depth_policy import fit_router, scalar_score, make_router, select_threshold
from fbsde_depth_study import numeric_inputs, teacher_row
from fbsde_depth_audit import score


class DepthTensorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        torch.set_num_threads(2)
        cls.rows=[teacher_row(r) for r in numeric_inputs(15485863,32,'train')]
        cls.fit=fit_router(torch,cls.rows)

    def test_actual_shared_router_learning(self):
        self.assertEqual(self.fit['parameters'],265)
        self.assertLess(self.fit['losses'][-1],self.fit['losses'][0])
        self.assertTrue(self.fit['teacher_is_model_not_observed_success'])

    def test_scalar_torch_parity_on_new_beliefs(self):
        m=make_router(torch);m.load_state_dict({k:torch.tensor(v) for k,v in self.fit['state'].items()});m.eval()
        rows=[teacher_row(r) for r in numeric_inputs(7919,8,'model_test')]
        x=torch.tensor([r['features'] for r in rows])
        with torch.inference_mode():y=m(x).sigmoid().tolist()
        for a,r in zip(y,rows):
            self.assertAlmostEqual(a,scalar_score(self.fit['state'],r['features']),places=6)
            self.assertAlmostEqual(a,score(self.fit['state'],r['features']),places=6)

    def test_training_rejects_test_partition_before_optimizer(self):
        rows=copy.deepcopy(self.rows);rows[0]['input']['source_id']='model_test:0'
        with self.assertRaisesRegex(ValueError,'training-only'):fit_router(torch,rows)

    def test_class_degenerate_training_does_not_fake_learning(self):
        rows=copy.deepcopy(self.rows)
        for row in rows:row['gain']=0.
        with self.assertRaisesRegex(ValueError,'both teacher classes'):fit_router(torch,rows)

    def test_threshold_selection_does_not_mutate_weights(self):
        before=copy.deepcopy(self.fit['state'])
        rows=[teacher_row(r) for r in numeric_inputs(15485917,16,'selection')]
        selected=select_threshold(rows,self.fit['state'],'learned')
        self.assertEqual(before,self.fit['state']);self.assertFalse(selected['selection_uses_external_outcomes'])


if __name__=='__main__':unittest.main()
