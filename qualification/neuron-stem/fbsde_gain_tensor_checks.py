"""Actual small-model optimization on analytical fixtures, not pretrained evidence."""
import unittest
import torch
from fbsde_gain_policy import fit
from fbsde_depth_policy import scalar_score


class GainTensorChecks(unittest.TestCase):
    def test_identical_frequency_but_different_gain_magnitude_changes_the_fit(self):
        torch.set_num_threads(2);rows=[]
        for group in range(2):
            for i in range(40):
                positive=i%10<(9 if group==0 else 1)
                net=(.01 if positive else -.99) if group==0 else (.99 if positive else -.01)
                x=[0.]*15;x[0]=float(group);x[1]=1.-group
                rows.append(dict(source_id=f'train:{group}:{i}',features=x,outcome_gain=net+.002))
        a=fit(torch,rows,'frequency_v1');b=fit(torch,rows,'signed_gain_v2')
        self.assertEqual(a['initial_sha256'],b['initial_sha256']);self.assertEqual(a['parameters'],265)
        xa,xb=rows[0]['features'],rows[40]['features']
        self.assertGreater(scalar_score(a['state'],xa),scalar_score(a['state'],xb))
        self.assertLess(scalar_score(b['state'],xa),.5);self.assertGreater(scalar_score(b['state'],xb),.5)
        self.assertLess(b['losses'][-1],b['losses'][0])

    def test_zero_effective_weight_is_not_a_fitted_gate(self):
        rows=[dict(source_id='train:zero',features=[0.]*15,outcome_gain=.002)]
        with self.assertRaisesRegex(ValueError,'zero effective'):fit(torch,rows,'signed_gain_v2')

    def test_nonfinite_features_reject_before_optimizer(self):
        rows=[dict(source_id='train:nan',features=[float('nan')]*15,outcome_gain=1.)]
        with self.assertRaisesRegex(ValueError,'finite current'):fit(torch,rows,'frequency_v1')


if __name__=='__main__':unittest.main()
