"""Causal integration checks; these tiny backward fixtures are not training runs."""

import unittest
from unittest import mock

import torch

from .. import cells as cell_module
from ..content_model import (AddressedContentModel, ContentValueCell, parameter_activity,
                             query_loss, route_content)


def episode():
    inputs = torch.zeros(1, 6, 4+4+5)
    inputs[0, 0, [0, 4, 8+2]] = 1
    inputs[0, 1, [0, 5, 8+3]] = 1
    inputs[0, 2, 3] = 1
    inputs[0, 3, [1, 4]] = 1
    inputs[0, 4, [0, 4, 8+1]] = 1
    inputs[0, 5, [1, 4]] = 1
    targets = torch.tensor([[-100, -100, -100, 2, -100, 1]])
    return inputs, targets


class ContentModelTests(unittest.TestCase):
    def setUp(self):
        torch.manual_seed(509)
        torch.set_num_threads(1)

    def test_routing_binds_values_to_keys_and_queries_do_not_write(self):
        inputs, _ = episode()
        routed = route_content(inputs, 4, 5).reshape(1, 4, 6, 9)
        self.assertEqual(routed[0, 0, 0, 4+2], 1)
        self.assertEqual(routed[0, 1:, 0, 4:].count_nonzero(), 0)
        self.assertEqual(routed[0, :, 3, 4:].count_nonzero(), 0)
        changed = inputs.clone()
        changed[0, 3, 4:8] = torch.tensor([0., 1., 0., 0.])
        torch.testing.assert_close(route_content(changed, 4, 5), routed.reshape(4, 6, 9), rtol=0, atol=0)

    def test_query_swap_changes_read_address_without_changing_core_state(self):
        inputs, _ = episode()
        model = AddressedContentModel("hx_dual", keys=4, values=5, hidden_size=4)
        changed = inputs.clone()
        changed[0, 3, 4:8] = torch.tensor([0., 1., 0., 0.])
        states = model.encode(inputs)
        torch.testing.assert_close(model.encode(changed), states, rtol=0, atol=0)
        torch.testing.assert_close(model(changed)[0, 3], model.head(states[0, 3, 1]))
        self.assertFalse(torch.equal(model(inputs)[0, 3], model(changed)[0, 3]))

    def test_future_overwrite_cannot_change_earlier_query(self):
        inputs, _ = episode()
        changed = inputs.clone()
        changed[0, 4, 8:] = torch.tensor([1., 0., 0., 0., 0.])
        for core in ("hx_dual", "smooth_gate", "gru", "cfc", "transformer"):
            model = AddressedContentModel(core, keys=4, values=5, hidden_size=4)
            with self.subTest(core=core):
                torch.testing.assert_close(model(inputs)[:, :4], model(changed)[:, :4])

    def test_actual_query_backward_and_pruned_channel_coefficients(self):
        inputs, targets = episode()
        mask = targets != -100
        for core in ("hx_dual", "hx_call", "hx_risk", "margin_only", "smooth_gate", "gru", "cfc", "transformer"):
            model = AddressedContentModel(core, keys=4, values=5, hidden_size=4)
            query_loss(model(inputs), targets, mask).backward()
            report = parameter_activity(model)
            with self.subTest(core=core):
                self.assertGreater(report["observed_nonzero_gradient"], 0)
                self.assertTrue(all(row["finite_gradient"] is not False for row in report["parameters"]))
                self.assertFalse(report["parameter_match_qualified"])
                if core in {"hx_call", "hx_risk", "margin_only"}:
                    self.assertEqual(model.core.rate_features.shape, (1, 4))
                    self.assertEqual(model.core.value_features.shape, (1, 4))

    def test_smooth_control_does_not_call_financial_kernel(self):
        cell = ContentValueCell(9, 4, "smooth_gate")
        with mock.patch.object(cell_module, "hx_boundary", side_effect=AssertionError), \
                mock.patch.object(cell_module, "hx_equity", side_effect=AssertionError), \
                mock.patch.object(cell_module.ValueKernelCell, "financial_parameters", side_effect=AssertionError):
            self.assertTrue(torch.isfinite(cell(torch.randn(2, 3, 9))).all())

    def test_content_stream_resume_and_actual_query_boundary_gradient(self):
        inputs, targets = episode()
        inputs = inputs.double()
        model = AddressedContentModel("hx_dual", keys=4, values=5, hidden_size=4).double()
        edges = (0., .1, .23, .9, 1., 1.2, 1.5)
        whole, _ = model.stream(inputs, edges, subdivisions=2)
        prefix, state = model.stream(inputs[:, :3], edges[:4], subdivisions=2)
        suffix, _ = model.stream(inputs[:, 3:], edges[3:], initial_state=state, subdivisions=2)
        torch.testing.assert_close(torch.cat((prefix, suffix), 1), whole, rtol=0, atol=0)
        loss = query_loss(whole, targets, targets != -100)
        parameter = model.core.boundary_input.weight
        gradient = torch.autograd.grad(loss, parameter)[0]
        direction = torch.cos(torch.arange(parameter.numel(), dtype=torch.float64)).reshape_as(parameter)
        direction /= direction.norm()
        analytic = (gradient*direction).sum()
        original = parameter.detach().clone()
        epsilon = 1e-4
        with torch.no_grad():
            try:
                parameter.copy_(original+epsilon*direction)
                plus = query_loss(model.stream(inputs, edges, subdivisions=2)[0], targets, targets != -100)
                parameter.copy_(original-epsilon*direction)
                minus = query_loss(model.stream(inputs, edges, subdivisions=2)[0], targets, targets != -100)
            finally:
                parameter.copy_(original)
        self.assertGreater(float(analytic.abs()), 1e-9)
        torch.testing.assert_close(analytic, (plus-minus)/(2*epsilon), rtol=2e-3, atol=1e-8)

    def test_malformed_input_time_and_target_mask_are_rejected(self):
        inputs, targets = episode()
        model = AddressedContentModel("gru", keys=4, values=5, hidden_size=4)
        corrupted = inputs.clone()
        corrupted[0, 3, 8] = 1
        with self.assertRaises(ValueError):
            model(corrupted)
        for position, field in ((2, 4), (3, 8)):
            corrupted = inputs.clone()
            corrupted[0, position, field] = 1
            with self.assertRaises(ValueError):
                model(corrupted)
        for interval in (0, True, float("nan"), torch.full((1, 6), .1)):
            with self.assertRaises(ValueError):
                model(inputs, interval)
        for edges in ((0, 0, 1, 2, 3, 4, 5), (False, 1, 2, 3, 4, 5, 6)):
            with self.assertRaises(ValueError):
                model.stream(inputs, edges)
        leaking = targets.clone()
        leaking[0, 0] = 1
        with self.assertRaises(ValueError):
            query_loss(model(inputs), leaking, targets != -100)
        for invalid_class in (-100, 6):
            invalid = targets.clone()
            invalid[targets != -100] = invalid_class
            with self.assertRaises(ValueError):
                query_loss(model(inputs), invalid, targets != -100)


if __name__ == "__main__":
    unittest.main()
