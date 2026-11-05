"""Independent mass and renewal tests for the population-flux mechanism."""

from dataclasses import replace
import unittest
import numpy as np
from scipy.integrate import quad
from scipy.special import ndtr
from qualification.hcsn.population import Population, PopulationConfig, PopulationState, killed_transition, _log_interval


class PopulationTests(unittest.TestCase):
    def test_empty_and_infinite_intervals(self):
        a = np.array([-np.inf, -np.inf, -np.inf, -2., -1., 0., 8.])
        b = np.array([-np.inf, np.inf, -1., np.inf, -1., 1., 8.3])
        actual = np.exp(_log_interval(a, b))
        expected = np.array([0., 1., ndtr(-1.), ndtr(2.), 0., ndtr(1.)-.5,
                             ndtr(-8.)-ndtr(-8.3)])
        np.testing.assert_allclose(actual, expected, atol=1e-15, rtol=1e-13)
        self.assertTrue(np.isnan(_log_interval(np.array(1.), np.array(0.))))

    def test_refractory_from_actual_event_rounds_up_without_an_extra_step(self):
        cfg = PopulationConfig(bins=32, refractory=.065, dt=.02)
        model = Population(cfg)
        step = model.step(model.initial_state(), drive=100.)
        self.assertGreater(float(step.absorbed), 1-1e-14)
        self.assertEqual(cfg.refractory_steps, 4)
        state = step.state
        for _ in range(4):
            step = model.step(state, drive=100.)
            state = step.state
            self.assertLess(float(step.absorbed), 1e-20)
        self.assertAlmostEqual(float(state.active.sum()), 1.)
        self.assertGreater(float(model.step(state, drive=100.).absorbed), 1-1e-14)

    def test_transition_matches_density_quadrature(self):
        x, sigma, dt, mu = 0.45, 0.35, 0.2, -0.8
        edges = np.array([0., .2, .6, 1.0])
        matrix, hit, escape = killed_transition([x], edges, np.array([mu]), sigma, dt)
        s = sigma * np.sqrt(dt)
        def density(y):
            a = np.exp(-0.5 * ((y-x-mu*dt)/s)**2)
            b = np.exp(-2*mu*x/sigma**2-0.5*((y+x-mu*dt)/s)**2)
            return (a-b)/(np.sqrt(2*np.pi)*s)
        expected = np.array([quad(density, a, b)[0] for a, b in zip(edges[:-1], edges[1:])])
        np.testing.assert_allclose(matrix[0], expected, atol=2e-14)
        self.assertAlmostEqual(float(escape[0]), quad(density, 1, np.inf)[0], places=13)
        self.assertAlmostEqual(float(hit[0]), 1-quad(density, 0, np.inf)[0], places=13)

    def test_mass_balance_under_drive_and_recovery(self):
        model = Population(PopulationConfig(bins=32, x_max=1.2))
        state = model.initial_state((2,))
        for k in range(120):
            step = model.step(state, np.array([3.5, -2.0]) if k < 60 else 0.)
            state = step.state
            np.testing.assert_allclose(state.total_mass(), np.ones(2), atol=2e-12)
            self.assertGreaterEqual(float(state.active.min()), 0)
            self.assertTrue(np.all(step.rate <= 1/model.config.dt + 1e-9))
        self.assertGreater(float(state.escaped[1]), 0.01)
        self.assertGreater(float(state.recovery[0]), 0.0)

    def test_refractory_has_no_early_release(self):
        cfg = PopulationConfig(bins=32, refractory=0.06, dt=0.02)
        model = Population(cfg)
        q = np.zeros(cfg.refractory_steps)
        q[-1] = 1.0
        state = PopulationState(np.zeros(cfg.bins), q, np.array(0.), np.array(0.))
        for _ in range(cfg.refractory_steps):
            step = model.step(state, drive=10.)
            self.assertEqual(float(step.rate), 0.)
            state = step.state
        self.assertAlmostEqual(float(state.active.sum()), 1.)
        self.assertEqual(float(state.refractory.sum()), 0.)
        self.assertGreater(float(model.step(state, drive=100.).rate), 0.)

    def test_zero_refractory_resets_at_end(self):
        cfg = PopulationConfig(bins=32, refractory=0., recovery_strength=0.)
        model = Population(cfg)
        step = model.step(model.initial_state(), drive=100.)
        self.assertGreater(float(step.absorbed), .99)
        np.testing.assert_allclose(step.state.active, model.reset_weights, atol=1e-12)
        self.assertEqual(step.state.refractory.size, 0)

    def test_quiet_state_and_repeatable_pulses(self):
        model = Population(PopulationConfig(bins=48))
        state = model.initial_state()
        rates = []
        for k in range(420):
            drive = 4.5 if 50 <= k < 75 or 250 <= k < 275 else 0.
            step = model.step(state, drive)
            state = step.state
            rates.append(float(step.rate))
        self.assertLess(max(rates[:50]), 1e-8)
        self.assertGreater(max(rates[50:80]), 1.)
        self.assertLess(max(rates[-50:]), 1e-8)
        self.assertLess(abs(max(rates[50:100])-max(rates[250:300])), .02)
        self.assertLess(float(state.escaped), 1e-8)

    def test_first_passage_refinement(self):
        x, mu, sigma, horizon = .45, -.25, .35, 1.2
        s = sigma*np.sqrt(horizon)
        exact = ndtr((-x-mu*horizon)/s)+np.exp(-2*mu*x/sigma**2)*ndtr((-x+mu*horizon)/s)
        errors = []
        for bins, dt in [(48, .04), (96, .02), (192, .01)]:
            cfg = PopulationConfig(bins=bins, x_max=2.4, dt=dt, sigma=sigma,
                                   rest_margin=x, reset_margin=x, leak=0., base_drift=mu,
                                   refractory=2., recovery_strength=0.)
            model, total = Population(cfg), 0.
            state = model.initial_state()
            for _ in range(round(horizon/dt)):
                step = model.step(state)
                state = step.state
                total += float(step.absorbed)
            errors.append(abs(total-exact))
        self.assertLess(errors[1], errors[0])
        self.assertLess(errors[2], errors[1])
        self.assertLess(errors[-1], .003)

    def test_invalid_parameters_and_state_rejected(self):
        for change in [{"sigma":0.}, {"dt":-1.}, {"reset_margin":0.}, {"recovery_tau":0.}, {"refractory":-.1}]:
            with self.assertRaises(ValueError):
                replace(PopulationConfig(), **change)
        model = Population()
        with self.assertRaises(ValueError):
            model.step(model.initial_state(), drive=np.nan)


if __name__ == "__main__":
    unittest.main()
