"""Deterministic CPU mechanism checks, not pretrained Granite learning evidence."""
import unittest

import torch
from torch.nn import functional as F

from cross_fact_bridge import FactInteractionBlock, matched_reader_pair


class CrossFactMechanismTests(unittest.TestCase):
    def setUp(self):
        torch.set_num_threads(1)
        torch.manual_seed(9)

    def test_equal_trainable_parameters_and_identical_base(self):
        cross, local = matched_reader_pair()
        self.assertEqual(sum(p.numel() for p in cross.fact_block.parameters()), 4096)
        self.assertEqual(sum(p.numel() for p in local.fact_block.parameters()), 4096)
        self.assertEqual(sum(p.numel() for p in cross.parameters()), sum(p.numel() for p in local.parameters()))
        self.assertEqual(len(list(cross.fact_block.parameters())), 4)

    def test_cross_fact_has_nonlocal_gradient_local_control_does_not(self):
        cross = FactInteractionBlock(8, 'cross_fact')
        local = FactInteractionBlock(8, 'local')
        for block in (cross, local):
            for layer in (block.a, block.b, block.c, block.d):
                torch.nn.init.eye_(layer.weight)
        valid = torch.tensor([[True, True, True]])
        data = torch.randn(1, 3, 8, requires_grad=True)
        cross(data, valid)[0, 0].sum().backward()
        self.assertGreater(data.grad[0, 1].abs().sum().item(), 1e-7)
        self.assertGreater(data.grad[0, 2].abs().sum().item(), 1e-7)
        local_data = data.detach().clone().requires_grad_(True)
        local(local_data, valid)[0, 0].sum().backward()
        self.assertEqual(local_data.grad[0, 1].abs().sum().item(), 0.)
        self.assertEqual(local_data.grad[0, 2].abs().sum().item(), 0.)

    def test_padded_fact_cannot_change_live_fact_outputs(self):
        for mode in ('cross_fact', 'local'):
            block = FactInteractionBlock(8, mode)
            mask = torch.tensor([[True, True, False]])
            data = torch.randn(1, 3, 8)
            changed = data.clone()
            changed[:, 2] = 999.
            first, second = block(data, mask), block(changed, mask)
            torch.testing.assert_close(first, second)
            self.assertEqual(first[:, 2].abs().sum().item(), 0.)

    def test_public_six_input_reader_forward_and_finite_backprop(self):
        cross, local = matched_reader_pair(input_dim=8, hidden_dim=8)
        facts = torch.randn(4, 4, 3, 8)
        question = torch.randn(4, 2, 8)
        candidate = torch.randn(4, 2, 8)
        masks = (torch.ones(4, 4, 3, dtype=torch.bool), torch.ones(4, 2, dtype=torch.bool),
                 torch.ones(4, 2, dtype=torch.bool))
        targets = torch.tensor([0, 1, 0, 1])
        for model in (cross, local):
            output = model(facts, question, candidate, *masks, steps=2, return_attention=True)
            self.assertEqual(output['logits'].shape, (4, 2))
            loss = F.cross_entropy(output['logits'], targets)
            loss.backward()
            for parameter in model.fact_block.parameters():
                self.assertIsNotNone(parameter.grad)
                self.assertTrue(torch.isfinite(parameter.grad).all())
            self.assertTrue(torch.isfinite(loss))

    def test_only_adapter_updates_when_base_is_frozen(self):
        cross, local = matched_reader_pair(input_dim=8, hidden_dim=8)
        facts = torch.randn(8, 4, 3, 8)
        question = torch.randn(8, 2, 8)
        candidate = torch.randn(8, 2, 8)
        masks = (torch.ones(8, 4, 3, dtype=torch.bool), torch.ones(8, 2, dtype=torch.bool),
                 torch.ones(8, 2, dtype=torch.bool))
        targets = torch.tensor([0, 1] * 4)
        for model in (cross, local):
            for name, parameter in model.named_parameters():
                parameter.requires_grad_(name.startswith('fact_block.'))
            original = {name: value.detach().clone() for name, value in model.state_dict().items()}
            optimizer = torch.optim.AdamW(model.fact_block.parameters(), lr=.005, foreach=False)
            for _ in range(3):
                optimizer.zero_grad(set_to_none=True)
                loss = F.cross_entropy(model(facts, question, candidate, *masks, steps=2), targets)
                loss.backward()
                optimizer.step()
            self.assertTrue(any(not torch.equal(value, original[name])
                                for name, value in model.state_dict().items()
                                if name.startswith('fact_block.')))
            self.assertTrue(all(torch.equal(value, original[name])
                                for name, value in model.state_dict().items()
                                if not name.startswith('fact_block.')))

    def test_missing_all_facts_is_rejected(self):
        block = FactInteractionBlock(8, 'cross_fact')
        with self.assertRaisesRegex(ValueError, 'nonempty masks'):
            block(torch.randn(1, 2, 8), torch.zeros(1, 2, dtype=torch.bool))


if __name__ == '__main__':
    unittest.main()
