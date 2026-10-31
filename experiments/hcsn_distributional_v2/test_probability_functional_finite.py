"""P2 reject nonfinite accumulated expectations; does not certify real events."""
import unittest

import torch

from .stable_probability import advance_probability, REGENERATIVE_PROBABILITY


class FunctionalFiniteGateTests(unittest.TestCase):
    def test_float32_event_sum_overflow_must_refuse(self):
        # Input is accepted by the declared 8-epsilon mass guard; the
        # expected count is infinite after multiplication/reduction.
        p=torch.tensor([.50000006,.50000006],dtype=torch.float32)
        weight=torch.full((2,),torch.finfo(torch.float32).max)
        with self.assertRaisesRegex(ValueError,'Nonfinite accumulated event vector'):
            advance_probability(p,torch.eye(2),operator_kind=REGENERATIVE_PROBABILITY,
                                event_vector=weight)

    def test_float32_negative_reward_sum_overflow_must_refuse(self):
        p=torch.tensor([.50000006,.50000006],dtype=torch.float32)
        weight=torch.full((2,),-torch.finfo(torch.float32).max)
        with self.assertRaisesRegex(ValueError,'Nonfinite accumulated reward vector'):
            advance_probability(p,torch.eye(2),operator_kind=REGENERATIVE_PROBABILITY,
                                reward_vector=weight)

    def test_float64_accumulation_overflow_must_refuse(self):
        p=torch.tensor([.5000000000001,.5000000000001],dtype=torch.float64)
        identity=torch.eye(2,dtype=torch.float64)
        weight=torch.full((2,),torch.finfo(torch.float64).max,dtype=torch.float64)
        for key in ('event_vector','reward_vector'):
            with self.subTest(key=key):
                with self.assertRaisesRegex(ValueError,'Nonfinite accumulated'):
                    advance_probability(p,identity,operator_kind=REGENERATIVE_PROBABILITY,
                                        **{key:weight})

    def test_finite_boundary_expectation_preserves_dtype_and_gradients(self):
        # Exact unit mass and max finite vector are still representable.
        p=torch.tensor([.5,.5],dtype=torch.float32,requires_grad=True)
        weight=torch.full((2,),torch.finfo(torch.float32).max)
        out=advance_probability(p,torch.eye(2),operator_kind=REGENERATIVE_PROBABILITY,
                                event_vector=weight,reward_vector=-weight)
        self.assertEqual(out['events'].dtype,torch.float32)
        self.assertEqual(out['events'].item(),torch.finfo(torch.float32).max)
        self.assertEqual(out['reward'].item(),-torch.finfo(torch.float32).max)
        grad=torch.autograd.grad(out['events'],p)[0]
        self.assertTrue(torch.equal(grad,weight))


if __name__=='__main__':
    unittest.main()
