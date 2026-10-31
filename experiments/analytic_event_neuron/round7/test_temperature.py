"""Independent probability-law checks for the event-temperature control."""

import math
import unittest
from unittest.mock import patch

import numpy as np
import torch

from .dynamics import EventDynamics
from .joint_control import build_graph, evaluate_graph
from .model import JointCell
from .task import TaskParameters
from .temperature import EventTemperature


torch.set_num_threads(1)


def set_temperature(cell, value):
    fraction = (value - 0.25) / 1.75
    with torch.no_grad():
        cell.raw_temperature.fill_(math.log(fraction / (1.0 - fraction)))


def extreme_transition_fixture():
    """Valid Markov rows, including exact and nearly singular event supports."""
    n = 5
    active_conditional = torch.tensor([0.1, 0.2, 0.3, 0.15, 0.25], dtype=torch.float64)
    event_conditional = torch.tensor([0.7, 0.3], dtype=torch.float64)
    probabilities = [0.0, 1.0, 1e-20, 1.0 - 1e-15, 0.3]
    transition = torch.zeros(1, n + 2, n + 2, dtype=torch.float64)
    events = torch.zeros(1, n + 2, 2, dtype=torch.float64)
    for row, probability in enumerate(probabilities):
        transition[0, row, :n] = (1.0 - probability) * active_conditional
        transition[0, row, n:] = probability * event_conditional
        events[0, row] = transition[0, row, n:]
    transition[0, n, :n] = 0.6 * active_conditional
    transition[0, n, n] = 0.4
    transition[0, n + 1, :n] = 0.3 * active_conditional
    transition[0, n + 1, n + 1] = 0.7
    return transition, events


class EventTemperatureTests(unittest.TestCase):
    def test_temperature_one_matches_the_underlying_fpt_law(self):
        for n_grid in (5, 15):
            base = EventDynamics("first_passage", n_grid)
            control = EventTemperature(n_grid)
            self.assertAlmostEqual(float(control.physical_parameters()["event_temperature"].detach()), 1.0, places=14)
            for dt in (1.0, 0.001):
                drive = torch.tensor([-1.3, 0.0, 0.8], dtype=torch.float64)
                original, original_events = base.transition_matrix(drive, dt)
                changed, changed_events = control.transition_matrix(drive, dt)
                torch.testing.assert_close(changed, original, rtol=2e-11, atol=2e-13)
                torch.testing.assert_close(changed_events, original_events, rtol=2e-11, atol=2e-13)

    def test_extreme_probability_mass_and_conditional_laws(self):
        original, original_events = extreme_transition_fixture()
        for temperature in (0.5, 1.0, 1.8):
            control = EventTemperature(5)
            set_temperature(control, temperature)
            with patch.object(EventDynamics, "transition_matrix", return_value=(original, original_events)):
                changed, events = control.transition_matrix(torch.zeros(1, dtype=torch.float64))
            with self.subTest(temperature=temperature):
                self.assertTrue(torch.isfinite(changed).all())
                self.assertGreaterEqual(float(changed.min().detach()), 0.0)
                torch.testing.assert_close(changed.sum(-1), torch.ones(1, 7, dtype=torch.float64), rtol=0.0, atol=1e-13)
                torch.testing.assert_close(changed[:, 5:, :], original[:, 5:, :], rtol=0.0, atol=0.0)
                torch.testing.assert_close(events[:, :5, :], changed[:, :5, 5:], rtol=0.0, atol=0.0)
                torch.testing.assert_close(events[:, 5:, :], original_events[:, 5:, :], rtol=0.0, atol=0.0)
                for row in range(5):
                    old_survival = float(original[0, row, :5].sum())
                    old_event = float(original[0, row, 5:].sum())
                    new_survival = changed[0, row, :5].sum()
                    new_event = changed[0, row, 5:].sum()
                    if old_survival == 0.0:
                        expected = np.array([0.0, 1.0])
                    elif old_event == 0.0:
                        expected = np.array([1.0, 0.0])
                    else:
                        logs = np.log([old_survival, old_event]) / temperature
                        expected = np.exp(logs - logs.max())
                        expected /= expected.sum()
                    torch.testing.assert_close(torch.stack((new_survival, new_event)),
                                               torch.from_numpy(expected), rtol=3e-12, atol=0.0)
                    if old_survival > 0.0:
                        self.assertGreater(float(new_survival.detach()), 0.0)
                        torch.testing.assert_close(changed[0, row, :5] / new_survival,
                                                   original[0, row, :5] / old_survival,
                                                   rtol=3e-12, atol=2e-15)
                    if old_event > 0.0:
                        self.assertGreater(float(new_event.detach()), 0.0)
                        torch.testing.assert_close(changed[0, row, 5:] / new_event,
                                                   original[0, row, 5:] / old_event,
                                                   rtol=3e-12, atol=2e-15)

    def test_matched_trainable_capacity_and_full_return_integration(self):
        torch.manual_seed(31415)
        model = JointCell("first_passage", n_grid=5, hidden=6)
        graph = build_graph([TaskParameters(horizon=3, budget=3, ordinary_count=1,
                                            arrival_tick=1, corruption_probability=0.4)])
        original, _ = evaluate_graph(model, graph, temperature=0.4)
        original_core = model.core
        original_count = sum(parameter.numel() for parameter in original_core.parameters() if parameter.requires_grad)
        replacement = EventTemperature(5)
        replacement.load_state_dict(original_core.state_dict(), strict=False)
        model.core = replacement
        changed, _ = evaluate_graph(model, graph, temperature=0.4)
        torch.testing.assert_close(changed, original, rtol=2e-11, atol=2e-13)
        changed_count = sum(parameter.numel() for parameter in replacement.parameters() if parameter.requires_grad)
        self.assertEqual(changed_count, original_count)
        self.assertFalse(replacement.raw_diffusion.requires_grad)
        self.assertTrue(replacement.raw_temperature.requires_grad)
        derivative = torch.autograd.grad(changed, replacement.raw_temperature)[0]
        self.assertTrue(torch.isfinite(derivative))
        self.assertGreater(abs(float(derivative)), 1e-12)
        original_parameter = float(replacement.raw_temperature.detach())
        epsilon = 1e-5
        with torch.no_grad():
            replacement.raw_temperature.fill_(original_parameter + epsilon)
            high = float(evaluate_graph(model, graph, temperature=0.4)[0])
            replacement.raw_temperature.fill_(original_parameter - epsilon)
            low = float(evaluate_graph(model, graph, temperature=0.4)[0])
            replacement.raw_temperature.fill_(original_parameter)
        self.assertAlmostEqual(float(derivative), (high - low) / (2.0 * epsilon), delta=2e-8)

    def test_actual_small_tick_kernel_does_not_lose_probability_mass(self):
        control = EventTemperature(15)
        with torch.no_grad():
            control.raw_temperature.fill_(8.0)
        for dt in (0.001, 0.0001):
            changed, events = control.transition_matrix(torch.zeros(1, dtype=torch.float64), dt)
            torch.testing.assert_close(changed.sum(-1), torch.ones(1, 17, dtype=torch.float64),
                                       rtol=0.0, atol=2e-13)
            self.assertGreater(float(events[0, 7].sum().detach()), 0.0)
            derivative = torch.autograd.grad(events[:, :15, :].sum(), control.raw_temperature)[0]
            self.assertTrue(torch.isfinite(derivative))
            self.assertGreater(abs(float(derivative)), 0.0)


if __name__ == "__main__":
    unittest.main(verbosity=2)

