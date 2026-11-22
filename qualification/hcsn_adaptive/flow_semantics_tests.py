"""Independent renewal, coupled-ODE, physical-clock and derivative fixtures."""

from dataclasses import replace
import math
import unittest

import numpy as np
import torch

from .batched_flow import BatchedFlow, FlowConfig
from .finite_control import first_passage_channels, frozen_channels
from .flow_semantics import FlowSemantics


class FlowSemanticsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.old_threads = torch.get_num_threads()
        torch.set_num_threads(1)

    @classmethod
    def tearDownClass(cls):
        torch.set_num_threads(cls.old_threads)

    def model(self, **kwargs):
        torch.manual_seed(17)
        return BatchedFlow(
            FlowConfig(
                input_size=1,
                content_size=1,
                bins=2,
                stages=1,
                upper_mode="reflecting",
                **kwargs,
            )
        )

    def test_two_state_first_passage_discount_and_repeat_count_are_distinct(self):
        a, b, rho, duration = 2.0, 3.0, 0.5, 2.0
        generator = torch.tensor([[-a, a], [b, -b]], dtype=torch.float64)
        result = frozen_channels(
            generator,
            generator.new_tensor([a, 0.0]),
            generator.new_zeros(2),
            discount=rho,
            duration=duration,
            event_destination=1,
        )
        first = [
            1 - math.exp(-a * duration),
            1 - (b * math.exp(-a * duration) - a * math.exp(-b * duration)) / (b - a),
        ]
        paid_a = a * -math.expm1(-(a + rho) * duration) / (a + rho)
        paid_b = (
            a
            * b
            / (b - a)
            * (
                -math.expm1(-(a + rho) * duration) / (a + rho)
                + math.expm1(-(b + rho) * duration) / (b + rho)
            )
        )
        torch.testing.assert_close(
            result["first_event_probability"],
            generator.new_tensor(first),
            atol=2e-13,
            rtol=0,
        )
        torch.testing.assert_close(
            result["discounted_first_event"],
            generator.new_tensor([paid_a, paid_b]),
            atol=2e-13,
            rtol=0,
        )
        repeated = a * b / (a + b) * duration + a * a / (a + b) ** 2 * -math.expm1(
            -(a + b) * duration
        )
        self.assertAlmostEqual(
            float(result["expected_event_count"][0]), repeated, places=12
        )
        self.assertGreater(repeated, 1.0)
        self.assertTrue(
            torch.equal(result["expected_event_count"], result["expected_events"])
        )
        rate = generator.new_tensor(a, requires_grad=True)
        learned = torch.stack((torch.stack((-rate, rate)), generator[1]))
        risk = first_passage_channels(
            learned,
            torch.stack((rate, rate * 0)),
            discount=rho,
            duration=duration,
            event_destination=1,
        )["first_event_probability"][0]
        derivative = torch.autograd.grad(risk, rate)[0]
        self.assertAlmostEqual(
            float(derivative), duration * math.exp(-a * duration), places=12
        )

    def test_starting_refractory_population_and_edge_cohort_are_counted_once(self):
        flow = self.model()
        state = flow.initial_state(1)
        density = torch.zeros_like(state.density)
        density[0, 0, 0], density[0, 0, 2] = 0.4, 0.6
        state = replace(state, density=density)
        inputs, duration, drift = flow.edges.new_zeros(1, 1), 0.8, -1.0
        _, _, diag = flow.step_physical(
            inputs,
            state,
            semantics=FlowSemantics("event_mask"),
            write_mask=[0],
            dt=duration,
            drift_override=drift,
            boundary_override=1.0,
        )
        # Independently integrate an exponential refractory release followed by
        # the existing killed-spatial first hit, without a reset/refractory G.
        points, weights = np.polynomial.legendre.leggauss(40)
        release_times = flow.edges.new_tensor((points + 1) * duration / 2)
        _, _, spatial = flow._generator(flow.edges.new_tensor([drift]))
        active_hit = (
            torch.matrix_exp(spatial * (duration - release_times)[:, None, None])[
                :, :2, 2
            ]
            @ flow.reset
        )
        rate = 1 / flow.config.refractory
        released_risk = (
            (
                flow.edges.new_tensor(weights)
                * rate
                * torch.exp(-rate * release_times)
                * active_hit
            ).sum()
            * duration
            / 2
        )
        observed = diag["observables"]
        torch.testing.assert_close(
            observed.first_event_probability[0],
            0.4 + 0.6 * released_risk,
            atol=2e-12,
            rtol=0,
        )
        self.assertGreater(float(observed.first_event_probability[0]), 0.4)
        self.assertLessEqual(
            float(observed.discounted_first_event[0]),
            float(observed.first_event_probability[0]),
        )
        density[0, 0, 0], density[0, 0, 2] = 1.0, 0.0
        _, _, edge = flow.step_physical(
            inputs,
            replace(state, density=density),
            semantics=FlowSemantics("event_mask"),
            write_mask=[0],
            dt=2.0,
            drift_override=-2.0,
            boundary_override=1.0,
        )
        self.assertEqual(float(edge["observables"].first_event_probability[0]), 1.0)
        self.assertEqual(float(edge["observables"].discounted_first_event[0]), 1.0)
        self.assertGreater(float(edge["observables"].expected_event_count[0]), 1.5)

    def test_heterogeneous_batch_cannot_hide_an_invalid_marked_edge(self):
        # The second sample must not relax the first sample's physical domain.
        generator = torch.tensor(
            [[[-1.0, 1.0], [0.0, 0.0]], [[-1e16, 1e16], [0.0, 0.0]]],
            dtype=torch.float64,
        )
        rates = generator.new_tensor([[2.0, 0.0], [1e16, 0.0]])
        with self.assertRaises(ValueError):
            first_passage_channels(
                generator, rates, discount=0.5, duration=1.0, event_destination=1
            )

    def test_continuous_write_matches_independent_coupled_ode(self):
        flow, rate, duration = self.model(), 1.7, 0.23
        inputs = flow.edges.new_tensor([[0.4]])
        state = flow.initial_state(1)
        state = replace(
            state,
            density=torch.cat((state.density[:, :1], 0.2 * state.density[:, :1]), 1),
        )
        _, updated, diag = flow.step_physical(
            inputs,
            state,
            semantics=FlowSemantics("continuous_write", rate),
            dt=duration,
            drift_override=-0.3,
        )
        g, event, _ = flow._generator(flow.edges.new_tensor([-0.3]))
        g, event, n = g[0], event[0], g.shape[-1]
        active = g.new_tensor([1.0, 1.0, 0.0, 0.0])
        mark = flow.writer(inputs).tanh()[0, 0]
        # Larger joint (p,q) ODE with explicit reward coordinates, independent
        # of the reduced residual solution used by the execution layer.
        block = g.new_zeros(2 * n + 3, 2 * n + 3)
        block[:n, :n], block[:n, n : 2 * n] = g, rate * mark * torch.diag(active)
        block[n : 2 * n, n : 2 * n] = g - rate * torch.diag(active)
        block[:n, 2 * n], block[n : 2 * n, 2 * n + 1], block[:n, 2 * n + 2] = (
            event,
            event,
            active,
        )
        initial = torch.cat((state.density.reshape(-1), g.new_zeros(3)))
        independent = initial @ torch.matrix_exp(duration * block)
        torch.testing.assert_close(
            updated.density.reshape(-1), independent[: 2 * n], atol=2e-13, rtol=0
        )
        actual = diag["observables"]
        torch.testing.assert_close(
            torch.cat(
                (
                    actual.expected_event_count,
                    actual.marked_event_count.reshape(-1),
                    actual.occupation_integral,
                )
            ),
            independent[2 * n :],
            atol=2e-13,
            rtol=0,
        )
        self.assertLess(float(diag["content_balance_error"].abs().max()), 2e-13)

    def test_physical_subdivision_preserves_state_count_and_occupation(self):
        flow, inputs = self.model(), torch.tensor([[0.4]], dtype=torch.float64)
        for semantics in (
            FlowSemantics("event_mask"),
            FlowSemantics("continuous_write", 2.3),
        ):
            mask = [1] if semantics.write_law == "event_mask" else None
            _, direct, diag = flow.step_physical(
                inputs,
                semantics=semantics,
                dt=0.2,
                write_mask=mask,
                boundary_override=0.07,
                drift_override=-0.3,
            )
            state, totals = None, inputs.new_zeros(3)
            for step in range(4):
                mask = [int(step == 0)] if semantics.write_law == "event_mask" else None
                _, state, piece = flow.step_physical(
                    inputs,
                    state,
                    semantics=semantics,
                    dt=0.05,
                    write_mask=mask,
                    boundary_override=0.07,
                    drift_override=-0.3,
                )
                obs = piece["observables"]
                totals = totals + torch.cat(
                    (
                        obs.expected_event_count,
                        obs.marked_event_count.reshape(-1),
                        obs.occupation_integral,
                    )
                )
            obs = diag["observables"]
            torch.testing.assert_close(
                state.density, direct.density, atol=2e-12, rtol=0
            )
            torch.testing.assert_close(
                totals,
                torch.cat(
                    (
                        obs.expected_event_count,
                        obs.marked_event_count.reshape(-1),
                        obs.occupation_integral,
                    )
                ),
                atol=2e-12,
                rtol=0,
            )
            self.assertEqual(state.time_micros, direct.time_micros)

    def test_boundary_drift_write_reward_gradients_and_snapshot_continuation(self):
        flow = self.model()
        controls = flow.edges.new_tensor([-0.23, 0.071, 0.09, 0.4], requires_grad=True)
        semantics = FlowSemantics("continuous_write", 1.7)

        def loss(z):
            features, state, diag = flow.step_physical(
                z[3:].reshape(1, 1),
                semantics=semantics,
                dt=0.17,
                drift_override=z[0],
                boundary_override=z[1],
                reward_offset=z[2],
            )
            return (
                features.square().sum()
                + diag["observables"].discounted_first_event.sum()
                + state.density[:, 1:].square().sum()
            )

        derivative = torch.autograd.grad(loss(controls), controls)[0]
        differences = []
        for i in range(4):
            offset = torch.zeros_like(controls)
            offset[i] = 1e-5
            differences.append(
                (loss(controls.detach() + offset) - loss(controls.detach() - offset))
                / 2e-5
            )
        torch.testing.assert_close(
            derivative, torch.stack(differences), atol=3e-8, rtol=3e-5
        )
        self.assertGreater(float(derivative.abs().min()), 1e-6)
        inputs = controls.detach()[3:].reshape(1, 1)
        _, state, _ = flow.step_physical(inputs, semantics=semantics)
        restored = type(state).from_record(state.to_record())
        a, final, _ = flow.step_physical(inputs, state, semantics=semantics)
        b, resumed, _ = flow.step_physical(inputs, restored, semantics=semantics)
        self.assertTrue(torch.equal(a, b))
        self.assertTrue(torch.equal(final.density, resumed.density))
        self.assertFalse(restored.density.requires_grad)

    def test_declared_write_law_and_batched_mixed_precision_are_enforced(self):
        for precision in ("float64", "native"):
            flow = self.model(transport_precision=precision).to(dtype=torch.float32)
            inputs = torch.tensor([[0.4], [0.4]], dtype=torch.float32)
            out, state, diag = flow.step_physical(
                inputs, semantics=FlowSemantics("event_mask"), write_mask=[1, 0]
            )
            self.assertEqual(out.dtype, torch.float32)
            self.assertEqual(
                state.density.dtype,
                torch.float64 if precision == "float64" else torch.float32,
            )
            self.assertEqual(float(state.density[1, 1].abs().sum()), 0.0)
            self.assertGreater(float(state.density[0, 1].abs().sum()), 0.0)
            self.assertLess(float(diag["mass_error"].abs().max()), 3e-5)
            out.square().sum().backward()
            self.assertTrue(
                all(
                    p.grad is not None and bool(torch.isfinite(p.grad).all())
                    for p in flow.parameters()
                )
            )
        for law in ("continuous_write", "legacy_observation"):
            with self.assertRaises(ValueError):
                FlowSemantics(law)
        with self.assertRaises(ValueError):
            flow.step_physical(inputs, semantics=FlowSemantics("event_mask"))
        with self.assertRaises(ValueError):
            flow.step_physical(
                inputs,
                semantics=FlowSemantics("continuous_write", 2.0),
                write_mask=[1, 0],
            )


if __name__ == "__main__":
    unittest.main()
