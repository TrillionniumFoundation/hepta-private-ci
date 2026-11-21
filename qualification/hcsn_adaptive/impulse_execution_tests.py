"""Independent new control-execution fixtures; no training or holdout reuse."""

import itertools
import math
import unittest

import torch

from qualification.hcsn_adaptive.batched_flow import BatchedFlow, FlowConfig, FlowState
from qualification.hcsn_adaptive.finite_control import evaluate_impulse_policy, frozen_channels
from qualification.hcsn_adaptive.impulse_execution import compile_impulse_policy


class ImpulseExecutionTests(unittest.TestCase):
    def test_executed_return_matches_independent_qvi_rows_for_every_policy(self):
        g = torch.tensor([[-2., 0., 0., 2.], [1., -1., 0., 0.],
                          [0., 1., -1., 0.], [0., 0., 3., -3.]], dtype=torch.float64)
        event, reward = g.new_tensor([2., 0., 0., 0.]), g.new_tensor([-2.6, .2, 1., 0.])
        payoff = g.new_tensor([-.25, -.4, -.1])
        density = g.new_tensor([[.2, .2, .3, .3], [.1, -.1, .15, -.2]])
        for bits in itertools.product((False, True), repeat=3):
            policy = torch.tensor(bits, dtype=torch.bool)
            kwargs = dict(discount=.5, active_count=3, reset_entry=3, policy=policy)
            expected = evaluate_impulse_policy(g, reward, payoff, **kwargs)
            kernel = compile_impulse_policy(g, event, reward, payoff, **kwargs)
            torch.testing.assert_close(kernel.value(), expected, rtol=0, atol=1e-12)
            whole = kernel.advance(density, .7)
            left = kernel.advance(density, .3)
            right = kernel.advance(left.density, .4)
            torch.testing.assert_close(whole.density, right.density, rtol=0, atol=2e-12)
            for field in ("natural_events", "intervention_events"):
                torch.testing.assert_close(getattr(whole, field), getattr(left, field) + getattr(right, field),
                                           rtol=0, atol=2e-12)
            torch.testing.assert_close(whole.discounted_reward,
                                       left.discounted_reward + math.exp(-.5 * .3) * right.discounted_reward,
                                       rtol=0, atol=2e-12)
            # Bellman decomposition checks real executed rewards plus continuation.
            torch.testing.assert_close(density @ expected,
                                       whole.discounted_reward + math.exp(-.5 * .7) * (whole.density @ expected),
                                       rtol=0, atol=2e-12)

    def test_marked_self_events_survive_elimination_and_are_not_multiple_first_hits(self):
        # Every release immediately causes a new intervention. The phase stays
        # unchanged, but interventions form a rate-3 Poisson process.
        g = torch.tensor([[-2., 2.], [3., -3.]], dtype=torch.float64)
        kernel = compile_impulse_policy(g, g.new_tensor([2., 0.]), g.new_zeros(2), g.new_tensor([-1.]),
                                        discount=.5, active_count=1, reset_entry=1,
                                        policy=torch.tensor([True]))
        start = g.new_tensor([[0., 1.], [0., -.4]])
        result = kernel.advance(start, .7)
        torch.testing.assert_close(result.density, start, rtol=0, atol=1e-12)
        self.assertAlmostEqual(float(result.natural_events[0]), 0., places=12)
        self.assertAlmostEqual(float(result.intervention_events[0]), 2.1, places=12)
        self.assertAlmostEqual(float(result.first_event[0]), 1 - math.exp(-2.1), places=12)
        self.assertAlmostEqual(float(result.discounted_reward[0]), -6 * (1 - math.exp(-.35)), places=12)
        initial_hit = kernel.advance(g.new_tensor([[1., 0.]]), .7)
        self.assertAlmostEqual(float(initial_hit.intervention_events[0]), 3.1, places=12)
        self.assertAlmostEqual(float(initial_hit.first_event[0]), 1., places=12)

    def test_real_flow_execution_and_cold_state_resume(self):
        flow = BatchedFlow(FlowConfig(input_size=1, bins=3, stages=2, upper_mode="reflecting"))
        initial = flow.initial_state(1)
        reward, payoff = flow.edges.new_tensor([-.8, .1, .7, 0., 0., 0.]), flow.edges.new_full((3,), -.05)
        solution = flow.task_control_reference(reward, payoff, drift=-.2)
        args = (solution.reset_policy, reward, payoff)
        whole, receipt = flow.execute_task_policy(initial, *args, drift=-.2, dt=.3)
        prefix, first = flow.execute_task_policy(initial, *args, drift=-.2, dt=.1)
        recovered = FlowState.from_record(prefix.to_record())
        resumed, second = flow.execute_task_policy(recovered, *args, drift=-.2, dt=.2)
        torch.testing.assert_close(whole.density, resumed.density, rtol=0, atol=2e-12)
        self.assertEqual(whole.time_micros, resumed.time_micros)
        torch.testing.assert_close(receipt.discounted_reward,
                                   first.discounted_reward + math.exp(-flow.config.discount * .1) * second.discounted_reward,
                                   rtol=0, atol=2e-12)
        # With no intervention the executor agrees with original same-G channels.
        never = torch.zeros(3, dtype=torch.bool)
        untouched, baseline = flow.execute_task_policy(initial, never, reward, payoff, drift=-.2, dt=.3)
        g, e, _ = flow._generator(flow.edges.new_tensor([-.2]))
        channels = frozen_channels(g[0], e[0], reward - flow.config.spike_cost * e[0],
                                   discount=flow.config.discount, duration=.3, event_destination=3)
        torch.testing.assert_close(untouched.density[0], initial.density[0] @ channels["transition"], rtol=0, atol=1e-12)
        torch.testing.assert_close(baseline.natural_events, initial.density[0] @ channels["expected_events"], rtol=0, atol=1e-12)


if __name__ == "__main__":
    unittest.main()
