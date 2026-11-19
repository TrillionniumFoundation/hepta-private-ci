"""New distribution continuation gates, independent of the V4 point tests."""

import io
import math
import unittest

import numpy as np
from scipy.integrate import quad, quad_vec
import torch

from qualification.hcsn_regenerative import process as scalar
from qualification.hcsn_regenerative.distribution import (
    DistributionGrid, DistributionState, condition_on_likelihood, physical_time,
)
from qualification.hcsn_regenerative.distribution_operator import DistributionOperator
from qualification.hcsn_regenerative.tensor import TensorDiffusion, TensorReset


def grid():
    return DistributionGrid(tuple(np.linspace(0., 1.6, 17)), (0., .0275, .055, .0825, .11), 1.)


def oracle_point(g, x, t):
    p = scalar.KilledDiffusion(-.1, .3, .15)
    transition = scalar.regenerative_transition(p, scalar.ResetRule(.25, .11), x, t,
                                               g.active_edges, refractory_edges=g.refractory_edges)
    occupation = t*quad(lambda u: 2*u*math.exp(-.15*t*u*u)*p.survival(x, t*u*u),
                        0., 1., epsabs=2e-12, epsrel=2e-12)[0]
    return np.array([*transition.active_bins, transition.upper_tail, *transition.refractory_bins,
                     p.hit_probability(x, t), p.discounted_hit(x, t), occupation])


class DistributionContinuationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        torch.set_num_threads(1)
        cls.grid = grid()
        cls.reset = TensorReset(.25, .11)
        cls.operators = {}
        for device in (("cpu", "cuda") if torch.cuda.is_available() else ("cpu",)):
            for dtype in (torch.float32, torch.float64):
                for dt in (.04, .07):
                    cls.operators[device, dtype, dt] = DistributionOperator(
                        TensorDiffusion(-.1, .3, .15), cls.reset, cls.grid, dt, dtype=dtype, device=device)

    def test_independent_uniform_and_tail_integrals(self):
        operator = self.operators["cpu", torch.float64, .04]
        combined = torch.cat((operator.matrix, operator.reward_matrix), dim=-1).numpy()
        lo, hi = self.grid.active_edges[2:4]
        expected, _ = quad_vec(lambda x: oracle_point(self.grid, x, .04)/(hi-lo), lo, hi,
                               epsabs=1e-10, epsrel=1e-10)
        np.testing.assert_allclose(combined[2], expected, atol=2e-7, rtol=2e-7)
        endpoint, rate = self.grid.active_edges[-1], self.grid.tail_rate
        expected, _ = quad_vec(lambda u: 2*u*oracle_point(self.grid, endpoint-math.log1p(-u*u)/rate, .04),
                               0., 1., epsabs=1e-10, epsrel=1e-10)
        np.testing.assert_allclose(combined[self.grid.active_size], expected, atol=2e-7, rtol=2e-7)

    def test_tail_returns_and_mass_is_not_renormalized(self):
        for (device, dtype, dt), operator in self.operators.items():
            mass = torch.zeros(self.grid.size, dtype=dtype, device=device)
            mass[self.grid.active_size] = 1.
            flow = operator.advance(DistributionState(self.grid, mass))
            self.assertGreater(float(flow.state.active.sum().cpu()), 0.)
            self.assertLess(float(flow.state.tail.cpu()), 1.)
            self.assertLess(abs(float(flow.mass_residual.cpu())), 3e-6)
            self.assertEqual(flow.spatial_truncation_mass, 0.)
            self.assertEqual(flow.renewal_truncation_mass, 0.)
            self.assertGreater(float(flow.tail_projection_distance_upper.cpu()), 0.)

    def test_actual_distribution_changes_the_next_state_and_gradient(self):
        for (device, dtype, dt), operator in self.operators.items():
            mass = torch.full((3, self.grid.size), 1/self.grid.size, dtype=dtype, device=device, requires_grad=True)
            state = DistributionState(self.grid, mass)
            flow = operator.advance(state)
            weights = torch.linspace(-.4, .7, self.grid.size, dtype=dtype, device=device)
            derivative = torch.autograd.grad((flow.state.mass*weights).sum(), mass)[0]
            expected = (operator.matrix@weights).expand_as(mass)
            torch.testing.assert_close(derivative, expected, atol=1e-6, rtol=2e-6)
            alternate = torch.zeros_like(mass.detach()); alternate[:, -1] = 1.
            changed = operator.advance(DistributionState(self.grid, alternate))
            self.assertGreater(float((changed.state.mass-flow.state.mass).abs().sum().detach().cpu()), .1)

    def test_exact_physical_phase_atoms_and_boundary_atoms(self):
        for device, dtype in sorted({(d, t) for d, t, _ in self.operators}, key=str):
            first = self.operators[device, dtype, .04]
            second = self.operators[device, dtype, .07]
            state = DistributionState.phase_point(self.grid, .11, dtype=dtype, device=device)
            after = first.advance(state).state
            self.assertEqual(after.refractory_atoms, (physical_time(.07),))
            released = second.advance(after).state
            self.assertEqual(released.active_atoms, (.25,))
            self.assertEqual(released.refractory_atoms, ())
            self.assertEqual(released.elapsed, physical_time(.11))
            self.assertEqual(float(released.active_atom_mass.sum().cpu()), 1.)
            boundary = DistributionState.point(self.grid, 0., dtype=dtype, device=device)
            hit = first.advance(boundary)
            self.assertEqual(float(hit.expected_hits.cpu()), 1.)
            self.assertEqual(hit.state.refractory_atoms, (physical_time(.07),))

    def test_checkpoint_roundtrip_contains_the_real_measure_and_clock(self):
        for (device, dtype, dt), operator in self.operators.items():
            mass = torch.zeros(self.grid.size, dtype=dtype, device=device)
            mass[3], mass[self.grid.active_size], mass[-2] = .25, .15, .2
            state = DistributionState(self.grid, mass, (.35,), mass.new_tensor([.1]),
                                      (.09,), mass.new_tensor([.3]), physical_time(.123))
            first = operator.advance(state).state
            buffer = io.BytesIO(); torch.save(first.state_dict(), buffer); buffer.seek(0)
            restored = DistributionState.from_state_dict(self.grid, torch.load(buffer, weights_only=True), device=device)
            actual, expected = operator.advance(restored).state, operator.advance(first).state
            self.assertTrue(torch.equal(actual.packed, expected.packed))
            self.assertEqual(actual.elapsed, expected.elapsed)
            self.assertEqual(actual.refractory_atoms, expected.refractory_atoms)
            self.assertTrue(torch.equal(actual.projection_phase_time_sum, expected.projection_phase_time_sum))

    def test_atom_coefficient_gradients_survive_release_without_location_gradients(self):
        for device, dtype in sorted({(d, t) for d, t, _ in self.operators}, key=str):
            mass = torch.zeros((2, self.grid.size), dtype=dtype, device=device)
            weights = torch.ones((2, 1), dtype=dtype, device=device, requires_grad=True)
            state = DistributionState(self.grid, mass, refractory_atoms=(.11,), refractory_atom_mass=weights)
            next_state = self.operators[device, dtype, .07].advance(
                self.operators[device, dtype, .04].advance(state).state).state
            derivative = torch.autograd.grad(next_state.active_atom_mass.sum(), weights)[0]
            self.assertTrue(torch.equal(derivative, torch.ones_like(weights)))
            self.assertEqual(next_state.active_atoms, (.25,))

    def test_observation_conditioning_has_explicit_evidence_and_gradients(self):
        operator = self.operators["cpu", torch.float64, .04]
        state = operator.advance(DistributionState.point(self.grid, .35, dtype=torch.float64)).state
        logits = torch.linspace(-.3, .5, self.grid.size, dtype=torch.float64, requires_grad=True)
        likelihood = logits.exp()
        posterior = condition_on_likelihood(state, likelihood, observation_id="fixed-observation-7")
        self.assertAlmostEqual(float(posterior.evidence.detach()), float((state.mass*likelihood).sum().detach()), places=13)
        future = operator.advance(posterior.state)
        derivative = torch.autograd.grad(future.state.tail+future.state.refractory.sum(), logits)[0]
        self.assertTrue(bool(torch.isfinite(derivative).all()))
        self.assertGreater(float(derivative.abs().sum()), 0.)
        self.assertEqual(posterior.state.elapsed, state.elapsed)

    def test_generator_dtype_grid_and_mass_contracts_reject(self):
        operator = self.operators["cpu", torch.float64, .04]
        state = operator.advance(DistributionState.point(self.grid, .35, dtype=torch.float64)).state
        changed = DistributionOperator(TensorDiffusion(-.2, .3, .15), self.reset, self.grid, .04, dtype=torch.float64)
        with self.assertRaises(ValueError):
            changed.advance(state)
        with self.assertRaises(ValueError):
            operator.advance(DistributionState.point(self.grid, .35, dtype=torch.float32))
        with self.assertRaises(ValueError):
            DistributionOperator(TensorDiffusion(-.1, .3, .15), self.reset, self.grid, .12)
        with self.assertRaises(ValueError):
            DistributionOperator(TensorDiffusion(torch.tensor(-.1, requires_grad=True), .3, .15), self.reset, self.grid, .04)
        with self.assertRaises(FloatingPointError):
            DistributionState(self.grid, torch.zeros(self.grid.size, dtype=torch.float64))
        with self.assertRaises(ValueError):
            DistributionGrid(torch.tensor([0., .5, 1.]), (0., .11))
        with self.assertRaises(ValueError):
            DistributionOperator(TensorDiffusion(-.1, .3, .15), self.reset, self.grid, .04,
                                 quadrature_order=torch.tensor(32))
        with self.assertRaises(AttributeError):
            operator.dt = physical_time(.07)


if __name__ == "__main__":
    unittest.main()
