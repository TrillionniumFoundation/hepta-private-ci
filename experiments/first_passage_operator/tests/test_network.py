"""Independent moment, propagation and whole-network training checks."""

import unittest

import numpy as np
import torch

from experiments.first_passage_operator.network import (
    RecurrentNetwork, RenewalNetwork, renewal_moments, sample_segment,
)
from experiments.first_passage_operator.tasks import task_data
from experiments.first_passage_cell.kernels import first_passage


def tensor(value):
    return torch.tensor(value, dtype=torch.float64, requires_grad=True)


class NetworkTests(unittest.TestCase):
    def test_conditional_moment_gradients(self):
        values = [-0.03, 0.025, 1.4, 0.24, 0.75, -0.03, 0.085]
        args = [tensor(x) for x in values]
        def result(*parts):
            out = renewal_moments(*parts, 0.5, order=32)
            return torch.stack([out[k] for k in ("count", "active", "voltage", "refractory")])
        self.assertTrue(torch.autograd.gradcheck(result, tuple(args), eps=1e-6,
                                                 atol=2e-6, rtol=2e-5))

    def test_exact_cdf_and_independent_simulation_moments(self):
        from experiments.first_passage_operator.network import passage_cdf
        actual = passage_cdf(tensor(0.5), tensor(1.2), tensor(0.25), tensor(0.4))
        expected = float(first_passage(0.5, -1.2, 0.25, 0.4)["F"])
        self.assertAlmostEqual(actual.item(), expected, places=13)
        size = 60000
        values = [-0.02, 0.025, 2.6, 0.3, 0.7, -0.02, 0.085]
        sample = sample_segment(np.full(size, values[0]), *values[1:], 0.9,
                                np.random.default_rng(97031))
        moments = renewal_moments(*[tensor(v) for v in values], 0.9, order=48)
        for name in ("count", "active", "voltage", "refractory"):
            observed = getattr(sample, name)
            reference = moments[name].item()
            error = abs(observed.mean() - reference)
            standard_error = observed.std(ddof=1) / np.sqrt(size)
            self.assertLess(error, 4.5 * standard_error + 1e-6, (name, error, standard_error))
        self.assertGreater(sample.count.mean(), 2)

    def test_refractory_carry_multiple_events_and_replay(self):
        args = (np.array([0.0, 0.1]), np.array([0.1, 0.0]), 4.0, 0.12, 0.6, 0.0, 0.1, 0.7)
        first = sample_segment(*args, np.random.default_rng(9), retain_events=True)
        replay = sample_segment(*args, np.random.default_rng(9), retain_events=True)
        np.testing.assert_array_equal(first.count, replay.count)
        np.testing.assert_array_equal(first.voltage, replay.voltage)
        self.assertEqual(first.events, replay.events)
        self.assertTrue(np.all(first.count >= 2))
        for unit in range(2):
            times = sorted(t for i, t in first.events if i == unit)
            self.assertTrue(all(b - a >= 0.1 for a, b in zip(times, times[1:])))
            self.assertAlmostEqual(first.active[unit] + args[1][unit] +
                                   first.count[unit] * 0.1 - first.refractory[unit], 0.7, places=12)
        hold = sample_segment(np.array([0.0]), 0.1, 4.0, 0.12, 0.6, 0.0, 0.1,
                              0.04, np.random.default_rng(1))
        self.assertAlmostEqual(float(hold.refractory[0]), 0.06)
        self.assertEqual(float(hold.count[0]), 0)

    def test_network_dynamics_receive_gradients_and_layers_spike(self):
        x, y = task_data("evidence", "train", 404, 32)
        for kind in ("first_passage", "lif", "rnn"):
            net = RecurrentNetwork(seed=1) if kind == "rnn" else RenewalNetwork(kind=kind, seed=1)
            self.assertEqual(sum(p.numel() for p in net.parameters()), 55)
            logits, logs = net(torch.tensor(x), noise_seed=1, capture=True)
            loss = torch.nn.functional.binary_cross_entropy_with_logits(logits, torch.tensor(y))
            loss.backward()
            for name, p in net.named_parameters():
                self.assertIsNotNone(p.grad, name)
                self.assertTrue(torch.isfinite(p.grad).all(), name)
                self.assertGreater(float(p.grad.abs().max()), 1e-12, (kind, name))
            if kind == "first_passage":
                for layer in range(2):
                    self.assertGreater(sum(row["count"].sum() for row in logs if row["layer"] == layer), 0)
                initial = {k: v.detach().clone() for k, v in net.named_parameters()}
                torch.optim.Adam(net.parameters(), lr=0.01).step()
                for name, p in net.named_parameters():
                    self.assertGreater(float((p.detach() - initial[name]).abs().max()), 0, name)

    def test_labels_identifiable_before_transmission_deadline(self):
        for task in ("evidence", "order", "delayed_match"):
            x, y = task_data(task, "train", 404, 1024)
            if task == "evidence":
                prediction = x[:, :7, 0].mean(1) > 0
            elif task == "order":
                first = x[:, :7, 0].argmax(1)
                second = x[:, :7, 1].argmax(1)
                prediction = second < first
            else:
                prediction = x[:, 0, 0] * x[:, 6, 1] > 0
            self.assertGreater(float((prediction == y).mean()), 0.95, task)
        net = RecurrentNetwork(seed=3)
        x, _ = task_data("delayed_match", "train", 404, 16)
        sample = torch.tensor(x, requires_grad=True)
        net(sample).sum().backward()
        self.assertEqual(float(sample.grad[:, 7].abs().max()), 0)
        self.assertGreater(float(sample.grad[:, 6, 1].abs().max()), 1e-6)

    def test_split_identity_and_influence(self):
        x, y = task_data("order", "train", 1, 16)
        other, _ = task_data("order", "confirmation", 1, 16)
        self.assertFalse(np.array_equal(x, other))
        net = RenewalNetwork(seed=3)
        with torch.no_grad():
            a = net(torch.tensor(x), noise_seed=71)
            net.w1.zero_()
            b = net(torch.tensor(x), noise_seed=71)
        self.assertGreater(float((a - b).abs().max()), 1e-6)


if __name__ == "__main__":
    torch.set_num_threads(1)
    unittest.main()
