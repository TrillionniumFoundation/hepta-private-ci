"""Causality/gradient gate on independent toys; no formal task or final set."""
import unittest

import torch

from .architectures import ArchitectureModel, KINDS, UnavailableBaseline
from .environment import execution_identity
from .tasks import generate


class ArchitectureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        execution_identity()

    def test_parameter_band_causality_and_full_gradient(self):
        data = generate("unit-test-only/architecture-gate", 31, "asynchronous", "train", 2, 4)
        changed = {name: value.copy() for name, value in data.items()}
        changed["x"][:, 2:] += .7
        for kind in KINDS:
            with self.subTest(kind=kind):
                torch.manual_seed(31)
                try:
                    model = ArchitectureModel(kind)
                except UnavailableBaseline:
                    print("UNAVAILABLE: official_cfc; no substitute executed")
                    continue
                with torch.no_grad():
                    prefix = model.sequence(data)[:, :2]
                    other = model.sequence(changed)[:, :2]
                torch.testing.assert_close(prefix, other, rtol=1e-10, atol=1e-11)
                loss = (model(data) - torch.from_numpy(data["y"])).square().mean()
                loss.backward()
                self.assertTrue(torch.isfinite(loss))
                self.assertTrue(all(p.grad is not None and torch.isfinite(p.grad).all()
                                    for p in model.parameters()))
                self.assertTrue(any(p.grad.abs().max() > 0 for p in model.parameters()))
                self.assertGreaterEqual(model.identity()["parameters"], 238)
                self.assertLessEqual(model.identity()["parameters"], 322)


if __name__ == "__main__":
    unittest.main()

