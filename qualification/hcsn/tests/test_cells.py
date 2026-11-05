"""Version-A and baseline behavior; tensor tests must run on a PyTorch host."""

import importlib.util
import itertools
import unittest
from unittest import mock

TORCH_AVAILABLE = importlib.util.find_spec("torch") is not None
if TORCH_AVAILABLE:
    import torch
    from .. import cells as cell_module
    from ..cells import ValueKernelCell
    from ..tensor import hx_boundary, hx_equity
    from ..baselines import UnavailableBaseline, make_encoder


@unittest.skipUnless(TORCH_AVAILABLE, "PyTorch is unavailable; tensor verification is not claimed")
class CellTests(unittest.TestCase):
    def setUp(self):
        torch.manual_seed(31)
        torch.set_num_threads(1)

    def test_frozen_update_preserves_bounds_and_zero_time_identity(self):
        cell = ValueKernelCell(2, 4).double()
        x = torch.tensor([[10.0, -10.0], [-4.0, 8.0]], dtype=torch.float64)
        h, r = cell.initial_state(2, like=x)
        unchanged = cell.step(x, (h, r), dt=0.0)
        torch.testing.assert_close(unchanged[0], h, atol=0, rtol=0)
        torch.testing.assert_close(unchanged[1], r, atol=0, rtol=0)
        for _ in range(40):
            h, r = cell.step(x, (h, r), dt=20.0)
        self.assertTrue(bool((h.abs() <= 1+1e-12).all()))
        self.assertTrue(bool(((r >= 0) & (r <= 1+1e-12)).all()))

    def test_financial_parameter_box_has_nonnegative_continuation_equity(self):
        corners = torch.tensor(list(itertools.product((-16., 16.), repeat=6)), dtype=torch.float64).T
        samples = torch.logit(torch.rand(6, 128, dtype=torch.float64).clamp(.001, .999))
        corners = torch.cat((corners, samples), dim=1)
        cell = ValueKernelCell(2, corners.shape[1]).double()
        with torch.no_grad():
            cell.raw_financial.copy_(corners)
        params = cell.financial_parameters()
        boundary = hx_boundary(params)
        g0 = (params.delta*boundary-(1-params.tax)*params.coupon+
              (params.recovery*boundary-params.principal)/params.maturity)
        self.assertTrue(bool((g0 <= 0).all()))
        self.assertTrue(bool((params.recovery*boundary <= params.principal).all()))
        for kernel in ("hx", "no_rollover"):
            domain_cell = ValueKernelCell(2, corners.shape[1], kernel=kernel).double()
            with torch.no_grad():
                domain_cell.raw_financial.copy_(corners)
            domain_params = domain_cell.financial_parameters()
            largest_boundary = domain_cell._base_boundary(domain_params)*domain_params.principal.new_tensor(.25).exp()
            self.assertTrue(bool((2.4*domain_params.principal > largest_boundary).all()))
        x = torch.tensor([.1, .5, 1.1, 2.1], dtype=torch.float64)[:, None]
        ratio = hx_equity(x, params, boundary=boundary)/(boundary*x.exp())
        self.assertTrue(bool(torch.isfinite(ratio).all()))
        self.assertTrue(bool(((ratio >= -1e-9) & (ratio <= 1+1e-9)).all()))

    def test_full_rollover_backpropagates_to_liquidity_and_input_boundary(self):
        cell = ValueKernelCell(2, 4).double()
        x = torch.randn(2, 4, 2, dtype=torch.float64, requires_grad=True)
        value = cell(x).square().sum()
        value.backward()
        for gradient in (x.grad, cell.raw_financial.grad, cell.boundary_input.weight.grad):
            self.assertIsNotNone(gradient)
            self.assertTrue(bool(torch.isfinite(gradient).all()))
            self.assertGreater(float(gradient.abs().sum()), 0)
        self.assertGreater(float(cell.raw_financial.grad[5].abs().sum()), 0)

    def test_risk_only_preserves_liquidity_and_boundary_sensitivity(self):
        cell = ValueKernelCell(2, 4, channel="risk").double()
        with torch.no_grad():
            cell.margin_input.weight.zero_()
            cell.margin_input.bias.fill_(-4.)
            cell.boundary_input.weight.fill_(.1)
        inputs = torch.tensor([[.5, .2], [.1, .4]], dtype=torch.float64)
        params = cell.financial_parameters()
        boundary = cell._base_boundary(params)
        boundary.retain_grad()
        memory, _ = cell.initial_state(inputs.shape[0], like=inputs)
        with mock.patch.object(cell_module, "hx_equity", side_effect=AssertionError("risk-only must skip equity")):
            features = cell._features(inputs, memory, params, boundary)
            torch.testing.assert_close(features[0], torch.zeros_like(features[0]))
            features[1].sum().backward()
            for gradient in (cell.raw_financial.grad[5], cell.boundary_input.weight.grad, boundary.grad):
                self.assertTrue(bool(torch.isfinite(gradient).all()))
                self.assertGreater(float(gradient.abs().sum()), 1e-12)
            self.assertTrue(bool((boundary.grad > 0).all()))
            cell.zero_grad(set_to_none=True)
            cell(inputs[:, None, :].expand(-1, 3, -1)).square().sum().backward()
            self.assertGreater(float(cell.raw_financial.grad[5].abs().sum()), 1e-12)

    def test_call_only_skips_first_passage_feature(self):
        cell = ValueKernelCell(2, 4, channel="call").double()
        inputs = torch.randn(2, 3, 2, dtype=torch.float64)
        with mock.patch.object(cell_module, "first_passage_cdf", side_effect=AssertionError("call-only must skip risk")):
            outputs = cell(inputs)
            self.assertTrue(bool(torch.isfinite(outputs).all()))
            outputs.square().sum().backward()

    def test_value_map_rejects_a_boundary_above_assets_without_clipping(self):
        cell = ValueKernelCell(2, 4).double()
        inputs = torch.zeros(2, 2, dtype=torch.float64)
        params = cell.financial_parameters()
        state = cell.initial_state(inputs.shape[0], like=inputs)
        with self.assertRaisesRegex(ValueError, "at or above the conditioned boundary"):
            cell.step(inputs, state, params=params, base_boundary=10*params.principal)

    def test_each_native_ablation_and_baseline_trains_one_step(self):
        names = ["hx_dual", "hx_fixed", "hx_call", "hx_risk", "no_rollover", "softplus",
                 "no_recovery", "hx_attention", "population_flux", "gru", "lif", "adaptive_lif", "pif", "transformer"]
        x = torch.randn(2, 4, 2)
        for name in names:
            with self.subTest(model=name):
                model = make_encoder(name, 2, 8)
                output = model(x)
                self.assertEqual(tuple(output.shape), (2, 4, 8))
                self.assertTrue(bool(torch.isfinite(output).all()))
                output.square().sum().backward()
                self.assertTrue(all(p.grad is None or bool(torch.isfinite(p.grad).all()) for p in model.parameters()))

    def test_attention_is_causal_and_optional_mamba_is_not_substituted(self):
        model = make_encoder("transformer", 2, 8)
        x = torch.randn(2, 5, 2)
        modified = x.clone()
        modified[:, 3:] += 20
        torch.testing.assert_close(model(x)[:, :3], model(modified)[:, :3], rtol=1e-5, atol=1e-6)
        with self.assertRaises(UnavailableBaseline):
            make_encoder("mamba2", 2, 8, device="cpu")


if __name__ == "__main__":
    unittest.main()
