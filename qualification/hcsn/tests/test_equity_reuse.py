"""Prepared HX expressions preserve values, full gradients and feature hooks."""

from dataclasses import fields, replace
import itertools
import unittest
from unittest import mock

import torch

from qualification.hcsn import cells, tensor as hx
from qualification.hcsn.matched_gate import MatchedGateCell


class EquityReuseTests(unittest.TestCase):
    def setUp(self):
        torch.manual_seed(823)
        torch.set_num_threads(1)

    def test_prepared_values_and_all_nine_physical_gradients(self):
        names = tuple(f.name for f in fields(hx.HXParams))
        for dtype, atol, rtol in ((torch.float64, 2e-9, 3e-10), (torch.float32, 2e-4, 3e-5)):
            for ell in (0., 1e-10, .01):
                for supplied in (False, True):
                    values = [.05, .02, .2, 5., 100., .05, .25, .6, ell]
                    theta = torch.tensor(values, dtype=dtype, requires_grad=True)
                    # FP32 x=12 at this short maturity has nonfinite gradients
                    # in the frozen direct kernel too; retained separately in
                    # the study's unresolved stress record, never a pass case.
                    margins = [0., 1e-7, .003, .03, .3, 2.] + ([12.] if dtype == torch.float64 else [])
                    x = torch.tensor(margins, dtype=dtype, requires_grad=True)
                    p = hx.HXParams(**dict(zip(names, theta)))
                    b = 1.1*hx.hx_boundary(p) if supplied else None
                    direct = hx.hx_equity(x, p, boundary=b)
                    reused = hx.prepared_hx_equity(x, hx.prepare_hx_equity(p, b))
                    torch.testing.assert_close(reused, direct, atol=atol, rtol=rtol)
                    weights = torch.arange(1, len(margins)+1, dtype=dtype)
                    old = torch.autograd.grad((direct*weights).sum(), (theta, x), retain_graph=True)
                    new = torch.autograd.grad((reused*weights).sum(), (theta, x))
                    for actual, expected in zip(new, old):
                        torch.testing.assert_close(actual, expected, atol=atol, rtol=rtol)

    def test_sequence_matches_uncached_public_steps_and_refreshes_graph(self):
        for dtype, tolerance in ((torch.float64, 3e-11), (torch.float32, 3e-5)):
            for boundary in ("conditional", "fixed"):
                cell = cells.ValueKernelCell(3, 5, boundary=boundary, equity_evaluation="prepared").to(dtype=dtype)
                for update in range(2):
                    sequence = torch.randn(2, 7, 3, dtype=dtype, requires_grad=True)
                    actual = cell(sequence)
                    params = cell.financial_parameters()
                    base = cell._base_boundary(params)
                    state = cell.initial_state(2, like=sequence)
                    outputs = []
                    for item in sequence.unbind(1):
                        state = cell.step(item, state, params=params, base_boundary=base)
                        outputs.append(state[0])
                    expected = torch.stack(outputs, 1)
                    parameters = [sequence] + [p for p in cell.parameters() if p.requires_grad]
                    old = torch.autograd.grad(expected.square().sum(), parameters, retain_graph=True)
                    new = torch.autograd.grad(actual.square().sum(), parameters)
                    torch.testing.assert_close(actual, expected, atol=tolerance, rtol=tolerance)
                    for a, b in zip(new, old):
                        torch.testing.assert_close(a, b, atol=tolerance, rtol=tolerance)
                    with torch.no_grad():
                        for p, gradient in zip(parameters[1:], new[1:]):
                            p.add_(gradient, alpha=-.01)

    def test_conditional_homogeneity_at_all_cell_parameter_corners(self):
        for dtype, tolerance in ((torch.float64, 3e-10), (torch.float32, 5e-5)):
            cell = cells.ValueKernelCell(2, 64, equity_evaluation="prepared").to(dtype=dtype)
            with torch.no_grad():
                cell.raw_financial.copy_(torch.tensor(list(itertools.product((-16.,16.), repeat=6)), dtype=dtype).T)
            p = cell.financial_parameters()
            b = hx.hx_boundary(p)
            value = torch.tensor([2.4, 3.4, 4.4], dtype=dtype)[:,None].expand(-1,64).clone().requires_grad_()
            shift = torch.tensor([.25, 0., -.25], dtype=dtype)[:,None].requires_grad_()
            scale = shift.exp()
            x = torch.log(value/b)-shift
            local = replace(p, coupon=p.coupon*scale, principal=p.principal*scale)
            expected = hx.hx_equity(x, local, b*scale, validate=False)/value
            actual = scale*hx.prepared_hx_equity(x, hx.prepare_hx_equity(p,b), validate=False)/value
            parameters = (value, shift, cell.raw_financial)
            old = torch.autograd.grad(expected.sum(), parameters, retain_graph=True)
            new = torch.autograd.grad(actual.sum(), parameters)
            torch.testing.assert_close(actual, expected, atol=tolerance, rtol=tolerance)
            for a, b in zip(new, old):
                torch.testing.assert_close(a, b, atol=tolerance, rtol=tolerance)

    def test_risk_only_and_subclass_features_do_not_prepare_equity(self):
        sequence = torch.randn(2, 4, 3, dtype=torch.float64)
        for model in (cells.ValueKernelCell(3, 5, channel="risk", equity_evaluation="prepared").double(),
                      MatchedGateCell(3, 5).double()):
            with mock.patch.object(cells, "prepare_hx_equity", side_effect=AssertionError("unused HX preparation")):
                result = model(sequence)
                result.square().mean().backward()
                self.assertTrue(all(p.grad is not None for p in model.parameters() if p.requires_grad))


if __name__ == "__main__":
    unittest.main()
