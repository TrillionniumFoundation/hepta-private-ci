import itertools
import unittest

import torch
from torch.nn import functional as F

from execution_meter import WorkLedger
from group_reader import Reader
from paired_execution import PHASES
from test_execution_meter import policy


def binding_fixture():
    """All binary value assignments: query alone is exactly uninformative."""
    facts, query, target = [], [], []
    for assignment in itertools.product((0, 1), repeat=3):
        for asked in range(3):
            row = torch.zeros(3, 8)
            for key, value in enumerate(assignment):
                row[key, key] = 1
                row[key, 3 + value] = 1
            facts.append(row)
            query.append(F.one_hot(torch.tensor(asked), 8).float())
            target.append(assignment[asked])
    return torch.stack(facts), torch.stack(query), torch.tensor(target)


class ReaderTests(unittest.TestCase):
    def setUp(self):
        torch.manual_seed(11)
        torch.set_num_threads(1)

    def test_query_conditions_first_hop_and_padding_permutation_are_respected(self):
        model = Reader(8, 16)
        facts, query, _ = binding_fixture()
        mask = torch.ones(24, 3, dtype=torch.bool)
        trace = model(facts, query, steps=2, mask=mask, return_attention=True)
        changed = model(facts, query.roll(1, 0), steps=2, mask=mask, return_attention=True)
        self.assertFalse(torch.equal(trace["attentions"][0], changed["attentions"][0]))
        permutation = torch.tensor([2, 0, 1])
        permuted = model(facts[:, permutation], query, steps=2, mask=mask[:, permutation])
        torch.testing.assert_close(trace["logits"], permuted)
        padded = torch.cat((facts, torch.randn(24, 1, 8) * 100), dim=1)
        padded_mask = torch.cat((mask, torch.zeros(24, 1, dtype=torch.bool)), dim=1)
        torch.testing.assert_close(trace["logits"], model(padded, query, steps=2, mask=padded_mask))
        empty = model(facts, query, mask=torch.zeros_like(mask), return_attention=True)
        self.assertTrue(torch.equal(empty["attentions"][0], torch.zeros_like(mask, dtype=torch.float32)))
        self.assertTrue(torch.isfinite(empty["logits"]).all())
        self.assertLessEqual(empty["state"].abs().max().item(), 1)

    def test_tiny_binding_overfit_requires_evidence_and_has_strict_gradients(self):
        model = Reader(8, 16)
        facts, query, target = binding_fixture()
        optimizer = torch.optim.Adam(model.parameters(), lr=.025, foreach=False)
        initial = F.cross_entropy(model(facts, query, steps=2), target).item()
        for _ in range(180):
            optimizer.zero_grad()
            F.cross_entropy(model(facts, query, steps=2), target).backward()
            optimizer.step()
        self.assertLess(F.cross_entropy(model(facts, query, steps=2), target).item(), initial * .1)
        self.assertGreaterEqual((model(facts, query, steps=2).argmax(-1) == target).float().mean().item(), .95)
        deleted = model(facts, query, steps=2, mask=torch.zeros(24, 3, dtype=torch.bool))
        self.assertEqual((deleted.argmax(-1) == target).float().mean().item(), .5)
        meter = WorkLedger(policy("strict"), dict.fromkeys(PHASES, 10**9))
        with meter.scope("train", "bank"):
            F.cross_entropy(model(facts, query, steps=2), target).backward()
        self.assertEqual(meter.report()["unknown_operators"], {})
        self.assertGreater(model.attention_query.weight.grad.abs().sum().item(), 0)


if __name__ == "__main__":
    unittest.main()
