"""P2 research-only: prevent transition batches from silently multiplying a batch of states.

These are numerical accounting checks, not repeated physical event evidence.
"""
import unittest

import torch

from .stable_probability import advance_probability, REGENERATIVE_PROBABILITY


class TransitionBatchGateTests(unittest.TestCase):
    def setUp(self):
        self.start = torch.tensor([[.2, .3, .5], [.3, .3, .4]], dtype=torch.float64)
        self.identity = torch.eye(3, dtype=torch.float64)

    def run_step(self, p, operator, **kwargs):
        return advance_probability(p, operator, operator_kind=REGENERATIVE_PROBABILITY, **kwargs)

    def test_cross_batch_cartesian_operator_must_refuse_without_functional(self):
        # Previously: two input states x two implicit operator batches => [2,2,3].
        operator = self.identity.expand(2, 1, 3, 3)
        with self.assertRaisesRegex(ValueError, 'unintended batch axes'):
            self.run_step(self.start, operator)

    def test_cross_batch_event_and_reward_must_refuse(self):
        operator = self.identity.expand(2, 1, 3, 3)
        vector = torch.tensor([0., 1., 2.], dtype=torch.float64)
        with self.assertRaisesRegex(ValueError, 'unintended batch axes'):
            self.run_step(self.start, operator, event_vector=vector, reward_vector=-vector)

    def test_leading_singleton_operator_axis_cannot_change_batch_rank(self):
        operator = self.identity.expand(1, 2, 3, 3)
        with self.assertRaisesRegex(ValueError, 'unintended batch axes'):
            self.run_step(self.start, operator)

    def test_singleton_state_batch_cannot_implicitly_expand_to_operators(self):
        operator = self.identity.expand(4, 3, 3)
        with self.assertRaisesRegex(ValueError, 'unintended batch axes'):
            self.run_step(self.start[:1], operator)

    def test_unbroadcastable_batches_raise_public_value_error(self):
        operator = self.identity.expand(3, 3, 3)
        with self.assertRaisesRegex(ValueError, 'incompatible.*batch axes'):
            self.run_step(self.start, operator)

    def test_aligned_and_shared_operators_preserve_values_and_gradients(self):
        p = self.start.clone().requires_grad_()
        weights = torch.tensor([[0., 1., 2.], [3., 0., 1.]], dtype=torch.float64)
        for op in (self.identity, self.identity.expand(2, 3, 3)):
            out = self.run_step(p, op, event_vector=weights, reward_vector=-weights)
            self.assertEqual(tuple(out['probability'].shape), (2, 3))
            self.assertTrue(torch.equal(out['probability'], p))
            self.assertTrue(torch.allclose(out['events'], (p * weights).sum(-1)))
            self.assertTrue(torch.allclose(out['reward'], -(p * weights).sum(-1)))
            grad = torch.autograd.grad(out['events'].sum(), p, retain_graph=True)[0]
            self.assertTrue(torch.equal(grad, weights))

    def test_single_unbatched_state_can_expand_to_operator_batches(self):
        p = self.start[0].clone().requires_grad_()
        operator = self.identity.expand(2, 4, 3, 3)
        vector = torch.tensor([0., 1., 2.], dtype=torch.float64)
        out = self.run_step(p, operator, event_vector=vector)
        self.assertEqual(tuple(out['probability'].shape), (2, 4, 3))
        self.assertEqual(tuple(out['events'].shape), (2, 4))
        self.assertTrue(torch.allclose(out['events'], torch.full((2, 4), 1.3, dtype=torch.float64)))
        grad = torch.autograd.grad(out['events'].sum(), p)[0]
        self.assertTrue(torch.equal(grad, 8 * vector))

    def test_batched_state_may_broadcast_over_singleton_operator_batch(self):
        out = self.run_step(self.start, self.identity.expand(1, 3, 3))
        self.assertEqual(tuple(out['probability'].shape), (2, 3))


if __name__ == '__main__':
    unittest.main()
