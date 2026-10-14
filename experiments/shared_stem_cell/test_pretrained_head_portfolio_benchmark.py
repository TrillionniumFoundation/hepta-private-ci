"""Actual Torch arithmetic fixtures; synthetic tensors are not model evidence."""
from __future__ import annotations

import unittest
import torch

from experiments.shared_stem_cell import pretrained_head_portfolio_benchmark as b


class HeadPortfolioPhysicalTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        torch.set_num_threads(1)

    def models(self):
        torch.manual_seed(2033)
        result = {name: b.Head(width, kind)
                  for name, width, kind in (
                      ("bank0", 384, "gated"), ("bank1", 384, "gated"),
                      ("shared", 386, "gated"), ("correction", 384, "linear"))}
        for model in result.values():
            model.eval().requires_grad_(False)
        return result

    def test_model_geometry_and_independent_parameter_budget(self):
        x = self.models()
        n = {k: sum(p.numel() for p in v.parameters()) for k, v in x.items()}
        self.assertEqual(n, {"bank0": 6192, "bank1": 6192,
                             "shared": 6224, "correction": 1540})
        self.assertEqual(n["shared"] + n["correction"], 7764)

    def test_route_corrects_only_named_cell_without_weight_mutation(self):
        models = self.models()
        x = torch.randn(6, 384)
        routes = torch.tensor([0, 0, 1, 0, 1, 1])
        old = {name: {k: v.clone() for k, v in m.state_dict().items()}
               for name, m in models.items()}
        shared = b.execute(models, x, routes, "shared")
        corrected = b.execute(models, x, routes, "sparse_corrected")
        self.assertTrue(torch.equal(shared[routes == 0], corrected[routes == 0]))
        self.assertTrue(torch.allclose(corrected[routes == 1],
                                      shared[routes == 1] +
                                      models["correction"](x[routes == 1]),
                                      rtol=1e-6, atol=1e-6))
        for name, model in models.items():
            for key, before in old[name].items():
                self.assertTrue(torch.equal(before, model.state_dict()[key]))

    def test_missing_and_malformed_scope_features_refuse_before_forward(self):
        models = self.models()
        routes = torch.tensor([0, 1])
        for x, cells in ((torch.randn(2, 383), routes),
                         (torch.randn(2, 384), torch.tensor([0, 2])),
                         (torch.randn(2, 384), torch.tensor([0., 1.])),
                         (torch.full((2, 384), float("nan")), routes)):
            with self.subTest(shape=tuple(x.shape)), self.assertRaises(b.audit.AuditError):
                b.execute(models, x, cells, "shared")
        with self.assertRaises(b.audit.AuditError):
            b.execute(models, torch.randn(2, 384), routes, "unknown")


if __name__ == "__main__":
    unittest.main()
