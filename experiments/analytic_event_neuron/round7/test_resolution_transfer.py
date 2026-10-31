"""Check that the resolution diagnostic changes buffers, never learned data."""

import unittest

import torch

from .joint_control import build_graph, evaluate_graph
from .model import JointCell
from .resolution_transfer import exact_policy_metrics, parameter_sha256, prepare_graph, transfer_parameters_only
from .task import TaskParameters


torch.set_num_threads(1)


class ResolutionTransferTests(unittest.TestCase):
    def test_parameters_are_identical_and_mesh_buffers_are_rebuilt(self):
        torch.manual_seed(2718)
        for mode in ("continuous", "clocked", "first_passage", "first_passage_temperature"):
            source = JointCell(mode, n_grid=5, hidden=6)
            before = parameter_sha256(source)
            target = transfer_parameters_only(source, 9)
            self.assertEqual(parameter_sha256(target), before)
            self.assertEqual(parameter_sha256(source), before)
            self.assertEqual(source.core.normalised_grid.shape, (5,))
            self.assertEqual(target.core.normalised_grid.shape, (9,))
            self.assertEqual(target.core.plus_generator_basis.shape, (9, 11))
            inputs = torch.linspace(-0.2, 0.8, 36, dtype=torch.float64).reshape(2, 18)
            for original, transferred in zip(source.encode(inputs), target.encode(inputs)):
                torch.testing.assert_close(original, transferred, rtol=0.0, atol=0.0)
            for name, value in source.core.physical_parameters().items():
                torch.testing.assert_close(target.core.physical_parameters()[name], value, rtol=0.0, atol=0.0)

    def test_return_and_count_recursion_matches_control_graph(self):
        torch.manual_seed(1618)
        parameters = TaskParameters(horizon=2, budget=2, ordinary_count=1, arrival_tick=1)
        graph = build_graph([parameters])
        model = JointCell("first_passage", n_grid=5, hidden=6)
        prepared = prepare_graph(model, graph)
        for policy, head in (("soft", 1), ("greedy", 1), ("greedy", 0)):
            with self.subTest(policy=policy, head=head):
                metric = exact_policy_metrics(model, graph, prepared, policy=policy, head=head)
                expected, _ = evaluate_graph(model, graph, policy=policy, head=head)
                self.assertAlmostEqual(metric["registered_return"], float(expected.detach()), delta=2e-13)
                epsilon = 1e-5
                with torch.no_grad():
                    high, _ = evaluate_graph(model, graph, policy=policy, head=head, compute_price=0.0005 + epsilon)
                    low, _ = evaluate_graph(model, graph, policy=policy, head=head, compute_price=0.0005 - epsilon)
                self.assertAlmostEqual(float((high - low) / (2.0 * epsilon)), -metric["expected_decisions"], delta=1e-9)
                with torch.no_grad():
                    high, _ = evaluate_graph(model, graph, policy=policy, head=head, event_price=0.0002 + epsilon)
                    low, _ = evaluate_graph(model, graph, policy=policy, head=head, event_price=0.0002 - epsilon)
                self.assertAlmostEqual(float((high - low) / (2.0 * epsilon)), -metric["expected_events"], delta=1e-9)


if __name__ == "__main__":
    unittest.main(verbosity=2)

