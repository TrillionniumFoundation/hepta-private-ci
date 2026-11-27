"""Actual interface, learning/readback and masked-state checks."""

import io
import unittest

import torch
from torch import nn

from qualification.hcsn_boundary_factorial.run import FactorialModel, GRID, tensor_digest
from .model import BudgetGRU


class BudgetGRUTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        torch.set_num_threads(1)

    def inputs(self):
        generator = torch.Generator().manual_seed(41)
        return torch.randn(1, 4, 21, generator=generator, dtype=torch.float64)

    def test_actual_interfaces_and_capacity_against_factorial(self):
        for seed in (11, 23, 37):
            reference = FactorialModel(seed, "c0_b0", grid=GRID)
            model = BudgetGRU(seed, GRID)
            self.assertEqual(model.interface_digests(), {
                "frontend": tensor_digest(reference.frontend.state_dict()),
                "readout": tensor_digest(reference.network.readout.state_dict())})
            self.assertTrue(all(model.capacity[k] <= model.ceilings[k] for k in model.capacity))
            x = self.inputs()
            self.assertTrue(torch.equal(reference.frontend(x), model.frontend(x)))
            features = torch.randn(1, 4, 9, dtype=torch.float64)
            self.assertTrue(torch.equal(reference.network.readout(features), model.readout(features)))

    def test_real_backward_optimizer_and_checkpoint_readback(self):
        model = BudgetGRU(11, GRID)
        interfaces, before = model.interface_digests(), tensor_digest(model.state_dict())
        optimizer = torch.optim.Adam([p for p in model.parameters() if p.requires_grad], lr=.003)
        x, valid = self.inputs(), torch.ones(1, 4, dtype=torch.bool)
        logits, _ = model(x, valid)
        nn.functional.cross_entropy(logits.flatten(0, 1), torch.tensor([1, 2, 3, 4])).backward()
        self.assertTrue(all(p.grad is not None and bool(torch.isfinite(p.grad).all())
                            for p in model.parameters() if p.requires_grad))
        optimizer.step()
        self.assertEqual(model.interface_digests(), interfaces)
        self.assertNotEqual(tensor_digest(model.state_dict()), before)
        data = io.BytesIO()
        torch.save(dict(model=model.state_dict(), optimizer=optimizer.state_dict()), data)
        data.seek(0)
        checkpoint = torch.load(data, weights_only=True)
        replay = BudgetGRU(11, GRID)
        replay.load_state_dict(checkpoint["model"])
        self.assertTrue(torch.equal(model(x, valid)[0], replay(x, valid)[0]))

    def test_tail_padding_keeps_valid_predictions_and_hidden_state(self):
        model = BudgetGRU(11, GRID)
        x, valid = self.inputs(), torch.ones(1, 4, dtype=torch.bool)
        original, states = model(x, valid)
        padded_x = torch.cat((x, torch.ones(1, 2, 21, dtype=torch.float64)), 1)
        padded_mask = torch.tensor([[True, True, True, True, False, False]])
        padded, padded_states = model(padded_x, padded_mask)
        self.assertTrue(torch.allclose(original, padded[:, :4], atol=1e-14, rtol=1e-14))
        self.assertTrue(torch.equal(padded[:, 4:], torch.zeros_like(padded[:, 4:])))
        self.assertTrue(torch.allclose(states[:, -1], padded_states[:, -1], atol=1e-14, rtol=1e-14))


if __name__ == "__main__":
    unittest.main()
