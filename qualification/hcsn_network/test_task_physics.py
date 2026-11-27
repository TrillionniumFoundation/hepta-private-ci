"""Value/flow identity and actual coupled gradients on one fixed episode grid."""

from fractions import Fraction
import unittest

import torch

from qualification.hcsn_currentstate.differentiable import Work, advance, initial, refractory
from .task_physics import continuation_value, finite_policy_value, task_physics


THETA = [-.2, .55, .3, 1.2, .8, .25, .15]


class TaskPhysicsTests(unittest.TestCase):
    def test_full_state_value_and_signed_content_conservation(self):
        theta = torch.tensor(THETA, dtype=torch.float64)
        episode = task_physics(theta)
        probability = episode.initial_probability
        state = initial(torch.stack((probability, probability*.7, -probability*.3)))
        values, _ = finite_policy_value(episode.physics)
        reference = state.active @ values
        for target in (Fraction(1, 10), Fraction(1, 4), Fraction(1, 2)):
            with self.subTest(target=target):
                work = Work()
                result = advance(state, episode.physics, target, work)
                future = continuation_value(result, episode.physics, work)
                torch.testing.assert_close(result.value + result.discount_factor*future,
                                           reference, atol=2e-11, rtol=2e-11)
                torch.testing.assert_close(result.active.sum(1)+result.upper+refractory(result),
                                           state.active.sum(1), atol=2e-12, rtol=2e-12)

    def test_boundary_changes_real_flow_and_all_seven_derivatives(self):
        def outputs(theta):
            episode = task_physics(theta)
            result = advance(initial(episode.initial_probability[None]), episode.physics,
                             Fraction(1, 2), Work())
            return torch.cat((episode.boundary[None], result.hits,
                              result.discounted_hits, result.value,
                              continuation_value(result, episode.physics)))
        theta = torch.tensor(THETA, dtype=torch.float64, requires_grad=True)
        self.assertTrue(torch.autograd.gradcheck(outputs, (theta,), eps=1e-6,
                                                atol=2e-6, rtol=2e-5))
        changed = theta.detach().clone()
        changed[-1] += .02
        self.assertGreater(float((outputs(changed)[1]-outputs(theta)[1]).detach().abs()), 1e-3)

    def test_fixed_boundary_is_a_distinct_projected_policy(self):
        theta = torch.tensor(THETA, dtype=torch.float64)
        learned = task_physics(theta)
        fixed = task_physics(theta, boundary=learned.boundary-.03)
        self.assertFalse(torch.equal(learned.physics.reset, fixed.physics.reset))
        self.assertTrue(torch.equal(learned.physics.generator, fixed.physics.generator))
        self.assertGreater(float((learned.physics.reward-fixed.physics.reward).abs().max()), 0)

    def test_rejects_unsupported_law_or_delay_interface(self):
        theta = torch.tensor(THETA, dtype=torch.float64)
        with self.assertRaises(ValueError):
            task_physics(torch.cat((theta, theta.new_tensor([.2]))))
        with self.assertRaises(ValueError):
            task_physics(theta, delay=.2)
        with self.assertRaises(ValueError):
            task_physics(theta, nodes=2, extent=6.)
        bad = theta.clone()
        bad[0] = 2.
        with self.assertRaises(ValueError):
            task_physics(bad)


if __name__ == "__main__":
    unittest.main()
