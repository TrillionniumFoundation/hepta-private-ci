"""Repeated pure readouts and repeated observations have different semantics."""

import unittest

import torch

from qualification.hcsn_differentiable.contract import GridSpec
from qualification.hcsn_differentiable.network import ContinuousSpikingNetwork


class ReadoutSemanticsTests(unittest.TestCase):
    def test_reading_twice_does_not_mutate_but_replaying_observation_updates(self):
        with torch.random.fork_rng():
            torch.manual_seed(311)
            model = ContinuousSpikingNetwork(
                2,
                content_dim=2,
                layer_count=1,
                grid=GridSpec(active_cells=6, phase_cells=3, quadrature_order=8),
            )
        layer = model.layers[0]
        with torch.no_grad():
            layer.likelihood.weight.zero_()
            layer.likelihood.bias.copy_(torch.linspace(-1, 1, layer.state_count))
            layer.content_proposal.weight.zero_()
            layer.content_proposal.bias.fill_(0.4)
            layer.state_embedding.zero_()
            layer.write_gate.weight.zero_()
            layer.write_gate.bias.zero_()
        state = model.initial_state(1)
        probability = state.layers[0].probability.clone()
        content = state.layers[0].content_mass.clone()
        flow1 = layer.operator.advance(probability, content, 0.0, layer.physics())
        flow2 = layer.operator.advance(probability, content, 0.0, layer.physics())
        torch.testing.assert_close(
            flow1.interval_value, flow2.interval_value, atol=0, rtol=0
        )
        torch.testing.assert_close(
            probability, state.layers[0].probability, atol=0, rtol=0
        )
        torch.testing.assert_close(
            content, state.layers[0].content_mass, atol=0, rtol=0
        )
        self.assertGreater(float(flow1.interval_value), 0)
        self.assertEqual(float(flow1.expected_events), 0)

        observations = torch.ones(1, 1, 2, dtype=torch.float64)
        dt = torch.zeros(1, 1, dtype=torch.float64)
        first = model(observations, dt, state=state)
        second = model(observations, dt, state=first.state)
        change = float(
            (second.state.layers[0].content_mass - first.state.layers[0].content_mass)
            .abs()
            .sum()
        )
        self.assertGreater(change, 0.01)
        torch.testing.assert_close(second.state.elapsed, state.elapsed, atol=0, rtol=0)
        self.assertEqual(int(second.state.steps[0]), 2)
        self.assertEqual(float(second.expected_events.sum()), 0)
        missing = torch.zeros(1, 1, dtype=torch.bool)
        padded = model(
            observations, dt, state=first.state, observed=missing, valid_mask=missing
        )
        torch.testing.assert_close(
            padded.state.layers[0].content_mass,
            first.state.layers[0].content_mass,
            atol=0,
            rtol=0,
        )
        self.assertEqual(
            padded.state.sequence_position, first.state.sequence_position + 1
        )
        self.assertEqual(float(padded.predictions.abs().sum()), 0)
        self.numerical_evidence = {
            "zero_time_repeated_observation_content_l1": change,
            "pure_query_terminal_feature": float(flow1.interval_value),
        }
