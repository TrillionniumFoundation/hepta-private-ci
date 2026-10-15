import unittest

import torch
from torch.nn import functional as F

from group_core import Core
from execution_meter import WorkLedger
from paired_execution import PHASES
from test_execution_meter import policy


class GroupCoreTests(unittest.TestCase):
    def test_real_gradient_training_decreases_prediction_loss(self):
        torch.manual_seed(7)
        torch.set_num_threads(1)
        model = Core(8, hidden_dim=16)
        labels = torch.arange(8).repeat(3)
        tokens = F.one_hot(labels, 8).float().unsqueeze(1).repeat(1, 3, 1)
        optimizer = torch.optim.Adam(model.parameters(), lr=.03)
        initial = F.cross_entropy(model(tokens, steps=2), labels).item()
        for _ in range(40):
            optimizer.zero_grad()
            loss = F.cross_entropy(model(tokens, steps=2), labels)
            loss.backward()
            optimizer.step()
        self.assertLess(F.cross_entropy(model(tokens, steps=2), labels).item(), initial * .2)
        self.assertEqual(model(tokens, steps=2).argmax(-1).tolist(), labels.tolist())

    def test_masked_evidence_and_state_reset_change_execution(self):
        torch.manual_seed(4)
        model = Core(8, hidden_dim=16)
        tokens = torch.randn(2, 3, 8)
        mask = torch.tensor([[True, True, False], [True, True, False]])
        altered = tokens.clone()
        altered[:, 2] = 1000
        self.assertTrue(torch.equal(model(tokens, mask=mask), model(altered, mask=mask)))
        self.assertFalse(torch.equal(model(tokens, steps=3), model(tokens, steps=3, reset_state=True)))
        state, _ = model.step(tokens)
        self.assertLessEqual(state.abs().max().item(), 1)
        with self.assertRaises(ValueError):
            model(tokens, mask=torch.zeros_like(mask))
        with self.assertRaises(ValueError):
            model(tokens, steps=65)

    def test_forward_and_backward_have_complete_strict_work_coverage(self):
        model = Core(8, hidden_dim=16)
        tokens, labels = torch.randn(4, 3, 8), torch.tensor([0, 1, 2, 3])
        mask = torch.tensor([[True, True, False]] * 4)
        meter = WorkLedger(policy("strict"), dict.fromkeys(PHASES, 10**9))
        with meter.scope("train", "bank"):
            F.cross_entropy(model(tokens, steps=2, mask=mask), labels).backward()
        report = meter.report()
        self.assertEqual(report["unknown_operators"], {})
        self.assertGreater(report["phase_flops"]["train"], 0)


if __name__ == "__main__":
    unittest.main()
