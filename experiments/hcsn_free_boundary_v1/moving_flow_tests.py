"""Physical remap, event accounting, phase continuity and boundary derivatives."""

import unittest

import torch

from .moving_flow import (Grid, exact_segment_monte_carlo, generator, gradient_audit,
                         initial_state, moments, projected_policy_values, propagate,
                         remap, rollout)


class MovingFlowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        torch.set_num_threads(1)

    def test_identity_remap_preserves_every_state_component(self):
        old = generator(0.2, 0.7, 1.1, -0.2, 0.3, Grid(35, -3, 7))
        new = generator(-0.3, 0.9, 1.1, -0.2, 0.3, Grid(35, -3, 7))
        state = propagate(old, initial_state(old, 0.1), 1.4)
        result, receipt = remap(old, new, state)
        torch.testing.assert_close(result, state, rtol=0, atol=2e-15)
        self.assertEqual(float(receipt["immediate_events"]), 0)
        self.assertEqual(float(receipt["immediate_reward"]), 0)

    def test_partial_cell_shrink_fires_physical_density_and_affine_reward(self):
        # Old cells [0,1),[1,2),[2,3),[3,4); half of active mass lies in [1.5,3).
        old = generator(0, 0.5, 4, 0.6, 0.4, Grid(4, 0, 4))
        new = generator(0, 0.5, 1.5, 0.6, 0.4, Grid(4, 0, 4))
        state = torch.tensor([0.1, 0.2, 0.4, 0.0, 0.05, 0.1, 0.05, 0.1, 2.0, 1.7],
                             dtype=torch.float64)
        result, receipt = remap(old, new, state)
        self.assertAlmostEqual(float(receipt["immediate_events"]), 0.5, places=14)
        # Integral x: .2*.5*1.75 + .4*2.5 = 1.175; reward x-.4 is .975.
        self.assertAlmostEqual(float(receipt["removed_active_first_moment"]), 1.175, places=14)
        self.assertAlmostEqual(float(receipt["immediate_reward"]), 0.975, places=14)
        self.assertAlmostEqual(float(result[-2]), 2.5, places=14)
        self.assertAlmostEqual(float(result[-1]), 2.675, places=14)
        torch.testing.assert_close(result[5:8], state[5:8], rtol=0, atol=0)
        self.assertAlmostEqual(float(result[4]), float(state[4])+0.5, places=14)
        self.assertAlmostEqual(float(result[:-2].sum()), 1, places=14)
        self.assertGreaterEqual(float(result[:-2].min()), 0)
        torch.testing.assert_close(receipt["transfer_column_mass"], torch.ones(4, dtype=state.dtype),
                                   rtol=0, atol=1e-14)
        self.assertLessEqual(abs(float(receipt["projection_mean_error"])),
                             float(receipt["projection_mean_error_bound"]) + 1e-14)

    def test_expansion_does_not_create_events_or_mass_and_refractory_is_preserved(self):
        old = generator(0.3, 0.7, 0.8, -0.2, 0.6, Grid(31, -3, 9))
        new = generator(0.1, 0.9, 1.3, -0.2, 0.6, Grid(47, -3, 9))
        state = propagate(old, initial_state(old, 0.1), 1)
        result, receipt = remap(old, new, state)
        self.assertEqual(float(receipt["immediate_events"]), 0)
        self.assertEqual(float(receipt["immediate_reward"]), 0)
        torch.testing.assert_close(result[47:56], state[31:40], rtol=0, atol=0)
        self.assertAlmostEqual(float(result[:-2].sum()), float(state[:-2].sum()), places=13)
        self.assertGreaterEqual(float(result[:-2].min()), 0)
        torch.testing.assert_close(moments(new, result)["refractory_remaining"],
                                   moments(old, state)["refractory_remaining"], rtol=0, atol=0)
        self.assertLessEqual(abs(float(receipt["projection_mean_error"])),
                             float(receipt["projection_mean_error_bound"]) + 1e-14)

    def test_zero_delay_unit_reward_equals_count_through_flow_and_jumps(self):
        segments = [dict(mu=0.3, sigma=0.8, boundary=1.0, duration=0.8),
                    dict(mu=-0.2, sigma=0.7, boundary=0.4, duration=0.7),
                    dict(mu=0.4, sigma=0.9, boundary=1.1, duration=1)]
        flow, state, records = rollout(segments, -0.2, 0, 0.1, Grid(50, -4, 8),
                                       reward_slope=0, reward_intercept=1)
        self.assertAlmostEqual(float(state[-2]), float(state[-1]), places=12)
        self.assertGreater(float(state[-2]), 1)
        self.assertAlmostEqual(float(state[:-2].sum()), 1, places=11)
        self.assertGreater(float(records[1]["jump"]["immediate_events"]), 0.01)
        self.assertEqual(float(records[2]["jump"]["immediate_events"]), 0)
        self.assertEqual(flow["stages"], 0)

    def test_segment_subdivision_is_exact_for_same_generator(self):
        segments = [dict(mu=-0.2, sigma=0.75, boundary=1.0, duration=0.6),
                    dict(mu=0.3, sigma=0.65, boundary=0.5, duration=0.8)]
        _, once, _ = rollout(segments, -0.2, 0.3, 0.1, Grid(40, -4, 8))
        for partitions in (4, 16, 64):
            _, split, _ = rollout(segments, -0.2, 0.3, 0.1, Grid(40, -4, 8),
                                  partitions=partitions)
            torch.testing.assert_close(split, once, rtol=1e-10, atol=1e-12)

    def test_interior_boundary_gradient_including_jump_atom(self):
        result = gradient_audit()
        for name in ("objective", "immediate_count"):
            self.assertLess(result[name]["relative_error"], 2e-5, result[name])
            self.assertGreater(abs(result[name]["autograd"]), 1e-5)

    def test_phase_value_projection_obeys_local_policy_bellman_equation(self):
        flow = generator(0.2, 0.7, 1, -0.2, 0.4, Grid(40, -3, 8))
        state = propagate(flow, initial_state(flow, 0.1), 1.3)
        values = projected_policy_values(flow, state)
        self.assertLess(float(values["bellman_residual"]), 1e-11)
        self.assertAlmostEqual(float(values["eligible_mass"] + moments(flow, state)["refractory_mass"]),
                               1, places=11)
        self.assertEqual(len(values["phase_J"]), 8)
        torch.testing.assert_close(values["eligible_continuation_gap"],
                                   values["eligible_continuation"] - values["eligible_intervention"],
                                   rtol=1e-12, atol=1e-14)

    def test_exact_event_sampler_carries_remaining_refractory_across_boundary_jump(self):
        # Initial firing at t0; initial tau=.5 is still waiting during lowered-b segment.
        segments = [dict(mu=0, sigma=0, boundary=1, duration=0.2),
                    dict(mu=0, sigma=0, boundary=0.5, duration=0.2)]
        result = exact_segment_monte_carlo(segments, -0.2, 0.5, 1.1,
                                          samples=100, refractory_stages=None)
        final = result["records"][-1]["after_segment"]
        self.assertEqual(final["events"]["mean"], 1)
        self.assertAlmostEqual(final["refractory_remaining"]["mean"], 0.1, places=14)
        self.assertEqual(result["records"][1]["immediate_events"]["mean"], 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
