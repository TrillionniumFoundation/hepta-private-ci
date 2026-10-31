"""Independent numerical checks for the registered round-7 dynamics contract."""

import math
import unittest

import numpy as np
from scipy.integrate import quad
from scipy.linalg import expm
from scipy.special import ndtr
import torch

try:
    from .dynamics import EventDynamics
except ImportError:
    from dynamics import EventDynamics


torch.set_num_threads(1)


class EventDynamicsTests(unittest.TestCase):
    def test_probability_mass_and_nonnegative_transitions(self) -> None:
        drives = torch.tensor([-4.0, -0.3, 0.0, 0.8, 4.0], dtype=torch.float64)
        for mode in EventDynamics.MODES:
            with self.subTest(mode=mode):
                cell = EventDynamics(mode)
                transition, rewards = cell.transition_matrix(drives)
                self.assertGreaterEqual(float(transition.min().detach()), -2e-13)
                torch.testing.assert_close(
                    transition.sum(-1), torch.ones_like(transition.sum(-1)), rtol=0.0, atol=2e-12
                )
                mass = cell.initial(len(drives))
                for _ in range(20):
                    mass, events = cell(mass, drives)
                    self.assertGreaterEqual(float(events.min().detach()), -2e-13)
                    self.assertLessEqual(float(events.sum(-1).max().detach()), 1.0 + 2e-11)
                torch.testing.assert_close(mass.sum(-1), torch.ones(len(drives), dtype=torch.float64), rtol=0.0, atol=4e-11)
                if mode == "continuous":
                    self.assertEqual(float(rewards.abs().sum()), 0.0)
                    self.assertEqual(float(mass[:, -2:].abs().sum().detach()), 0.0)

    def test_clocked_events_match_independent_ou_endpoint_law(self) -> None:
        cell = EventDynamics("clocked")
        drive = np.array([-0.8, 0.3, 1.2])
        dt = 0.7
        physical = {k: float(v.detach()) for k, v in cell.physical_parameters().items()}
        mean = drive * (-np.expm1(-physical["leak"] * dt)) / physical["leak"]
        variance = physical["diffusion"] ** 2 * (-np.expm1(-2.0 * physical["leak"] * dt)) / (2.0 * physical["leak"])
        expected = np.stack((ndtr((mean - physical["boundary"]) / np.sqrt(variance)), ndtr((-physical["boundary"] - mean) / np.sqrt(variance))), axis=-1)
        _, events = cell(cell.initial(3), torch.from_numpy(drive), dt)
        np.testing.assert_allclose(events.detach().numpy(), expected, rtol=2e-13, atol=2e-15)

    def test_ctmc_exponential_matches_independent_scipy_construction(self) -> None:
        cell = EventDynamics("first_passage", n_grid=11)
        physical = {k: float(v.detach()) for k, v in cell.physical_parameters().items()}
        n = cell.n_grid
        h = 2.0 * physical["boundary"] / (n + 1)
        x = -physical["boundary"] + h * np.arange(1, n + 1)
        generator = np.zeros((n + 2, n + 2))
        drive = 0.47
        for i in range(n):
            drift = drive - physical["leak"] * x[i]
            right = 0.5 * physical["diffusion"] ** 2 / h**2 + max(drift, 0.0) / h
            left = 0.5 * physical["diffusion"] ** 2 / h**2 + max(-drift, 0.0) / h
            generator[i, i] = -right - left
            generator[i, i + 1 if i + 1 < n else n] = right
            generator[i, i - 1 if i > 0 else n + 1] = left
        expected = expm(0.8 * generator)
        actual = torch.matrix_exp(0.8 * cell.absorbing_generator(torch.tensor([drive], dtype=torch.float64)))[0]
        np.testing.assert_allclose(actual.detach().numpy(), expected, rtol=2e-11, atol=2e-13)

    def test_first_passage_brownian_mesh_convergence(self) -> None:
        # Independent killed-Brownian survival expansion on (-b,b), x=0.
        errors = []
        for n_grid in (15, 31, 63):
            cell = EventDynamics("first_passage", n_grid=n_grid)
            with torch.no_grad():
                cell.raw_leak.fill_(-35.0)
            physical = {k: float(v.detach()) for k, v in cell.physical_parameters().items()}
            dt = 1.7
            k = np.arange(200, dtype=np.float64)
            survival = float(np.sum((4.0 / np.pi) * ((-1.0) ** k / (2.0 * k + 1.0)) * np.exp(-((2.0 * k + 1.0) ** 2 * np.pi**2 * physical["diffusion"] ** 2 * dt / (8.0 * physical["boundary"] ** 2)))))
            _, events = cell(cell.initial(1), torch.zeros(1), dt)
            total = float(events.sum().detach())
            errors.append(abs(total - (1.0 - survival)))
            self.assertAlmostEqual(float(events[0, 0].detach()), float(events[0, 1].detach()), places=12)
        self.assertLess(errors[1], errors[0])
        self.assertLess(errors[2], errors[1])
        self.assertLess(errors[-1], 3e-4)

    def test_refractory_release_has_no_same_tick_events(self) -> None:
        for mode in ("clocked", "first_passage"):
            cell = EventDynamics(mode)
            mass = torch.zeros_like(cell.initial(1))
            mass[0, cell.n_grid] = 1.0
            released, events = cell(mass, torch.tensor([20.0]))
            q = cell.physical_parameters()["recovery_probability"]
            reset_plus, _ = cell.reset_distributions()
            torch.testing.assert_close(events, torch.zeros_like(events), rtol=0.0, atol=0.0)
            torch.testing.assert_close(released[0, : cell.n_grid], q * reset_plus)
            torch.testing.assert_close(released[0, cell.n_grid], 1.0 - q)
            _, next_events = cell(released, torch.tensor([20.0]))
            self.assertGreater(float(next_events.sum().detach()), 0.5)

    def test_repeated_events_are_counts_not_a_single_cdf(self) -> None:
        for mode in ("clocked", "first_passage"):
            cell = EventDynamics(mode)
            mass = cell.initial(1)
            expected_count = 0.0
            for _ in range(12):
                mass, events = cell(mass, torch.tensor([6.0]))
                expected_count += float(events.sum().detach())
            self.assertGreater(expected_count, 3.0)

    def test_truncated_reset_mean_against_independent_quadrature(self) -> None:
        cell = EventDynamics("clocked", n_grid=127)
        drive = 0.8
        dt = 0.75
        physical = {k: float(v.detach()) for k, v in cell.physical_parameters().items()}
        b, leak, sigma = physical["boundary"], physical["leak"], physical["diffusion"]
        mean = drive * (-math.expm1(-leak * dt)) / leak
        sd = sigma * math.sqrt(-math.expm1(-2.0 * leak * dt) / (2.0 * leak))
        reset_plus, reset_minus = cell.reset_distributions()
        grid = cell.active_grid()
        r_plus = float((reset_plus @ grid).detach())
        r_minus = float((reset_minus @ grid).detach())
        lower, upper = (-b - mean) / sd, (b - mean) / sd
        phi = lambda z: math.exp(-z * z / 2.0) / math.sqrt(2.0 * math.pi)
        analytic_inside = mean * (ndtr(upper) - ndtr(lower)) + sd * (phi(lower) - phi(upper))
        quadrature_inside, _ = quad(lambda x: x * phi((x - mean) / sd) / sd, -b, b, epsabs=1e-13)
        self.assertAlmostEqual(float(analytic_inside), quadrature_inside, places=12)
        exact = quadrature_inside + r_plus * ndtr(-upper) + r_minus * ndtr(lower)
        mass, _ = cell(cell.initial(1), torch.tensor([drive]), dt)
        projected_mean = float(cell.state_features(mass)[0, 0].detach())
        self.assertLess(abs(projected_mean - exact), 1e-4)
        naive = mean * (ndtr(upper) - ndtr(lower)) + r_plus * ndtr(-upper) + r_minus * ndtr(lower)
        self.assertGreater(abs(naive - exact), 0.04)

    def test_joint_gradients_match_finite_differences(self) -> None:
        for mode in ("clocked", "first_passage"):
            cell = EventDynamics(mode, n_grid=9)

            def objective() -> torch.Tensor:
                mass = cell.initial(2)
                total = torch.zeros((), dtype=torch.float64)
                for t in range(5):
                    drive = torch.tensor([1.1 + 0.07 * t, -0.8 + 0.03 * t], dtype=torch.float64)
                    mass, events = cell(mass, drive, dt=0.8)
                    features = cell.state_features(mass)
                    total = total + (t + 1) * (features[:, 0] * torch.tensor([0.7, -0.2])).sum()
                    total = total + 0.3 * features[:, 1].sum() + (events * torch.tensor([0.19, 0.11])).sum()
                return total

            loss = objective()
            parameters = list(cell.named_parameters())
            gradients = torch.autograd.grad(loss, [p for _, p in parameters])
            for (name, parameter), derivative in zip(parameters, gradients):
                with self.subTest(mode=mode, parameter=name):
                    self.assertTrue(torch.isfinite(derivative).all())
                    self.assertGreater(abs(float(derivative)), 1e-7)
                    saved = float(parameter.detach())
                    epsilon = 1e-5
                    with torch.no_grad():
                        parameter.fill_(saved + epsilon)
                        high = float(objective())
                        parameter.fill_(saved - epsilon)
                        low = float(objective())
                        parameter.fill_(saved)
                    numerical = (high - low) / (2.0 * epsilon)
                    self.assertAlmostEqual(float(derivative), numerical, delta=2e-6 + 2e-5 * abs(numerical))

    def test_continuous_projection_is_explicit_and_has_no_events(self) -> None:
        cell = EventDynamics("continuous")
        mass, events = cell(cell.initial(1), torch.tensor([100.0]))
        self.assertEqual(float(events.sum()), 0.0)
        self.assertGreater(float(mass[0, cell.n_grid - 1].detach()), 1.0 - 1e-12)
        mean = cell.state_features(mass)[0, 0]
        torch.testing.assert_close(mean, cell.active_grid()[-1])


if __name__ == "__main__":
    unittest.main(verbosity=2)

