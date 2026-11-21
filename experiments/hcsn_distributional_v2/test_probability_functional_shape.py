"""Source-exact P2 expected-event/reward batch accounting shape regressions.

These do not establish trained neural memory or task gains.
"""
import unittest
import torch

from .stable_probability import (advance_probability, REGENERATIVE_PROBABILITY)


class FunctionalShapeGateTests(unittest.TestCase):
    def setUp(self):
        self.p = torch.tensor([[.2,.3,.5],[.3,.3,.4]],dtype=torch.float64)
        self.identity = torch.eye(3,dtype=torch.float64)

    def test_extra_event_batch_axis_is_rejected(self):
        # Old code returns [2,2] event counts although transition output is [2,3].
        bad = torch.tensor([[[1.,2.,3.]],[[3.,2.,1.]]], dtype=torch.float64)
        with self.assertRaisesRegex(ValueError,'batch axes'):
            advance_probability(self.p,self.identity,operator_kind=REGENERATIVE_PROBABILITY,
                                event_vector=bad)

    def test_extra_reward_batch_axis_is_rejected(self):
        bad = torch.tensor([[[1.,-2.,3.]],[[3.,-2.,1.]]], dtype=torch.float64)
        with self.assertRaisesRegex(ValueError,'batch axes'):
            advance_probability(self.p,self.identity,operator_kind=REGENERATIVE_PROBABILITY,
                                reward_vector=bad)

    def test_existing_shared_and_per_batch_vectors_preserve_expected_counts(self):
        shared=torch.tensor([0.,2.,3.],dtype=torch.float64)
        per_batch=torch.tensor([[0.,2.,3.],[3.,0.,1.]],dtype=torch.float64)
        for vec in (shared,per_batch):
            out=advance_probability(self.p,self.identity,operator_kind=REGENERATIVE_PROBABILITY,
                                    event_vector=vec,reward_vector=-vec)
            expected=(self.p*vec).sum(-1)
            self.assertEqual(tuple(out['events'].shape),(2,))
            self.assertTrue(torch.allclose(out['events'],expected,rtol=0,atol=1e-14))
            self.assertTrue(torch.allclose(out['reward'],-expected,rtol=0,atol=1e-14))

    def test_operator_expansion_shared_start_is_supported(self):
        # A single initial probability can be broadcast to multiple operators.
        start=torch.tensor([.2,.3,.5],dtype=torch.float64)
        operators=torch.stack((self.identity,self.identity))
        counts=torch.tensor([0.,2.,3.],dtype=torch.float64)
        out=advance_probability(start,operators,operator_kind=REGENERATIVE_PROBABILITY,
                                event_vector=counts)
        self.assertEqual(tuple(out['probability'].shape),(2,3))
        self.assertEqual(tuple(out['events'].shape),(2,))
        self.assertTrue(torch.allclose(out['events'],torch.full((2,),2.1,dtype=torch.float64)))

    def test_event_gradient_through_broadcast_is_retained(self):
        start=torch.tensor([.2,.3,.5],dtype=torch.float64,requires_grad=True)
        operators=torch.stack((self.identity,self.identity))
        weights=torch.tensor([[0.,2.,3.],[3.,0.,1.]],dtype=torch.float64)
        out=advance_probability(start,operators,operator_kind=REGENERATIVE_PROBABILITY,
                                event_vector=weights)
        self.assertEqual(tuple(out['events'].shape),(2,))
        grad=torch.autograd.grad(out['events'].sum(),start)[0]
        self.assertTrue(torch.allclose(grad,weights.sum(0)))


if __name__=='__main__':
    unittest.main()
