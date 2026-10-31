"""Independent unit fixtures only; never opens a registered confirmation set."""

import math
import unittest

import numpy as np

from .. import analytic
from ..round4 import runtime_law, runtime_learning
from . import continuation, reference


def law(weights=(0.65, 0.35), means=(-0.45, 0.85), variances=(0.09, 0.36)):
    return {'schema': 'hepta.conditional-law.v4', 'semantics': 'terminal',
            'weights': list(weights), 'means': list(means), 'variances': list(variances)}


def difference(function, value, step):
    return (-function(value + 2 * step) + 8 * function(value + step)
            - 8 * function(value - step) + function(value - 2 * step)) / (12 * step)


class MathReferenceTests(unittest.TestCase):
    def test_dense_conditioning_matches_sequential_one_and_two_sensor_updates(self):
        priors = [law(), law((1.0,), (0.3,), (0.7,)), law((0.005, 0.995), (-1.2, 0.4), (0.03, 0.9))]
        for prior in priors:
            for values, variances in [([0.2], [0.04]), ([-0.4, 1.1], [0.36, 0.16])]:
                independent = reference.dense_posterior(prior, values, variances, 1.75)
                actual = runtime_law.posterior(prior, values, variances, 1.75)
                for name in ('weights', 'means', 'variances'):
                    np.testing.assert_allclose(actual[name], independent[name], rtol=4e-12, atol=3e-14)

    def test_posterior_mean_is_strictly_increasing_with_variance_identity(self):
        for prior, noise in [(law(), 0.07), (law((0.5, 0.5), (-1, 1), (0.04, 0.04)), 0.4)]:
            points = np.linspace(-3, 3, 31)
            means, variances = reference.posterior_moments_at(prior, points, noise)
            self.assertTrue(np.all(np.diff(means) > 0))
            numerical = difference(lambda x: reference.posterior_moments_at(prior, x, noise)[0], points, 1e-4)
            np.testing.assert_allclose(numerical, variances / noise, rtol=1e-9, atol=2e-10)

    def test_gaussian_closed_form_and_two_equal_components_match_fixed_quadrature(self):
        for mean, variance, noise, cost in [(-0.8, 0.2, 0.04, 0.12), (0, 0.7, 0.6, 0.48),
                                             (0.35, 0.3, 0.16, 0.03), (1.2, 0.02, 0.64, 0.48)]:
            prior = law((1,), (mean,), (variance,))
            exact = reference.gaussian_continuation(prior, noise, cost)
            independent = reference.continuation_reference(prior, noise, cost)
            actual, diagnostic = continuation.continuation_value(prior, noise, cost)
            self.assertAlmostEqual(actual, exact, delta=3e-13)
            self.assertAlmostEqual(independent, exact, delta=3e-12)
            self.assertEqual(diagnostic['method'], 'normal-positive-square-closed-form')
            duplicate = law((0.37, 0.63), (mean, mean), (variance, variance))
            actual_two, _ = continuation.continuation_value(duplicate, noise, cost)
            self.assertAlmostEqual(actual_two, exact, delta=4e-11)

    def test_mixture_continuation_against_independent_order_doubling(self):
        priors = [law(), law((0.5, 0.5), (-1, 1), (0.04, 0.04)),
                  law((0.0001, 0.9999), (-1.8, 0.3), (0.02, 0.6))]
        for prior in priors:
            for noise, cost in [(0.04, 0.03), (0.28, 0.12), (1.12, 0.48)]:
                independent = reference.continuation_reference(prior, noise, cost, order=256)
                doubled = reference.continuation_reference(prior, noise, cost, order=512)
                actual, diagnostic = continuation.continuation_value(prior, noise, cost)
                self.assertAlmostEqual(independent, doubled, delta=2e-10)
                self.assertAlmostEqual(actual, doubled, delta=3e-10)
                self.assertGreater(diagnostic['quadrature_evaluations'], 0)
                self.assertGreaterEqual(diagnostic['quadrature_error_estimate'], 0)
                self.assertGreater(diagnostic['truncation_upper_bound'], 0)
                self.assertLess(diagnostic['truncation_upper_bound'], 1e-25)
                self.assertFalse(diagnostic['floating_point_error_bound_claimed'])

    def test_paid_wait_changes_choice_on_each_side_of_stop_boundary(self):
        prior = law((0.5, 0.5), (-0.7, 0.7), (0.12, 0.12))
        cost, noise = 0.12, 0.16
        expectation = reference.continuation_reference(prior, noise, cost, order=512)
        for displacement, expected in [(-1e-6, 'wait'), (1e-6, 'stop')]:
            public = {'initial': 0.0, 'residuals': [0.0], 'variances': [0.36],
                      'repair_cost': cost, 'wait_cost': expectation + displacement, 'wait_variance': noise}
            values = continuation.action_values(prior, public, 1.0)
            choices = {'stop': 0.0, 'repair': values['repair_gain'], 'wait': values['wait_gain']}
            self.assertEqual(max(choices, key=choices.get), expected)
            self.assertFalse(values['future_transport_quantization_included_in_bound'])
            self.assertFalse(values['learned_future_readout_policy_included_in_integral'])
            public['residuals'].append(0.2)
            public['variances'].append(noise)
            self.assertIsNone(continuation.action_values(prior, public, 1.0)['wait_gain'])

    def test_paid_wait_changes_choice_on_each_side_of_repair_boundary(self):
        prior = law((1,), (0.6,), (0.1,))
        expectation = reference.gaussian_continuation(prior, 0.16, 0.12)
        amount = round(0.6 * (1 << 24)) / (1 << 24)
        repair = 2 * amount * 0.6 - amount * amount - 0.12
        for displacement, expected in [(-1e-6, 'wait'), (1e-6, 'repair')]:
            public = {'initial': 0.0, 'residuals': [0.6], 'variances': [0.36],
                      'repair_cost': 0.12, 'wait_cost': expectation - repair + displacement, 'wait_variance': 0.16}
            values = continuation.action_values(prior, public, 1.0)
            choices = {'stop': 0.0, 'repair': values['repair_gain'], 'wait': values['wait_gain']}
            self.assertEqual(max(choices, key=choices.get), expected)

    def test_terminal_logs_match_independent_density_integration_including_far_tails(self):
        for mean, variance, lower, upper in [(0.2, 0.7, -0.5, 0.5), (0, 1, 8, 8.001),
                                               (0, 1, 40, 40.00001), (0, 1, -40.00001, -40),
                                               (0, 1, 30, 30.00000001)]:
            independent = reference.normal_event_logs(mean, variance, lower, upper)
            actual = analytic.event_log_probs(mean, variance, lower, upper)
            np.testing.assert_allclose(actual, independent, rtol=2e-12, atol=4e-10)
        for threshold in (-2.0, 0.0, 1.3):
            probabilities = analytic.event_probs(0.2, 0.7, threshold, threshold)
            self.assertEqual(probabilities[1], 0)
            self.assertAlmostEqual(probabilities[0] + probabilities[2], 1, delta=3e-15)
        np.testing.assert_allclose(runtime_law.event_logs(law(), -0.5, 0.5),
                                   reference.event_logs(law(), -0.5, 0.5), rtol=2e-13, atol=3e-13)

    def test_inherited_probability_and_propagation_gradients_against_five_point_reference(self):
        mean, variance, lower, upper = 0.2, 0.7, -0.35, 0.8
        gradients = analytic.event_gradients(mean, variance, lower, upper)
        for key, value in [('mean', mean), ('variance', variance)]:
            function = lambda x: np.exp(reference.normal_event_logs(x if key == 'mean' else mean,
                x if key == 'variance' else variance, lower, upper))
            np.testing.assert_allclose(gradients[key], difference(function, value, 1e-4), atol=3e-10, rtol=3e-9)
        parameters = dict(mean=mean, variance=variance, drift=-0.2, diffusion=0.4, dt=1.1)
        actual = analytic.transition_event_gradients(**parameters, lower=lower, upper=upper)
        for key in parameters:
            def probability(value):
                p = {**parameters, key: value}
                return np.exp(reference.normal_event_logs(p['mean'] + p['drift'] * p['dt'],
                    p['variance'] + p['diffusion'] ** 2 * p['dt'], lower, upper))
            np.testing.assert_allclose(actual[key], difference(probability, parameters[key], 1e-4), atol=3e-10, rtol=3e-9)

    def test_learned_noise_scale_is_actual_supervised_objective_optimum(self):
        errors, variances = np.array([-0.4, 0.8, -0.2, 1.1]), np.array([0.04, 0.36, 0.16, 0.64])
        for log_scale in (-0.5, 0.2, 1.3):
            objective, gradient = reference.noise_objective(log_scale, errors, variances)
            numerical = difference(lambda x: reference.noise_objective(x, errors, variances)[0], log_scale, 1e-4)
            self.assertAlmostEqual(gradient, numerical, delta=2e-11)
        optimum = float(np.mean(errors ** 2 / variances))
        self.assertAlmostEqual(reference.noise_objective(math.log(optimum), errors, variances)[1], 0, delta=2e-16)
        rng = np.random.default_rng(630061)
        initial, target = rng.normal(size=(2, 24))
        first, second = rng.normal(size=(2, 24))
        data = {'initial_output': initial, 'target': target, 'self_evaluation': target + first,
                'wait_evaluation': target + second, 'sensor_variance': np.full(24, 0.36),
                'wait_variance': np.full(24, 0.16), 'repair_cost': np.full(24, 0.12), 'wait_cost': np.full(24, 0.04)}
        fitted, receipt = runtime_learning.fit_dynamics(data)
        sensor_errors = np.concatenate([first, second])
        declared = np.concatenate([data['sensor_variance'], data['wait_variance']])
        scale = fitted['calibration']['noise_scale']
        self.assertAlmostEqual(reference.noise_objective(math.log(scale), sensor_errors, declared)[1], 0, delta=5e-16)
        self.assertNotEqual(scale, receipt['noise_scale_initial'])

    def test_q24_rounding_bound_is_separate_from_transport(self):
        values = np.random.default_rng(630062).uniform(-8, 8, 200)
        rounded = np.rint(values * (1 << 24)) / (1 << 24)
        # Algebraic loss avoids cancellation from subtracting two large gains.
        losses = (values - rounded) ** 2
        self.assertLessEqual(float(losses.max()), continuation.ROUNDING_LOSS_BOUND)
        self.assertEqual(continuation.ROUNDING_LOSS_BOUND, 1 / (4 * (1 << 24) ** 2))


if __name__ == '__main__':
    unittest.main()
