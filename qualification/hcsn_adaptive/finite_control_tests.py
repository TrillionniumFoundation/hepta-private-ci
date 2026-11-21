"""New mathematical/integration fixtures; no sealed data or task benchmarks.

Run: python -m unittest qualification.hcsn_adaptive.finite_control_tests
"""

import itertools
import math
import unittest

import torch

from qualification.hcsn_adaptive.batched_flow import BatchedFlow, FlowConfig
from qualification.hcsn_adaptive.finite_control import (
    DelayLaw, continuation_value, evaluate_impulse_policy, frozen_channels, solve_impulse_control,
)


class FiniteControlTests(unittest.TestCase):
    def test_first_event_count_and_distinct_delay_continuations(self):
        # Two-state renewal process: active -> waiting -> active.
        g = torch.tensor([[-2., 2.], [3., -3.]], dtype=torch.float64)
        event, reward = g.new_tensor([2., 0.]), g.new_tensor([1., 0.])
        duration, discount = 2., .5
        channels = frozen_channels(g, event, reward, discount=discount, duration=duration,
                                   event_destination=1)
        expected_count = 6 / 5 * duration + 4 / 25 * (1 - math.exp(-5 * duration))
        self.assertAlmostEqual(float(channels["first_event_probability"][0]), 1 - math.exp(-2 * duration), places=12)
        self.assertAlmostEqual(float(channels["expected_events"][0]), expected_count, places=12)
        self.assertGreater(float(channels["expected_events"][0]), 1.)
        value = channels["value"]
        erlang = DelayLaw("erlang", 1 / 3, 1).discount_factor(discount)
        deterministic = DelayLaw("deterministic", 1 / 3).discount_factor(discount)
        self.assertAlmostEqual(float(value[1]), erlang * float(value[0]), places=13)
        self.assertGreater(abs(float(value[1]) - deterministic * float(value[0])), .001)
        with self.assertRaises(ValueError):
            DelayLaw("deterministic", .2, 2)
        with self.assertRaises(ValueError):
            frozen_channels(g, g.new_tensor([4., 0.]), reward, discount=.5, duration=.1, event_destination=1)
        rate = g.new_tensor(2., requires_grad=True)
        variable_g = torch.stack((torch.stack((-rate, rate)), g[1]))
        learned_value = continuation_value(variable_g, reward, discount)
        learned_value[0].backward()
        exact_derivative = -(discount + 3) / (discount * (discount + 2 + 3) ** 2)
        self.assertAlmostEqual(float(rate.grad), exact_derivative, places=13)

    def test_qvi_against_independent_all_policy_value_iteration(self):
        # Degradation task: operating states low/mid/good, then a waiting state.
        # Rewards are externally specified operating utility, not teacher labels.
        g = torch.tensor([[-2., 0., 0., 2.], [1., -1., 0., 0.],
                          [0., 1., -1., 0.], [0., 0., 3., -3.]], dtype=torch.float64)
        payoff, discount = g.new_full((3,), -.25), .5
        policies = [torch.tensor(bits, dtype=torch.bool) for bits in itertools.product((False, True), repeat=3)]
        selected = []
        for reward in (g.new_tensor([-2.6, .2, 1., 0.]), g.new_tensor([1., 1., 1., 0.])):
            result = solve_impulse_control(g, reward, payoff, discount=discount, active_count=3, reset_entry=3)
            # Independent fixed-policy iteration: no production solve/evaluate calls.
            all_values = []
            for policy in policies:
                v = torch.zeros(4, dtype=torch.float64)
                for _ in range(4000):
                    following = (reward + (3 * torch.eye(4, dtype=torch.float64) + g) @ v) / 3.5
                    following[:3] = torch.where(policy, payoff + v[3], following[:3])
                    if float((following - v).abs().max()) < 1e-12:
                        v = following
                        break
                    v = following
                else:
                    self.fail("independent policy value iteration failed to converge")
                all_values.append(v)
            optimum = torch.stack(all_values).amax(0)
            torch.testing.assert_close(result.value, optimum, rtol=0, atol=2e-11)
            self.assertLessEqual(result.bellman_residual, 1e-10)
            # Fixed and simple-gate baselines use the same complete task return.
            for policy in (policies[0], torch.tensor([True, False, False])):
                baseline = evaluate_impulse_policy(g, reward, payoff, discount=discount,
                                                    active_count=3, reset_entry=3, policy=policy)
                self.assertTrue(bool((result.value >= baseline - 2e-11).all()))
            selected.append(result.reset_policy.tolist())
        self.assertEqual(selected, [[True, True, False], [False, False, False]])

    def test_real_flow_entry_uses_same_generator_and_complete_reset(self):
        flow = BatchedFlow(FlowConfig(input_size=1, bins=3, stages=2, upper_mode="reflecting"))
        work = flow.edges
        g, event, spatial = flow._generator(work.new_tensor([-.2]))
        n, duration = g.shape[-1], .17
        operating = work.new_tensor([-.8, .1, .7, 0., 0., 0.])
        payoff = work.new_full((3,), -.05)
        result = flow.task_control_reference(operating, payoff, drift=-.2)
        adjusted = operating - flow.config.spike_cost * event[0]
        channels = frozen_channels(g[0], event[0], adjusted, discount=flow.config.discount,
                                   duration=duration, event_destination=3)
        old_first = torch.matrix_exp(duration * spatial[0])[:3, 3]
        torch.testing.assert_close(channels["first_event_probability"][:3], old_first, rtol=0, atol=1e-12)
        # The phase continuation is not a terminal zero or an absorbing default.
        factor = DelayLaw("erlang", flow.config.refractory, flow.config.stages).discount_factor(flow.config.discount)
        torch.testing.assert_close(result.value[3], factor * (flow.reset @ result.value[:3]), rtol=0, atol=1e-11)
        # Actual sequence flow still uses the shared differentiable value operator.
        inputs = work.new_full((1, 1), .3)
        features, state, diagnostics = flow.step(inputs, dt=duration, drift_override=-.2)
        running = torch.cat((flow.config.gain * flow.centers - flow.config.maintenance, work.new_zeros(n - 3)))
        frozen = continuation_value(g[0], running - flow.config.spike_cost * event[0], flow.config.discount)
        torch.testing.assert_close(features[0, -1], state.density[0, 0] @ frozen, rtol=0, atol=1e-12)
        features.sum().backward()
        self.assertTrue(bool(torch.isfinite(flow.writer.weight.grad).all()))
        self.assertGreater(float(flow.writer.weight.grad.abs().sum()), 0.)
        self.assertEqual(diagnostics["call_kind"], "frozen_finite_policy_continuation")


if __name__ == "__main__":
    unittest.main()
