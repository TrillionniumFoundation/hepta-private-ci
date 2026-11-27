"""Mechanistic and data-fairness checks; scientific gate remains open."""
import math
import unittest
import numpy as np
import torch
from .p1_factorial import (ARMS,TASKS,REPLACE,make_basis_table,interpolate_basis,
                           make_data,encoder_z,RecurrentReadout,run_full)

class AttributionContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        torch.set_num_threads(1)
        cls.table=make_basis_table()

    def test_all_eight_bases_active_matched_value_and_signed_slope(self):
        table=self.table
        z=np.array([-.0001,0.,.0001])
        for arm in ARMS:
            with self.subTest(arm=arm):
                a=interpolate_basis(table,arm,z)
                self.assertLess(float(np.max(np.abs(a[1]))),1e-9)
                # Linear interpolation on the symmetric fine grid, no slope sign flips.
                deriv=(a[2]-a[0])/.0002
                self.assertLess(float(np.max(np.abs(deriv-1.))),.045)
                self.assertGreater(min(table['columns'][arm]['singular_values']),1e-4)
        self.assertEqual(len(ARMS),8)
        self.assertEqual(len(REPLACE['all_three']),3)

    def test_frozen_encoder_data_no_future_target_leakage(self):
        for task in TASKS:
            for length in (12,28):
                x,y=make_data(task,n=127,length=length,seed=3940+length)
                self.assertEqual(x.shape,(127,length,3))
                self.assertTrue(np.all((y==0)|(y==1)))
                self.assertTrue(np.all(np.abs(encoder_z(x))<=1))
                if task=='selective_copy':
                    for i in range(127):
                        marked=np.flatnonzero(x[i,:,1]==1)
                        self.assertEqual(len(marked),1)
                        self.assertEqual(y[i],float(x[i,marked[0],0]>0))
                else:
                    for i in range(127):
                        query=x[i,-1,0]
                        matched=np.where(x[i,:-1,0]==query)[0]
                        self.assertEqual(y[i],float(x[i,matched[-1],1]>0))

    def test_all_parameters_active_and_identical_model_structure(self):
        torch.manual_seed(404)
        m=RecurrentReadout(hidden=20)
        self.assertEqual(sum(p.numel() for p in m.parameters() if p.requires_grad),561)
        x=torch.tensor([[[1.,0.,.4]]*8]*4)
        for arm in ARMS:
            features=torch.from_numpy(interpolate_basis(self.table,arm,encoder_z(x.numpy())))
            logits=m(x,features)
            m.zero_grad(set_to_none=True)
            logits.sum().backward()
            self.assertTrue(all(p.grad is not None for p in m.parameters()))
            self.assertTrue(torch.isfinite(logits).all())

    def test_complete_seeded_smoke_and_no_false_gate(self):
        r=run_full(seeds=(0,),updates=4,batch=12,train_count=48,test_count=32)
        self.assertEqual(r['candidate_count'],16)
        self.assertEqual(len(r['summary']),16)
        self.assertEqual(r['active_param_count'],561)
        self.assertFalse(r['production_activation'])
        self.assertFalse(r['all_scientific_blockers_closed'])
        self.assertTrue(all(math.isfinite(a['ood_acc']) for a in r['records']))
        self.assertEqual(sum(v['arm']!='ordinary' for v in r['summary']),14)

    def test_invalid_input_refusal(self):
        with self.assertRaises(ValueError):
            interpolate_basis(self.table,'fake',np.zeros(1))
        with self.assertRaises(ValueError):
            interpolate_basis(self.table,'ordinary',np.array([1.2]))
        with self.assertRaises(ValueError):
            make_data('unknown',n=10,length=12,seed=0)

if __name__=='__main__':unittest.main()
